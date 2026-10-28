"""The field bundle (phase 43, decision D331): what Smart Parks Protect Go, the app for the
place without a connection, downloads from a project before leaving, so a card reads offline
with the same code and the same credentials the server would use. One project per call, the
caller's visibility applied, the keys only for a caller who may set them (the rule of
`GET /devices/{id}/lp0-credentials`), the download in the audit log."""

import hashlib
import json
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.deps import ProjectContext, require_permission
from protect_api.routers.offload import (
    STATION_TYPE_KEY,
    TRACKERS_WINDOW,
    _current_entities,
    _project_device_ids,
    served_from_elsewhere,
)
from protect_api.schemas.field_bundle import (
    FieldArea,
    FieldBundleRead,
    FieldBundleRevision,
    FieldDevice,
    FieldEntity,
    FieldLp0,
    FieldMapRead,
    FieldMapRequest,
    FieldMetric,
    FieldOtherTracker,
    FieldProject,
    FieldStation,
)
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import get_session
from shared.domain.lp0 import credentials_for, device_eui, lp0_source
from shared.enums import MapExtractStatus
from shared.maps.extract import Bbox, covers, queue_map_extract, regions_of, row_regions
from shared.models import (
    Device,
    DeviceCurrentState,
    DeviceLp0Credentials,
    DeviceType,
    Entity,
    EntityCurrentState,
    EntityType,
    Feature,
    Gateway,
    MapExtract,
    Metric,
)
from shared.permissions import Permission
from shared.storage import stream_object
from shared.timeutil import utc_now
from shared.version import __version__

router = APIRouter(tags=["offload"])

#: Places of one kind read for the regions; a project with more is cut for the first of them.
MAX_PLACES = 5000


def _merge(boxes: list[FieldArea | None]) -> FieldArea | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return FieldArea(
        west=min(b.west for b in present),
        south=min(b.south for b in present),
        east=max(b.east for b in present),
        north=max(b.north for b in present),
    )


