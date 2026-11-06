"""Coverage (decision D107): where the project's devices were heard, and by which gateway.

Positions joined to the receptions of the same source event: a heard position carries the
best RSSI of its receptions, and on request the paths to the gateways that heard it (D368).
Points at every zoom, capped; hexagons aggregated in the database (PostGIS `ST_HexagonGrid`)
on request.
It shows only where devices were, never where nobody walked."""

import json
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import (
    ScopeContext,
    require_scope_permission,
)
from protect_api.routers.map import _bbox
from shared.connectivity.instances import (
    Groups,
    canonical_source,
    instance_groups,
    siblings_of,
)
from shared.database import get_session
from shared.models import Gateway
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["gateways"])

MAX_HOURS = 24 * 90
# Points are the default at every zoom (decision D123): the newest this many in view.
MAX_POINTS = 10000
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
        None,
        description="Only receptions by these registry gateways: what each of them heard "
        "(decision D373)",
    ),
    device_id: list[uuid.UUID] | None = Query(
        None,
        description="Only positions of these devices, every reception of them; with "
        "`gateway_id` the union of both (decision D373)",
    ),
    mode: str | None = Query(
        None,
        pattern="^(points|hexagons)$",
        description="Points at every zoom unless hexagons are asked for (decision D123)",
    ),
    lines: bool = Query(
        False,
        description="With the points, a line from each heard position to every gateway that "
        "received it and has a location (decision D368)",
    ),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> CoverageResponse:
    """Heard positions of the project in the window and viewport as points, the newest first
    up to a cap, or as hexagons with the count and best signal on request, plus the share per
    gateway. With `lines`, the points come with the paths the uplinks took: one `LineString`
    from the position to each gateway that received it, for the gateways with a location."""
    until = utc_now()
    since = until - timedelta(hours=hours)
    box = _bbox(bbox) or (-180.0, -90.0, 180.0, 90.0)
    params: dict[str, Any] = {
        "project_id": context.project_id,
        "since": since,
        "until": until,
        "west": box[0],
        "south": box[1],
        "east": box[2],
        "north": box[3],
    }
    groups = await instance_groups(session)
    device_filter = ""
    if context.visibility.limited:
        params["scope_devices"] = list(context.visibility.device_ids or ())
        device_filter = " AND p.device_id = ANY(CAST(:scope_devices AS uuid[]))"
    # the selection (decision D373): the receptions of the named gateways, the positions of
    # the named devices with every reception, or the union of both
    selection: list[str] = []
    if gateway_id:
        pairs = (
            await session.execute(
                select(Gateway.data_source_id, Gateway.external_id).where(
                    Gateway.id.in_(gateway_id)
                )
            )
        ).all()
        if not pairs and not device_id:
            return CoverageResponse(hours=hours, mode="points", total=0, features=[], gateways=[])
        clauses = []
        for i, (source_id, external_id) in enumerate(pairs):
            # the receptions of every sibling source of the gateway's instance (D376)
            clauses.append(
                f"(r.data_source_id = ANY(CAST(:gs{i} AS uuid[])) AND r.gateway_id = :gx{i})"
            )
            params[f"gs{i}"] = list(siblings_of(groups, source_id))
            params[f"gx{i}"] = external_id
        if clauses:
            selection.append("(" + " OR ".join(clauses) + ")")
    if device_id:
        params["selected_devices"] = list(device_id)
        selection.append("p.device_id = ANY(CAST(:selected_devices AS uuid[]))")
    selection_filter = " AND (" + " OR ".join(selection) + ")" if selection else ""
    # Every position of the window and the view joined to the receptions of its uplink, which
    # `ix_gateway_receptions_device_event` answers with one lookup per position (D371, Tim,
    # 2026-11-06: 47 s over Okonjima's 30 days before it, every position walking the device's
    # receptions of the window). Nothing joins the CTEs to one another afterwards: Postgres
    # estimates a CTE at a handful of rows and nests the loops, and a join of the drawn points
    # to the heard rows cost 85 s over 30,000 by 8,500 rows; the rank by time inside the heard
    # rows picks the drawn points and their paths instead.
    heard = f"""
        heard AS (
            SELECT p.id, p.time, p.geom, r.rssi, r.gateway_id, r.data_source_id
            FROM positions p
            JOIN gateway_receptions r
              ON r.device_id = p.device_id AND r.source_event_id = p.source_event_id
             AND r.time >= :since
            WHERE p.record_type <> 'network'
              AND (CAST(:project_id AS uuid) IS NULL
                   OR p.project_id = CAST(:project_id AS uuid))
              AND p.time >= :since AND p.time < :until
              AND p.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)
              {device_filter}{selection_filter}
        ),
        best AS (
            SELECT id, time, geom, MAX(rssi) AS rssi, COUNT(*) AS gateways
            FROM heard GROUP BY id, time, geom
        )
    """
    if mode == "hexagons":
        return await _hexagons(session, heard, params, hours, zoom, groups)
    # One statement for the shares, the total, the drawn points and their paths, so the heard
    # positions are computed once (D371); the paths are one MultiLineString per gateway, the
    # lines from the drawn points to the gateway's location, 29,640 features of 8 MB on
    # Okonjima's 30 days as one LineString each, 14 of 3 MB this way.
    statement = f"""
        WITH {heard},
        ranked AS (
            SELECT id, time, geom, rssi, gateway_id, data_source_id,
                   DENSE_RANK() OVER (ORDER BY time DESC, id DESC) AS rank
            FROM heard
        ),
        per_gateway AS (
            SELECT data_source_id, gateway_id, COUNT(DISTINCT id) AS n,
                   MAX(rssi) AS best_rssi, AVG(rssi) AS mean_rssi
            FROM heard GROUP BY data_source_id, gateway_id
        )
        SELECT 'gateway' AS kind, data_source_id, gateway_id, CAST(NULL AS text) AS name,
               n, best_rssi, mean_rssi, CAST(NULL AS text) AS geom,
               CAST(NULL AS bigint) AS gateways, CAST(NULL AS timestamptz) AS time,
               CAST(NULL AS bigint) AS position_id
        FROM per_gateway
        UNION ALL
        SELECT 'total', NULL, NULL, NULL, COUNT(DISTINCT id), NULL, NULL, NULL, NULL, NULL,
               NULL
        FROM heard
        UNION ALL
        SELECT 'point', NULL, NULL, NULL, NULL, MAX(rssi), NULL, ST_AsGeoJSON(geom), COUNT(*),
               time, id
        FROM ranked WHERE rank <= :limit GROUP BY id, time, geom
    """
    if lines:
        # a reception's source and the gateway's row may be sibling sources of one instance
        # (D376): both map to the instance's first source id and meet there
        mapping = ", ".join(
            f"(CAST(:ms{i} AS uuid), CAST(:mc{i} AS uuid))" for i in range(len(groups))
        )
        for i, (source_id, members) in enumerate(groups.items()):
            params[f"ms{i}"] = source_id
            params[f"mc{i}"] = members[0]
        statement += f"""
        UNION ALL
        SELECT 'path', mg.canonical, h.gateway_id,
               COALESCE(g.name_override, g.name, g.external_id), COUNT(*), NULL, NULL,
               ST_AsGeoJSON(ST_Collect(ST_MakeLine(h.geom, g.geom))), NULL, NULL, NULL
        FROM ranked h
        JOIN (VALUES {mapping}) AS mh(source_id, canonical) ON mh.source_id = h.data_source_id
        JOIN gateways g ON g.external_id = h.gateway_id
        JOIN (VALUES {mapping}) AS mg(source_id, canonical)
          ON mg.source_id = g.data_source_id AND mg.canonical = mh.canonical
        WHERE h.rank <= :limit AND g.geom IS NOT NULL
        GROUP BY mg.canonical, h.gateway_id, g.name_override, g.name, g.external_id
        """
    rows = (await session.execute(text(statement), {**params, "limit": MAX_POINTS})).all()
    total = next((int(row.n) for row in rows if row.kind == "total"), 0)
    gateways = await _shares(session, [row for row in rows if row.kind == "gateway"], total, groups)
    if total == 0:
        return CoverageResponse(hours=hours, mode="points", total=0, features=[], gateways=[])
    features = []
    for row in rows:
        if row.kind == "point":
            properties: dict[str, Any] = {
                "id": int(row.position_id),
                "best_rssi": row.best_rssi,
                "gateways": int(row.gateways),
                "time": row.time.isoformat(),
            }
        elif row.kind == "path":
            properties = {"kind": "path", "gateway": row.name, "receptions": int(row.n)}
        else:
            continue
        features.append(
            {"type": "Feature", "geometry": json.loads(row.geom), "properties": properties}
        )
    return CoverageResponse(
        hours=hours, mode="points", total=total, features=features, gateways=gateways
    )


