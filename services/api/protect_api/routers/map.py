"""Live map data (architecture 13.2 to 13.4).

- `GET /projects/{id}/map/current`: entity current state as GeoJSON, bounded by viewport and a
  row limit. The response says how many entities the project has so the client can switch to
  tiles above the threshold.
- `GET /projects/{id}/map/tiles/{z}/{x}/{y}.mvt`: the same as Mapbox vector tiles from PostGIS.
- `GET /projects/{id}/tracks`: positions of one entity or device over a period as a LineString
  with one time per vertex, decimated to `max_points` (architecture 13.4). Raw points remain
  reachable through the positions endpoint.
- `GET /projects/{id}/positions/at`: the position of an entity or device at one device time with
  the measurements of that moment, what a click on a track point opens (phase 19).
- `GET /projects/{id}/map/heat`: the positions behind the heatmap (decision D138): the newest
  `MAX_HEAT_POINTS` in the viewport and window for the given entities and devices.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from protect_api.deps import (
    ScopeContext,
    require_scope_permission,
)
from protect_api.routers.data import PositionRead, position_read
from shared.connectivity.network_location import NETWORK_RECORD_TYPE
from shared.curation.effective import (
    at_time,
    device_fix,
    effective_geom,
    effective_time,
    effective_value_num,
    in_window,
    sources_filter,
    visible,
)
from shared.database import get_session
from shared.device_drivers.registry import DRIVERS
from shared.domain.health import device_health
from shared.models import (
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityCurrentState,
    EntityType,
    Measurement,
    Metric,
    Position,
)
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["map"])

MAX_FEATURES = 5000
TILE_THRESHOLD = 2000
MAX_TRACK_POINTS = 10000
DEFAULT_TRACK_POINTS = 5000
MAX_HEAT_POINTS = 10000
MAX_HEAT_HOURS = 24 * 90
MAX_HEAT_IDS = 500
# The devices scanned per request, most recently seen first: every device costs a scan of its
# segment of the window, so the request stays bounded in time as well as in points.
MAX_HEAT_DEVICES = 200


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


class HeatResponse(BaseModel):
    """The points of the heatmap layer: bare positions, the newest first up to a cap."""

    type: str = "FeatureCollection"
    hours: int
    returned: int
    capped: bool = Field(description="More positions than the cap were in view")
    devices_scanned: int = Field(description="Devices whose positions were read")
    devices_total: int = Field(description="Devices seen in the window that qualify")
    features: list[dict[str, Any]]


class PointMeasurement(BaseModel):
    metric_key: str
    label: str
    unit: str | None
    value: float | bool | str | dict[str, Any] | None


class PointRead(BaseModel):
    """One position with the measurements of the same device at the same device time."""

    position: PositionRead
    device_name: str | None
    entity_name: str | None
    measurements: list[PointMeasurement]


def type_path(parent_label: str | None, label: str) -> str:
    """ "Vehicles · 4x4" for a sub-type, the label alone for a type (decision D166)."""
    return f"{parent_label} · {label}" if parent_label else label


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
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> CurrentStateResponse:
    parent_type = aliased(EntityType)
    base = (
        select(
            EntityCurrentState,
            Entity.name,
            Entity.status,
            Entity.icon_key,
            EntityType.key,
            EntityType.icon_key,
            EntityType.group_key,
            Entity.group_id,
            func.ST_AsGeoJSON(EntityCurrentState.latest_position),
            Entity.picture_updated_at,
            Entity.project_id,
            EntityType.label,
            parent_type.label,
        )
        .join(Entity, Entity.id == EntityCurrentState.entity_id)
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .outerjoin(parent_type, parent_type.id == EntityType.parent_id)
        .where(
            context.where(EntityCurrentState.project_id),
            EntityCurrentState.latest_position.is_not(None),
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(EntityCurrentState)
        .where(
            context.where(EntityCurrentState.project_id),
            EntityCurrentState.latest_position.is_not(None),
        )
    )
    box = _bbox(bbox)
    if box is not None:
        base = base.where(
            func.ST_Intersects(EntityCurrentState.latest_position, func.ST_MakeEnvelope(*box, 4326))
        )
    rows = (await session.execute(base.order_by(EntityCurrentState.entity_id).limit(limit))).all()
    device_ids = {row[0].device_id for row in rows if row[0].device_id}
    device_states: dict[uuid.UUID, DeviceCurrentState] = {}
    drivers_by_device: dict[uuid.UUID, str | None] = {}
    if device_ids:
        device_states = {
            s.device_id: s
            for s in (
                await session.scalars(
                    select(DeviceCurrentState).where(DeviceCurrentState.device_id.in_(device_ids))
                )
            ).all()
        }
        drivers_by_device = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Device.id, DeviceType.driver_key)
                    .join(DeviceType, DeviceType.id == Device.device_type_id)
                    .where(Device.id.in_(device_ids))
                )
            ).all()
        }
    # when the device tracking the entity today was assigned to it: the start of the "since the
    # device was assigned" track length in the map's track settings
    assigned_since: dict[uuid.UUID, datetime] = {}
    if device_ids:
        assigned_since = {
            entity_id: since
            for entity_id, since in (
                await session.execute(
                    select(
                        DeviceEntityAssignment.entity_id,
                        func.lower(DeviceEntityAssignment.validity),
                    ).where(
                        DeviceEntityAssignment.device_id.in_(device_ids),
                        DeviceEntityAssignment.validity.op("@>")(utc_now()),
                    )
                )
            ).all()
        }
    features = []
    for row in rows:
        state, name, entity_status, icon_override, type_key, type_icon, group_key = row[:7]
        group_id, geojson, picture_updated_at, entity_project_id = row[7], row[8], row[9], row[10]
        type_label, parent_label = row[11], row[12]
        import json

        device_state = device_states.get(state.device_id) if state.device_id else None
        health = None
        if device_state is not None:
            driver = DRIVERS.get(drivers_by_device.get(state.device_id) or "")
            health = device_health(
                getattr(driver, "health", None),
                latest_measurements=device_state.latest_measurements,
                latest_state=device_state.latest_state,
                latest_state_time=device_state.latest_state_time,
                last_seen_at=device_state.last_seen_at,
            )

        features.append(
            {
                "type": "Feature",
                "id": str(state.entity_id),
                "geometry": json.loads(geojson),
                "properties": {
                    "entity_id": str(state.entity_id),
                    "project_id": str(entity_project_id),
                    "name": name,
                    "status": entity_status,
                    "entity_type": type_key,
                    "entity_type_label": type_path(parent_label, type_label),
                    "group": group_key,
                    "group_id": str(group_id) if group_id else None,
                    "icon_key": icon_override or type_icon,
                    "picture_updated_at": picture_updated_at.isoformat()
                    if picture_updated_at
                    else None,
                    "device_id": str(state.device_id) if state.device_id else None,
                    "assigned_since": assigned_since[state.entity_id].isoformat()
                    if state.entity_id in assigned_since
                    else None,
                    "last_seen_at": state.last_seen_at.isoformat() if state.last_seen_at else None,
                    "position_time": state.latest_position_time.isoformat()
                    if state.latest_position_time
                    else None,
                    "position_kind": state.latest_position_kind,
                    "active_alert_count": state.active_alert_count,
                    "health_level": health.level if health else None,
                    "battery_voltage": device_state.battery_voltage if device_state else None,
                    "last_status_at": health.last_status_at.isoformat()
                    if health and health.last_status_at
                    else None,
                    "device_last_seen_at": device_state.last_seen_at.isoformat()
                    if device_state and device_state.last_seen_at
                    else None,
                },
            }
        )
    return CurrentStateResponse(
        features=features,
        total=int(total or 0),
        returned=len(features),
        use_tiles=int(total or 0) > TILE_THRESHOLD,
    )


@router.get("/map/devices", response_model=CurrentStateResponse)
async def devices_state(
    bbox: str | None = Query(None, description="west,south,east,north in WGS84"),
    limit: int = Query(MAX_FEATURES, ge=1, le=MAX_FEATURES),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> CurrentStateResponse:
    """The device layer (decision D111): every device assigned to the project today with its
    latest position from the device's own current state, whether or not it tracks an entity.
    A device without a position comes back without geometry so the panel can list it; with a
    `bbox` only positioned devices inside it return."""
    import json

    now = utc_now()
    assigned = (
        select(
            DeviceProjectAssignment.device_id.label("device_id"),
            DeviceProjectAssignment.project_id.label("project_id"),
            func.lower(DeviceProjectAssignment.validity).label("since"),
        )
        .where(
            context.where(DeviceProjectAssignment.project_id),
            DeviceProjectAssignment.validity.op("@>")(now),
        )
        .subquery()
    )
    base = select(
        Device,
        DeviceType.key,
        DeviceType.icon_key,
        DeviceType.driver_key,
        DeviceType.label,
        DeviceCurrentState,
        assigned.c.since,
        assigned.c.project_id,
        func.ST_AsGeoJSON(DeviceCurrentState.latest_position),
    )
    if context.is_all:
        # the all scope (decision D120): devices in no project come too, with project None
        total = int(await session.scalar(select(func.count()).select_from(Device)) or 0)
        base = base.outerjoin(assigned, assigned.c.device_id == Device.id)
    else:
        total = int(await session.scalar(select(func.count()).select_from(assigned)) or 0)
        base = base.join(assigned, assigned.c.device_id == Device.id)
    base = base.join(DeviceType, DeviceType.id == Device.device_type_id).outerjoin(
        DeviceCurrentState, DeviceCurrentState.device_id == Device.id
    )
    box = _bbox(bbox)
    if box is not None:
        base = base.where(
            DeviceCurrentState.latest_position.is_not(None),
            func.ST_Intersects(
                DeviceCurrentState.latest_position, func.ST_MakeEnvelope(*box, 4326)
            ),
        )
    rows = (await session.execute(base.order_by(Device.name).limit(limit))).all()
    device_ids = [row[0].id for row in rows]
    tracking: dict[uuid.UUID, tuple[uuid.UUID, str, uuid.UUID | None]] = {}
    if device_ids:
        tracking = {
            device_id: (entity_id, name, group_id)
            for device_id, entity_id, name, group_id in (
                await session.execute(
                    select(
                        DeviceEntityAssignment.device_id, Entity.id, Entity.name, Entity.group_id
                    )
                    .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
                    .where(
                        DeviceEntityAssignment.device_id.in_(device_ids),
                        DeviceEntityAssignment.validity.op("@>")(now),
                    )
                )
            ).all()
        }
    features = []
    for row in rows:
        device, type_key, type_icon, driver_key, type_label = row[:5]
        state, since, device_project_id, geojson = row[5:9]
        health = None
        if state is not None:
            driver = DRIVERS.get(driver_key or "")
            health = device_health(
                getattr(driver, "health", None),
                latest_measurements=state.latest_measurements,
                latest_state=state.latest_state,
                latest_state_time=state.latest_state_time,
                last_seen_at=state.last_seen_at,
            )
        entity = tracking.get(device.id)
        features.append(
            {
                "type": "Feature",
                "id": str(device.id),
                "geometry": json.loads(geojson) if geojson else None,
                "properties": {
                    "device_id": str(device.id),
                    "project_id": str(device_project_id) if device_project_id else None,
                    "name": device.name,
                    "serial_number": device.serial_number,
                    "status": device.status,
                    "device_type": type_key,
                    "device_type_label": type_label,
                    "icon_key": type_icon,
                    "entity_id": str(entity[0]) if entity else None,
                    "entity_name": entity[1] if entity else None,
                    "group_id": str(entity[2]) if entity and entity[2] else None,
                    "project_since": since.isoformat() if since else None,
                    "last_seen_at": state.last_seen_at.isoformat()
                    if state and state.last_seen_at
                    else None,
                    "position_time": state.latest_position_time.isoformat()
                    if state and state.latest_position_time
                    else None,
                    "position_kind": state.latest_position_kind if state else None,
                    "health_level": health.level if health else None,
                    "battery_voltage": state.battery_voltage if state else None,
                    "last_status_at": health.last_status_at.isoformat()
                    if health and health.last_status_at
                    else None,
                    "picture_updated_at": device.picture_updated_at.isoformat()
                    if device.picture_updated_at
                    else None,
                },
            }
        )
    return CurrentStateResponse(
        features=features, total=total, returned=len(features), use_tiles=False
    )


@router.get("/map/tiles/{z}/{x}/{y}.mvt", response_class=Response)
async def current_state_tile(
    z: int,
    x: int,
    y: int,
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
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
                   CASE WHEN pt.id IS NULL THEN et.label ELSE pt.label || ' · ' || et.label END
                       AS entity_type_label,
                   e.group_id::text AS group_id,
                   e.project_id::text AS project_id,
                   COALESCE(e.icon_key, et.icon_key) AS icon_key,
                   s.device_id::text AS device_id,
                   to_char(s.last_seen_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                       AS last_seen_at,
                   s.active_alert_count
            FROM entity_current_state s
            JOIN entities e ON e.id = s.entity_id
            JOIN entity_types et ON et.id = e.entity_type_id
            LEFT JOIN entity_types pt ON pt.id = et.parent_id
            CROSS JOIN bounds
            WHERE (CAST(:project_id AS uuid) IS NULL OR s.project_id = CAST(:project_id AS uuid))
              AND s.latest_position IS NOT NULL
              AND ST_Transform(s.latest_position, 3857) && bounds.geom
            LIMIT :limit
        )
        SELECT ST_AsMVT(rows, 'entities', 4096, 'geom') FROM rows
        """
    )
    tile = await session.scalar(
        sql, {"z": z, "x": x, "y": y, "project_id": context.project_id, "limit": MAX_FEATURES}
    )
    return Response(content=bytes(tile or b""), media_type="application/vnd.mapbox-vector-tile")