def _geojson(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    value = json.loads(text)
    return value if isinstance(value, dict) else None


async def _areas(
    session: AsyncSession, project_id: uuid.UUID, device_ids: list[uuid.UUID]
) -> list[FieldArea]:
    """The project's places as regions (decision D365): the boxes of its features, its
    entities' and devices' places set by hand, and the current positions of its devices and of
    the entities they track, grouped where they lie within `MAP_EXTRACT_REGION_GAP_KM` of one
    another; the largest region first. A station in the Netherlands and the tracker it served
    in Namibia are two regions, not one box over the gap."""
    boxes: list[Bbox] = []

    def envelope(column: Any) -> tuple[Any, Any, Any, Any]:
        geometry = cast(column, Geometry)
        return (
            func.ST_XMin(geometry),
            func.ST_YMin(geometry),
            func.ST_XMax(geometry),
            func.ST_YMax(geometry),
        )

    statements = [
        select(*envelope(Feature.geom))
        .where(Feature.project_id == project_id, Feature.geom.is_not(None))
        .limit(MAX_PLACES),
        select(*envelope(Entity.geom))
        .where(Entity.project_id == project_id, Entity.geom.is_not(None))
        .limit(MAX_PLACES),
    ]
    if device_ids:
        statements += [
            select(*envelope(Device.static_geom))
            .where(Device.id.in_(device_ids), Device.static_geom.is_not(None))
            .limit(MAX_PLACES),
            select(*envelope(DeviceCurrentState.latest_position))
            .where(
                DeviceCurrentState.device_id.in_(device_ids),
                DeviceCurrentState.latest_position.is_not(None),
            )
            .limit(MAX_PLACES),
            select(*envelope(EntityCurrentState.latest_position))
            .where(
                EntityCurrentState.project_id == project_id,
                EntityCurrentState.device_id.in_(device_ids),
                EntityCurrentState.latest_position.is_not(None),
            )
            .limit(MAX_PLACES),
        ]
    for statement in statements:
        for west, south, east, north in (await session.execute(statement)).all():
            if None in (west, south, east, north):
                continue
            boxes.append(Bbox(float(west), float(south), float(east), float(north)))
    regions = regions_of(boxes, get_settings().map_extract_region_gap_km)
    return [FieldArea(west=r.west, south=r.south, east=r.east, north=r.north) for r in regions]


def _boxes(areas: list[FieldArea]) -> list[Bbox]:
    return [Bbox(a.west, a.south, a.east, a.north) for a in areas]


async def _build_bundle(
    session: AsyncSession, context: ProjectContext
) -> tuple[FieldBundleRead, dict[str, int]]:
    """The project for the field (decision D331): devices with the entity each tracks now and
    their DevEUI, the entities, the offload stations with EUI and place, the area, and each
    tracker's LP0 address with its keys when the caller may set keys in this project. Returns
    the bundle, its revision set, and the figures the audit names."""
    reveal = context.is_server_admin or Permission.DEVICES_CONTROL in context.permissions
    device_ids = await _project_device_ids(session, context)
    rows = (
        await session.execute(
            select(Device, DeviceType)
            .join(DeviceType, DeviceType.id == Device.device_type_id)
            .where(Device.id.in_(device_ids))
            .order_by(Device.name)
        )
    ).all()
    entities = await _current_entities(session, device_ids)
    credentials = {
        row.device_id: row
        for row in (
            await session.scalars(
                select(DeviceLp0Credentials).where(DeviceLp0Credentials.device_id.in_(device_ids))
            )
        ).all()
    }
    source = await lp0_source(session)
    gateways = {
        g.device_id: g
        for g in (
            await session.scalars(
                select(Gateway).where(
                    Gateway.data_source_id == source.id, Gateway.device_id.in_(device_ids)
                )
            )
        ).all()
        if g.device_id is not None
    }
    station_ids = set(gateways) | {
        device_id for device_id, (_, _, key, _) in entities.items() if key == STATION_TYPE_KEY
    }

    devices: list[FieldDevice] = []
    stations: list[FieldStation] = []
    keys_sent = 0
    for device, device_type in rows:
        entity = entities.get(device.id)
        lp0: FieldLp0 | None = None
        row = credentials.get(device.id)
        if row is not None:
            lp0 = FieldLp0(
                dev_addr=row.dev_addr, keys_set=True, set_at=row.set_at, source=row.source
            )
            if reveal:
                keys = await credentials_for(session, device.id)
                if keys is not None:
                    lp0.app_s_key = keys.app_s_key.hex().upper()
                    lp0.nwk_s_key = keys.nwk_s_key.hex().upper()
                    keys_sent += 1
        eui = await device_eui(session, device)
        devices.append(
            FieldDevice(
                id=device.id,
                name=device.name,
                serial_number=device.serial_number,
                dev_eui=eui,
                device_type_key=device_type.key,
                device_type_label=device_type.label,
                driver_key=device_type.driver_key,
                status=device.status,
                firmware_version=device.firmware_version,
                entity_id=entity[0] if entity else None,
                entity_name=entity[1] if entity else None,
                is_station=device.id in station_ids,
                lp0=lp0,
            )
        )
        if device.id in station_ids:
            gateway = gateways.get(device.id)
            station_eui = eui or (gateway.external_id.upper() if gateway else None)
            if station_eui is None:
                continue  # a station without an EUI cannot be matched to a card's files
            place = await session.scalar(
                select(func.ST_AsGeoJSON(Device.static_geom)).where(Device.id == device.id)
            )
            if place is None and entity is not None:
                place = await session.scalar(
                    select(func.ST_AsGeoJSON(Entity.geom)).where(Entity.id == entity[0])
                )
            stations.append(
                FieldStation(
                    device_id=device.id,
                    device_name=device.name,
                    station_eui=station_eui,
                    entity_id=entity[0] if entity else None,
                    entity_name=entity[1] if entity else None,
                    geometry=_geojson(place),
                )
            )

    entity_ids = [entity_id for entity_id, _, _, _ in entities.values()]
    entity_rows = (
        (
            await session.execute(
                select(Entity, EntityType.key, EntityType.label, func.ST_AsGeoJSON(Entity.geom))
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(Entity.id.in_(entity_ids))
                .order_by(Entity.name)
            )
        ).all()
        if entity_ids
        else []
    )

    map_row = await session.get(MapExtract, context.project.id)
    areas = await _areas(session, context.project.id, device_ids)
    # the metric registry is shared by every project and small; the app names and units the
    # values it decodes with it (decision D334)
    metric_rows = (await session.scalars(select(Metric).order_by(Metric.key))).all()
    # the trackers of other projects the stations served (decision D348), so the app names a
    # card's frames of them rather than offering to add a device Protect has
    now = utc_now()
    elsewhere = await served_from_elsewhere(
        session,
        source.id,
        [g.external_id for g in gateways.values()],
        set(device_ids),
        now - TRACKERS_WINDOW,
        now,
    )
    bundle = FieldBundleRead(
        generated_at=now,
        protect_version=__version__,
        protect_commit=os.environ.get("GIT_COMMIT", "unknown"),
        server_url=get_settings().public_url,
        project=FieldProject(
            id=context.project.id,
            name=context.project.name,
            slug=context.project.slug,
            timezone=context.project.timezone,
        ),
        area=_merge(list(areas)),
        areas=areas,
        map=_map_read(map_row, areas) if map_row else None,
        credentials_included=reveal,
        devices=devices,
        entities=[
            FieldEntity(
                id=entity.id,
                name=entity.name,
                entity_type_key=key,
                entity_type_label=label,
                icon_key=entity.icon_key,
                geometry=_geojson(geometry),
            )
            for entity, key, label, geometry in entity_rows
        ],
        stations=stations,
        other_trackers=[
            FieldOtherTracker(
                dev_addr=served.dev_addr,
                device_id=served.device.id,
                device_name=served.device.name,
                project_name=served.project_name,
            )
            for served in elsewhere
            if served.dev_addr
        ],
        metrics=[
            FieldMetric(
                key=m.key,
                label=m.label,
                unit=m.unit,
                value_type=m.value_type,
                category=m.category,
                description=m.description,
            )
            for m in metric_rows
        ],
    )
    bundle.revision = _revision(bundle)
    return bundle, {"devices": len(devices), "stations": len(stations), "keys": keys_sent}


def _revision(bundle: FieldBundleRead) -> str:
    """A fingerprint of what the bundle carries, the same until the project changes: the
    generation time and the server's build are left out, so two reads of an unchanged project
    agree (decision D344)."""
    content = bundle.model_dump_json(
        exclude={"generated_at", "protect_commit", "protect_version", "revision"}
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@router.get("/projects/{project_id}/field-bundle", response_model=FieldBundleRead)
async def field_bundle(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> FieldBundleRead:
    """The project for the field (decision D331). Protect Go reads a card with this offline and
    uploads the card's files, never what it decoded. The download is audited."""
    bundle, figures = await _build_bundle(session, context)
    await record_audit(
        session,
        user=context.user,
        action="project.field_bundle_downloaded",
        object_type="project",
        object_id=str(context.project.id),
        project_id=context.project.id,
        details=figures,
    )
    await session.commit()
    return bundle


@router.get("/projects/{project_id}/field-bundle/revision", response_model=FieldBundleRevision)
async def field_bundle_revision(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> FieldBundleRevision:
    """The bundle's fingerprint alone (decision D344): Protect Go asks for it now and then and
    loads the project again by itself when it moved, so a station or a tracker added here is
    on the laptop without a hand. Not audited: nothing leaves but sixteen hex digits."""
    bundle, _figures = await _build_bundle(session, context)
    return FieldBundleRevision(revision=bundle.revision, checked_at=utc_now())


def _map_read(row: MapExtract, areas: list[FieldArea]) -> FieldMapRead:
    regions = row_regions(row)
    return FieldMapRead(
        status=row.status,
        west=row.west,
        south=row.south,
        east=row.east,
        north=row.north,
        regions=[
            FieldArea(west=r.west, south=r.south, east=r.east, north=r.north) for r in regions
        ],
        covers_areas=covers(regions, _boxes(areas)),
        max_zoom=row.max_zoom,
        build=row.build,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        requested_at=row.requested_at,
        ready_at=row.ready_at,
        error=row.error,
    )


@router.post(
    "/projects/{project_id}/field-bundle/map",
    response_model=FieldMapRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_field_map(
    body: FieldMapRequest,
    context: ProjectContext = Depends(require_permission(Permission.EXPORTS_CREATE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> FieldMapRead:
    """Ask for the project's offline map (phase 43 P3): the export worker cuts the project's
    regions, each with a margin, from the newest Protomaps planet build into one file. A file
    made for a member, so the permission is the exports' (`exports:create`: analysts and
    admins); every member downloads it. One job per project at a time; a map younger than a
    month whose regions cover every area is kept unless `force`. The regions are the project's
    features, entity and device places and current positions grouped by distance (decision
    D365), so a project with none yet has no map to cut."""
    device_ids = await _project_device_ids(session, context)
    areas = await _areas(session, context.project.id, device_ids)
    if not areas:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The project has no area yet: place an offload station, an entity or a feature first",
        )
    row, queued = await queue_map_extract(
        session,
        bus,
        context.project.id,
        _boxes(areas),
        requested_by=context.user.id,
        force=body.force,
    )
    if queued:
        await record_audit(
            session,
            user=context.user,
            action="project.field_map_requested",
            object_type="project",
            object_id=str(context.project.id),
            project_id=context.project.id,
            details={"max_zoom": row.max_zoom, "force": body.force, "regions": len(row.regions)},
        )
    await session.commit()
    return _map_read(row, areas)


@router.get(
    "/projects/{project_id}/field-bundle/map",
    responses={
        200: {"content": {"application/vnd.pmtiles": {}}, "description": "The map file"},
        202: {"model": FieldMapRead, "description": "Being made; the state"},
    },
)
async def download_field_map(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The project's offline map as a PMTiles file, streamed from MinIO, once it is ready;
    while it is being made, its state with 202; 404 when none was asked for; 409 with the
    reason when the last attempt failed."""
    row = await session.get(MapExtract, context.project.id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No offline map yet; ask for one with POST on this path"
        )
    if row.status == MapExtractStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The last map failed: {row.error}")
    if row.status != MapExtractStatus.READY or row.object_key is None:
        areas = await _areas(
            session, context.project.id, await _project_device_ids(session, context)
        )
        return JSONResponse(
            _map_read(row, areas).model_dump(mode="json"), status_code=status.HTTP_202_ACCEPTED
        )
    return StreamingResponse(
        stream_object(get_settings().minio_bucket_map_extracts, row.object_key),
        media_type="application/vnd.pmtiles",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{context.project.slug}-{row.build}.pmtiles"'
            ),
            "Content-Length": str(row.size_bytes or ""),
            "X-Content-SHA256": row.sha256 or "",
            "X-Map-Build": row.build or "",
        },
    )
