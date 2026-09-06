"""Coverage (decision D107): where the project's collars were heard, and by which gateway.

Positions joined to the receptions of the same source event: a heard position carries the
best RSSI of its receptions. Zoomed out the viewport is tiled into hexagons aggregated in the
database (PostGIS `ST_HexagonGrid`); zoomed in the positions themselves come back, capped.
It shows only where collars were, never where nobody walked."""

import json
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import ProjectContext, require_permission
from protect_api.routers.map import _bbox
from shared.database import get_session
from shared.models import Gateway
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["gateways"])

MAX_HOURS = 24 * 90
MAX_POINTS = 5000
POINTS_FROM_ZOOM = 13
WORLD_M = 40_075_016.686


class CoverageGateway(BaseModel):
    gateway_id: uuid.UUID | None = Field(default=None, description="Registry id when known")
    external_id: str
    name: str
    data_source_id: uuid.UUID
    heard: int = Field(description="Positions this gateway heard in the window and view")
    share: float = Field(description="Of every heard position, 0 to 1")
    best_rssi: float | None
    mean_rssi: float | None


class CoverageResponse(BaseModel):
    hours: int
    mode: str = Field(description="points or hexagons")
    hexagon_m: float | None = Field(default=None, description="Hexagon size in metres, if any")
    total: int = Field(description="Positions heard by at least one gateway in the window and view")
    features: list[dict[str, Any]]
    gateways: list[CoverageGateway]


def hexagon_size(zoom: int) -> float:
    """A hexagon about an eighth of a tile wide at the zoom, in metres of Web Mercator."""
    return float(WORLD_M / (2**zoom) / 8)


@router.get("/coverage", response_model=CoverageResponse)
async def coverage(
    bbox: str | None = Query(None, description="west,south,east,north in WGS84"),
    zoom: int = Query(8, ge=0, le=22),
    hours: int = Query(24 * 7, ge=1, le=MAX_HOURS),
    gateway_id: list[uuid.UUID] | None = Query(
        None, description="Only receptions by these registry gateways"
    ),
    mode: str | None = Query(
        None,
        pattern="^(points|hexagons)$",
        description="Force a mode; without it points from zoom 13 or up to 500 positions",
    ),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> CoverageResponse:
    """Heard positions of the project in the window and viewport, as points from zoom 13 and
    as hexagons with the count and best signal below, plus the share per gateway."""
    until = utc_now()
    since = until - timedelta(hours=hours)
    box = _bbox(bbox) or (-180.0, -90.0, 180.0, 90.0)
    params: dict[str, Any] = {
        "project_id": context.project.id,
        "since": since,
        "until": until,
        "west": box[0],
        "south": box[1],
        "east": box[2],
        "north": box[3],
    }
    gateway_filter = ""
    if gateway_id:
        pairs = (
            await session.execute(
                select(Gateway.data_source_id, Gateway.external_id).where(
                    Gateway.id.in_(gateway_id)
                )
            )
        ).all()
        if not pairs:
            return CoverageResponse(hours=hours, mode="points", total=0, features=[], gateways=[])
        clauses = []
        for i, (source_id, external_id) in enumerate(pairs):
            clauses.append(f"(r.data_source_id = :gs{i} AND r.gateway_id = :gx{i})")
            params[f"gs{i}"] = source_id
            params[f"gx{i}"] = external_id
        gateway_filter = " AND (" + " OR ".join(clauses) + ")"
    heard = f"""
        heard AS (
            SELECT p.id, p.time, p.geom, r.rssi, r.gateway_id, r.data_source_id
            FROM positions p
            JOIN gateway_receptions r
              ON r.device_id = p.device_id AND r.source_event_id = p.source_event_id
            WHERE p.project_id = :project_id
              AND p.time >= :since AND p.time < :until
              AND p.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
              {gateway_filter}
        ),
        best AS (
            SELECT id, time, geom, MAX(rssi) AS rssi, COUNT(*) AS gateways
            FROM heard GROUP BY id, time, geom
        )
    """
    per_gateway = (
        await session.execute(
            text(
                f"""
                WITH {heard}
                SELECT data_source_id, gateway_id, COUNT(DISTINCT id) AS heard,
                       MAX(rssi) AS best_rssi, AVG(rssi) AS mean_rssi,
                       (SELECT COUNT(*) FROM best) AS total
                FROM heard
                GROUP BY data_source_id, gateway_id
                ORDER BY heard DESC
                """
            ),
            params,
        )
    ).all()
    total = int(per_gateway[0].total) if per_gateway else 0
    registry = {
        (g.data_source_id, g.external_id): g
        for g in (
            await session.scalars(
                select(Gateway).where(
                    Gateway.data_source_id.in_({r.data_source_id for r in per_gateway}),
                    Gateway.external_id.in_({r.gateway_id for r in per_gateway}),
                )
            )
        ).all()
    }
    gateways = []
    for r in per_gateway:
        g = registry.get((r.data_source_id, r.gateway_id))
        gateways.append(
            CoverageGateway(
                gateway_id=g.id if g else None,
                external_id=r.gateway_id,
                name=(g.name_override or g.name or r.gateway_id) if g else r.gateway_id,
                data_source_id=r.data_source_id,
                heard=int(r.heard),
                share=round(int(r.heard) / total, 3) if total else 0.0,
                best_rssi=float(r.best_rssi) if r.best_rssi is not None else None,
                mean_rssi=round(float(r.mean_rssi), 1) if r.mean_rssi is not None else None,
            )
        )
    if total == 0:
        return CoverageResponse(hours=hours, mode="points", total=0, features=[], gateways=[])

    as_points = mode == "points" if mode else (zoom >= POINTS_FROM_ZOOM or total <= 500)
    if as_points:
        rows = (
            await session.execute(
                text(
                    f"""
                    WITH {heard}
                    SELECT ST_AsGeoJSON(geom) AS geom, rssi, gateways, time
                    FROM best ORDER BY time DESC LIMIT :limit
                    """
                ),
                {**params, "limit": MAX_POINTS},
            )
        ).all()
        features = [
            {
                "type": "Feature",
                "geometry": json.loads(row.geom),
                "properties": {
                    "best_rssi": row.rssi,
                    "gateways": int(row.gateways),
                    "time": row.time.isoformat(),
                },
            }
            for row in rows
        ]
        return CoverageResponse(
            hours=hours, mode="points", total=total, features=features, gateways=gateways
        )

    size = hexagon_size(zoom)
    rows = (
        await session.execute(
            text(
                f"""
                WITH {heard},
                cells AS (
                    SELECT h.geom AS cell, b.rssi
                    FROM ST_HexagonGrid(
                        :size,
                        ST_Transform(ST_MakeEnvelope(:west, :south, :east, :north, 4326), 3857)
                    ) AS h
                    JOIN best b ON ST_Intersects(ST_Transform(b.geom, 3857), h.geom)
                )
                SELECT ST_AsGeoJSON(ST_Transform(cell, 4326)) AS geom, COUNT(*) AS n,
                       MAX(rssi) AS best_rssi, AVG(rssi) AS mean_rssi
                FROM cells GROUP BY cell
                """
            ),
            {**params, "size": size},
        )
    ).all()
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row.geom),
            "properties": {
                "count": int(row.n),
                "best_rssi": float(row.best_rssi) if row.best_rssi is not None else None,
                "mean_rssi": round(float(row.mean_rssi), 1) if row.mean_rssi is not None else None,
            },
        }
        for row in rows
    ]
    return CoverageResponse(
        hours=hours,
        mode="hexagons",
        hexagon_m=round(size),
        total=total,
        features=features,
        gateways=gateways,
    )