@router.get("/tracks", response_model=TrackResponse)
async def track(
    entity_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    max_points: int = Query(DEFAULT_TRACK_POINTS, ge=2, le=MAX_TRACK_POINTS),
    sources: str = Query(
        "device",
        pattern="^(device|network|all)$",
        description="The device's own fixes (default), the network's locations, or both (D163)",
    ),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> TrackResponse:
    """Track of one entity or device attributed to the project. Longer periods are decimated so
    at most `max_points` vertices return; every vertex keeps its time. Default period: 24 hours,
    the device's own fixes unless `sources` says otherwise."""
    if (entity_id is None) == (device_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give exactly one of entity_id or device_id"
        )
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    conditions = [
        context.where(Position.project_id, unassigned=True),
        in_window(Position, time_from, time_to),
        visible(Position),
    ]
    source_clause = sources_filter(sources)
    if source_clause is not None:
        conditions.append(source_clause)
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


@router.get("/positions/at", response_model=PointRead)
async def position_at(
    time: datetime,
    entity_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PointRead:
    """The position of an entity or device at one device time (the effective time, exact) and the
    measurements its device reported at that moment: what a click on a track point opens. Both
    lookups go through the owner and time indexes; a device with several records at one time
    (a resend, a second record type) answers with the first position and every measurement."""
    if (entity_id is None) == (device_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give exactly one of entity_id or device_id"
        )
    when = require_aware(time)
    owner: ColumnElement[bool] = (
        Position.entity_id == entity_id
        if entity_id is not None
        else Position.device_id == device_id
    )
    position = await session.scalar(
        select(Position)
        .where(
            context.where(Position.project_id, unassigned=True),
            owner,
            at_time(Position, when),
            visible(Position),
        )
        .order_by(device_fix().desc(), Position.id)
        .limit(1)
    )
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No position at that time")
    rows = (
        await session.execute(
            select(
                Measurement.metric_key,
                effective_value_num(),
                Measurement.value_bool,
                Measurement.value_text,
                Measurement.value_json,
            )
            .where(
                Measurement.device_id == position.device_id,
                at_time(Measurement, when),
                visible(Measurement),
            )
            .order_by(Measurement.metric_key, Measurement.id)
        )
    ).all()
    metrics = {
        m.key: m
        for m in (
            await session.scalars(select(Metric).where(Metric.key.in_({r[0] for r in rows})))
        ).all()
    }
    seen: set[str] = set()
    measurements: list[PointMeasurement] = []
    for key, number, boolean, text_value, json_value in rows:
        if key in seen:
            continue
        seen.add(key)
        metric = metrics.get(key)
        value: float | bool | str | dict[str, Any] | None
        if number is not None:
            value = number
        elif boolean is not None:
            value = boolean
        elif text_value is not None:
            value = text_value
        else:
            value = json_value
        measurements.append(
            PointMeasurement(
                metric_key=key,
                label=metric.label if metric else key,
                unit=metric.unit if metric else None,
                value=value,
            )
        )
    device_name = await session.scalar(select(Device.name).where(Device.id == position.device_id))
    entity_name = (
        await session.scalar(select(Entity.name).where(Entity.id == position.entity_id))
        if position.entity_id
        else None
    )
    return PointRead(
        position=position_read(position),
        device_name=device_name,
        entity_name=entity_name,
        measurements=measurements,
    )


class NetworkLocationsResponse(BaseModel):
    hours: int
    total: int = Field(description="Network locations in the window and view")
    capped: bool = Field(description="True when more exist than were returned")
    features: list[dict[str, Any]]


MAX_NETWORK_LOCATIONS = 2000
MAX_NETWORK_HOURS = 24 * 90


@router.get("/map/network-locations", response_model=NetworkLocationsResponse)
async def network_locations(
    bbox: str | None = Query(None, description="west,south,east,north in WGS84"),
    hours: int = Query(168, ge=1, le=MAX_NETWORK_HOURS),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> NetworkLocationsResponse:
    """Where the networks placed the scope's devices (decisions D162 and D163): the positions
    of record type `network` (Iridium estimates the network stood by, ThingPark geolocation,
    solved locations) in the window and view, newest first, with their radius. Provenance for
    the map's "Network locations" layer, never a device's own fix."""
    until = utc_now()
    since = until - timedelta(hours=hours)
    west, south, east, north = _bbox(bbox) or (-180.0, -90.0, 180.0, 90.0)
    statement = (
        select(
            Position.id,
            effective_time(Position).label("time"),
            func.ST_X(effective_geom()).label("lon"),
            func.ST_Y(effective_geom()).label("lat"),
            Position.accuracy_m,
            Position.attributes,
            Position.device_id,
            Position.entity_id,
            Position.source_event_id,
            Device.name.label("device_name"),
            Entity.name.label("entity_name"),
        )
        .join(Device, Device.id == Position.device_id)
        .outerjoin(Entity, Entity.id == Position.entity_id)
        .where(
            context.where(Position.project_id, unassigned=True),
            Position.record_type == NETWORK_RECORD_TYPE,
            in_window(Position, since, until),
            visible(Position),
            func.ST_Intersects(
                effective_geom(), func.ST_MakeEnvelope(west, south, east, north, 4326)
            ),
        )
        .order_by(effective_time(Position).desc())
        .limit(MAX_NETWORK_LOCATIONS + 1)
    )
    rows = (await session.execute(statement)).all()
    capped = len(rows) > MAX_NETWORK_LOCATIONS
    features = [
        {
            "type": "Feature",
            "id": row.id,
            "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
            "properties": {
                "position_id": row.id,
                "time": row.time.isoformat(),
                "accuracy_m": row.accuracy_m,
                "method": (row.attributes or {}).get("method"),
                "device_id": str(row.device_id),
                "device_name": row.device_name,
                "entity_id": str(row.entity_id) if row.entity_id else None,
                "entity_name": row.entity_name,
                "source_event_id": row.source_event_id,
            },
        }
        for row in rows[:MAX_NETWORK_LOCATIONS]
    ]
    return NetworkLocationsResponse(
        hours=hours, total=len(features), capped=capped, features=features
    )


@router.get("/map/heat", response_model=HeatResponse)
async def heat_points(
    bbox: str | None = Query(None, description="west,south,east,north in WGS84"),
    hours: int = Query(24, ge=1, le=MAX_HEAT_HOURS),
    entity_id: list[uuid.UUID] | None = Query(None, description="Positions of these entities"),
    device_id: list[uuid.UUID] | None = Query(None, description="Positions of these devices"),
    limit: int = Query(MAX_HEAT_POINTS, ge=1, le=MAX_HEAT_POINTS),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> HeatResponse:
    """The positions behind the heatmap (decision D138): the newest `limit` in the viewport and
    the look-back window, of the given entities and devices, or of the whole scope when neither
    is given. Bare points; the client weighs and draws them. Effective times and coordinates,
    invalid rows left out (architecture 28). Bounded twice: the scan runs per device through the
    device and time index of the compressed chunks (a bounding-box scan over every chunk of the
    window decompresses them all), for at most `MAX_HEAT_DEVICES` devices, the most recently seen
    first, and stops at `limit` points; the answer says how many devices it read of how many."""
    if len(entity_id or []) > MAX_HEAT_IDS or len(device_id or []) > MAX_HEAT_IDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"At most {MAX_HEAT_IDS} entities and {MAX_HEAT_IDS} devices per request",
        )
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
        "limit": limit,
        "max_devices": MAX_HEAT_DEVICES,
    }
    # the devices that qualify: seen in the window and, in a project, assigned to it during the
    # window; narrowed to the ones asked for or the ones tracking the entities asked for (their
    # positions are then filtered on the entity as well)
    qualify = ["s.last_seen_at >= :since"]
    if context.project_id is not None:
        qualify.append(
            """s.device_id IN (
                SELECT a.device_id FROM device_project_assignments a
                WHERE a.project_id = :project_id AND a.validity && tstzrange(:since, :until))"""
        )
    owner_filter = ""
    if entity_id or device_id:
        owner = []
        if entity_id:
            params["entity_ids"] = list(entity_id)
            owner.append("p.entity_id = ANY(CAST(:entity_ids AS uuid[]))")
        if device_id:
            params["device_ids"] = list(device_id)
            owner.append("p.device_id = ANY(CAST(:device_ids AS uuid[]))")
        owner_filter = " AND (" + " OR ".join(owner) + ")"
        params["all_device_ids"] = list(device_id or [])
        params["all_entity_ids"] = list(entity_id or [])
        qualify.append(
            """(s.device_id = ANY(CAST(:all_device_ids AS uuid[]))
                OR s.device_id IN (
                    SELECT a.device_id FROM device_entity_assignments a
                    WHERE a.entity_id = ANY(CAST(:all_entity_ids AS uuid[]))
                      AND a.validity && tstzrange(:since, :until)))"""
        )
    qualifying = (
        "SELECT s.device_id, s.last_seen_at FROM device_current_state s WHERE "
        + " AND ".join(qualify)
    )
    devices_total = int(
        await session.scalar(text(f"SELECT count(*) FROM ({qualifying}) q"), params) or 0
    )
    devices_scanned = min(devices_total, MAX_HEAT_DEVICES)
    project_filter = "AND p.project_id = :project_id" if context.project_id is not None else ""
    rows = (
        await session.execute(
            text(
                f"""
                WITH d AS ({qualifying} ORDER BY s.last_seen_at DESC LIMIT :max_devices)
                SELECT ST_AsGeoJSON(q.geom) FROM d
                JOIN LATERAL (
                    SELECT COALESCE(p.curated_geom, p.geom) AS geom,
                           COALESCE(p.curated_time, p.time) AS t
                    FROM positions p
                    WHERE p.device_id = d.device_id AND p.valid AND p.record_type <> 'network'
                      {project_filter} {owner_filter}
                      AND ((p.curated_time IS NULL AND p.time >= :since AND p.time < :until)
                           OR (p.curated_time IS NOT NULL AND p.curated_time >= :since
                               AND p.curated_time < :until))
                      AND ST_Intersects(COALESCE(p.curated_geom, p.geom),
                                        ST_MakeEnvelope(:west, :south, :east, :north, 4326))
                    ORDER BY t DESC LIMIT :limit
                ) q ON true
                ORDER BY q.t DESC LIMIT :limit"""
            ),
            params,
        )
    ).all()
    import json

    return HeatResponse(
        hours=hours,
        returned=len(rows),
        capped=len(rows) >= limit,
        devices_scanned=devices_scanned,
        devices_total=devices_total,
        features=[
            {"type": "Feature", "geometry": json.loads(row[0]), "properties": {}} for row in rows
        ],
    )