async def _shares(
    session: AsyncSession, rows: list[Any], total: int, groups: Groups
) -> list[CoverageGateway]:
    """The share per gateway, named from the registry where the gateway is known; the
    receptions of sibling sources on one instance count together (D376)."""
    folded: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
    for r in rows:
        key = (canonical_source(groups, r.data_source_id), r.gateway_id)
        entry = folded.setdefault(key, {"n": 0, "best": None, "rssi": 0.0, "rssi_n": 0})
        n = int(r.n)
        entry["n"] += n
        if r.best_rssi is not None:
            best = float(r.best_rssi)
            entry["best"] = best if entry["best"] is None else max(entry["best"], best)
        if r.mean_rssi is not None:
            entry["rssi"] += float(r.mean_rssi) * n
            entry["rssi_n"] += n
    registry: dict[tuple[uuid.UUID, str], Gateway] = {}
    if folded:
        registry = {
            (canonical_source(groups, g.data_source_id), g.external_id): g
            for g in (
                await session.scalars(
                    select(Gateway).where(
                        Gateway.data_source_id.in_(
                            {s for key in folded for s in siblings_of(groups, key[0])}
                        ),
                        Gateway.external_id.in_({key[1] for key in folded}),
                    )
                )
            ).all()
        }
    shares = []
    for key, e in sorted(folded.items(), key=lambda item: int(item[1]["n"]), reverse=True):
        g = registry.get(key)
        shares.append(
            CoverageGateway(
                gateway_id=g.id if g else None,
                external_id=key[1],
                name=(g.name_override or g.name or key[1]) if g else key[1],
                data_source_id=g.data_source_id if g else key[0],
                heard=e["n"],
                share=round(e["n"] / total, 3) if total else 0.0,
                best_rssi=e["best"],
                mean_rssi=round(e["rssi"] / e["rssi_n"], 1) if e["rssi_n"] else None,
            )
        )
    return shares


async def _hexagons(
    session: AsyncSession,
    heard: str,
    params: dict[str, Any],
    hours: int,
    zoom: int,
    groups: Groups,
) -> CoverageResponse:
    """The hexagon aggregation (API users, decision D123): the shares and the total first,
    then the cells of the viewport sized by zoom."""
    shares_rows = (
        await session.execute(
            text(
                f"""
                WITH {heard}
                SELECT data_source_id, gateway_id, COUNT(DISTINCT id) AS n,
                       MAX(rssi) AS best_rssi, AVG(rssi) AS mean_rssi,
                       (SELECT COUNT(*) FROM best) AS total
                FROM heard GROUP BY data_source_id, gateway_id
                """
            ),
            params,
        )
    ).all()
    total = int(shares_rows[0].total) if shares_rows else 0
    gateways = await _shares(session, list(shares_rows), total, groups)
    if total == 0:
        return CoverageResponse(hours=hours, mode="points", total=0, features=[], gateways=[])
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
