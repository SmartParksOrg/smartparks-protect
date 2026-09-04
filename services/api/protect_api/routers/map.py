"""Live map data (architecture 13.2 to 13.4).

- `GET /projects/{id}/map/current`: entity current state as GeoJSON, bounded by viewport and a
  row limit. The response says how many entities the project has so the client can switch to
  tiles above the threshold.
- `GET /projects/{id}/map/tiles/{z}/{x}/{y}.mvt`: the same as Mapbox vector tiles from PostGIS.
- `GET /projects/{id}/tracks`: positions of one entity or device over a period as a LineString
  with one time per vertex, decimated to `max_points` (architecture 13.4). Raw points remain
  reachable through the positions endpoint.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import ProjectContext, require_permission
from shared.curation.effective import effective_geom, effective_time, in_window, visible
from shared.database import get_session
from shared.models import Entity, EntityCurrentState, EntityType, Position
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["map"])

MAX_FEATURES = 5000
TILE_THRESHOLD = 2000
MAX_TRACK_POINTS = 10000
DEFAULT_TRACK_POINTS = 5000


class CurrentStateResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]]
    total: int
    returned: int
    use_tiles: bool


class TrackResponse(BaseModel):
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    time_from: datetime
    time_to: datetime
    total_points: int
    returned_points: int
    step: int
    geometry: dict[str, Any]
    times: list[datetime]
    first_position_id: int | None
    last_position_id: int | None


def _bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "bbox must be west,south,east,north"
        ) from None
    if not (
        -180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bbox out of range")
    return west, south, east, north


@router.get("/map/current", response_model=CurrentStateResponse)
async def current_state(
    bbox: str | None = Query(None, description="west,south,east,north in WGS84"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> CurrentStateResponse:
    base = (
        select(
            EntityCurrentState,
            Entity.name,
            Entity.status,
            Entity.icon_key,
            EntityType.key,
            EntityType.icon_key,
            EntityType.group_key,
            func.ST_AsGeoJSON(EntityCurrentState.latest_position),
        )
        .join(Entity, Entity.id == EntityCurrentState.entity_id)
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .where(
            EntityCurrentState.project_id == context.project.id,
            EntityCurrentState.latest_position.is_not(None),
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(EntityCurrentState)
        .where(
            EntityCurrentState.project_id == context.project.id,
            EntityCurrentState.latest_position.is_not(None),
        )
    )
    box = _bbox(bbox)
    if box is not None:
        base = base.where(
            func.ST_Intersects(EntityCurrentState.latest_position, func.ST_MakeEnvelope(*box, 4326))
        )
    rows = (await session.execute(base.order_by(EntityCurrentState.entity_id).limit(limit))).all()
    features = []
    for state, name, entity_status, icon_override, type_key, type_icon, group_key, geojson in rows:
        import json

        features.append(
            {
                "type": "Feature",
                "id": str(state.entity_id),
                "geometry": json.loads(geojson),
                "properties": {
                    "entity_id": str(state.entity_id),
                    "name": name,
                    "status": entity_status,
                    "entity_type": type_key,
                    "group": group_key,
                    "icon_key": icon_override or type_icon,
                    "device_id": str(state.device_id) if state.device_id else None,
                    "last_seen_at": state.last_seen_at.isoformat() if state.last_seen_at else None,
                    "position_time": state.latest_position_time.isoformat()
                    if state.latest_position_time
                    else None,
                    "active_alert_count": state.active_alert_count,
                },
            }
        )
    return CurrentStateResponse(
        features=features,
        total=int(total or 0),
        returned=len(features),
        use_tiles=int(total or 0) > TILE_THRESHOLD,
    )


@router.get("/map/tiles/{z}/{x}/{y}.mvt", response_class=Response)
async def current_state_tile(
    z: int,
    x: int,
    y: int,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Entity current state as a Mapbox vector tile, layer `entities`."""
    if not (0 <= z <= 22) or not (0 <= x < 2**z) or not (0 <= y < 2**z):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile out of range")
    sql = text(
        """
        WITH bounds AS (SELECT ST_TileEnvelope(:z, :x, :y) AS geom),
        rows AS (
            SELECT ST_AsMVTGeom(ST_Transform(s.latest_position, 3857), bounds.geom, 4096, 64, true)
                       AS geom,
                   s.entity_id::text AS entity_id, e.name, e.status,
                   et.key AS entity_type, et.group_key AS "group",
                   COALESCE(e.icon_key, et.icon_key) AS icon_key,
                   s.device_id::text AS device_id,
                   to_char(s.last_seen_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                       AS last_seen_at,
                   s.active_alert_count
            FROM entity_current_state s
            JOIN entities e ON e.id = s.entity_id
            JOIN entity_types et ON et.id = e.entity_type_id
            CROSS JOIN bounds
            WHERE s.project_id = :project_id
              AND s.latest_position IS NOT NULL
              AND ST_Transform(s.latest_position, 3857) && bounds.geom
            LIMIT :limit
        )
        SELECT ST_AsMVT(rows, 'entities', 4096, 'geom') FROM rows
        """
    )
    tile = await session.scalar(
        sql, {"z": z, "x": x, "y": y, "project_id": context.project.id, "limit": MAX_FEATURES}
    )
    return Response(content=bytes(tile or b""), media_type="application/vnd.mapbox-vector-tile")


@router.get("/tracks", response_model=TrackResponse)
async def track(
    entity_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    max_points: int = Query(DEFAULT_TRACK_POINTS, ge=2, le=MAX_TRACK_POINTS),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> TrackResponse:
    """Track of one entity or device attributed to the project. Longer periods are decimated so
    at most `max_points` vertices return; every vertex keeps its time. Default period: 24 hours."""
    if (entity_id is None) == (device_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give exactly one of entity_id or device_id"
        )
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    conditions = [
        Position.project_id == context.project.id,
        in_window(Position, time_from, time_to),
        visible(Position),
    ]
    conditions.append(
        Position.entity_id == entity_id
        if entity_id is not None
        else Position.device_id == device_id
    )
    total = int(
        await session.scalar(select(func.count()).select_from(Position).where(*conditions)) or 0
    )
    step = max(1, -(-total // max_points))  # ceil
    numbered = (
        select(
            Position.id,
            effective_time(Position).label("time"),
            func.ST_X(effective_geom()).label("lon"),
            func.ST_Y(effective_geom()).label("lat"),
            func.row_number().over(order_by=effective_time(Position)).label("rn"),
        )
        .where(*conditions)
        .subquery()
    )
    rows = (
        await session.execute(
            select(numbered.c.id, numbered.c.time, numbered.c.lon, numbered.c.lat)
            .where(((numbered.c.rn - 1) % step == 0) | (numbered.c.rn == total))
            .order_by(numbered.c.time)
        )
    ).all()
    coordinates = [[lon, lat] for _, _, lon, lat in rows]
    geometry: dict[str, Any] = (
        {"type": "LineString", "coordinates": coordinates}
        if len(coordinates) >= 2
        else {"type": "MultiPoint", "coordinates": coordinates}
    )
    return TrackResponse(
        entity_id=entity_id,
        device_id=device_id,
        time_from=time_from,
        time_to=time_to,
        total_points=total,
        returned_points=len(rows),
        step=step,
        geometry=geometry,
        times=[r[1] for r in rows],
        first_position_id=rows[0][0] if rows else None,
        last_position_id=rows[-1][0] if rows else None,
    )
