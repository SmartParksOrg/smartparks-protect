"""Entities, features and device-to-entity assignments inside a project."""

import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.attribution import hold_while_attributing, job_read, queue_job
from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import (
    apply_patch,
    flush_or_409,
    geojson_to_geom,
    geom_to_geojson,
    get_or_404,
    range_bounds,
)
from protect_api.deps import (
    ProjectContext,
    ScopeContext,
    require_permission,
    require_scope_permission,
)
from protect_api.device_reads import with_state
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.pictures import drop_picture, picture_response, store_picture
from protect_api.schemas.domain import (
    AssignmentChange,
    AssignmentEnd,
    AssignmentStart,
    CombinedArea,
    CombineFeaturesRequest,
    EntityAssignmentCreate,
    EntityAssignmentExtended,
    EntityAssignmentRead,
    EntityBulkMove,
    EntityBulkMoveResult,
    EntityCreate,
    EntityFenceRead,
    EntityRead,
    EntityTracking,
    EntityUpdate,
    FeatureCreate,
    FeatureRead,
    FeatureUpdate,
    FenceMonitorPlace,
    FenceMonitorRead,
    FenceMonitorUpdate,
    FenceStatusRead,
    ProposeAreaRequest,
    ProposedArea,
    ProposedAreas,
    SearchAreasRequest,
    TrackingDevice,
    UnionAreasRequest,
)
from protect_api.visibility import group_and_subgroups
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.curation.apply import recompute_current_state
from shared.database import get_session
from shared.domain.areas import (
    ATTRIBUTION,
    MAX_READ_KM2,
    box_around,
    box_of,
    combine_areas,
    name_query,
    overpass_query,
    propose,
    search_areas,
    search_box,
)
from shared.domain.assignments import resolve_attribution
from shared.domain.attribution import QueueResult, publish_job
from shared.domain.fence import (
    MonitorReading,
    Thresholds,
    line_length_m,
    line_level,
    monitor_level,
    recompute_fence,
    sections_of,
    snap_to_line,
)
from shared.domain.health import LEVELS
from shared.domain.static_place import place_device, place_entity_of
from shared.enums import FeatureType
from shared.models import (
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    Entity,
    EntityCurrentState,
    EntityType,
    Feature,
    FenceMonitor,
    FenceStatus,
    Group,
)
from shared.overpass import fetch_overpass
from shared.permissions import Permission, permissions_for
from shared.pictures import PICTURE_LANDSCAPE
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(prefix="/projects/{project_id}", tags=["entities"])


def entity_read(entity: Entity) -> EntityRead:
    data = EntityRead.model_validate(entity)
    data.geometry = geom_to_geojson(entity.geom)
    return data


async def with_tracking(session: AsyncSession, entities: Sequence[Entity]) -> list[EntityRead]:
    """Entity reads with what their devices say today (decision D286): the devices assigned now
    with their health, judged as the devices list judges it, the worst of those levels, the
    newest record and the position the current state holds, and the open alerts. Read from the
    assignments rather than from the positions, so a device that sends no fix still counts."""
    reads = [entity_read(e) for e in entities]
    if not reads:
        return reads
    ids = [e.id for e in entities]
    entity_of = {
        device_id: entity_id
        for entity_id, device_id in (
            await session.execute(
                select(DeviceEntityAssignment.entity_id, DeviceEntityAssignment.device_id).where(
                    DeviceEntityAssignment.entity_id.in_(ids),
                    DeviceEntityAssignment.validity.op("@>")(utc_now()),
                )
            )
        ).all()
    }
    devices = (
        list(
            (
                await session.scalars(
                    select(Device).where(Device.id.in_(entity_of)).order_by(Device.name)
                )
            ).all()
        )
        if entity_of
        else []
    )
    received = (
        {
            device_id: updated_at
            for device_id, updated_at in (
                await session.execute(
                    select(DeviceCurrentState.device_id, DeviceCurrentState.updated_at).where(
                        DeviceCurrentState.device_id.in_(list(entity_of))
                    )
                )
            ).all()
        }
        if entity_of
        else {}
    )
    tracking: dict[uuid.UUID, list[TrackingDevice]] = {}
    for device in await with_state(session, devices):
        tracking.setdefault(entity_of[device.id], []).append(
            TrackingDevice(
                id=device.id,
                name=device.name,
                last_seen_at=device.last_seen_at,
                data_received_at=received.get(device.id),
                health=device.health,
            )
        )
    states = {
        s.entity_id: s
        for s in (
            await session.scalars(
                select(EntityCurrentState).where(EntityCurrentState.entity_id.in_(ids))
            )
        ).all()
    }
    for read in reads:
        tracked = tracking.get(read.id, [])
        state = states.get(read.id)
        levels = [
            LEVELS.index(d.health.level) for d in tracked if d.health and d.health.level in LEVELS
        ]
        seen = [d.last_seen_at for d in tracked if d.last_seen_at]
        if state is not None and state.last_seen_at:
            seen.append(state.last_seen_at)
        arrived = [d.data_received_at for d in tracked if d.data_received_at]
        if state is not None:
            arrived.append(state.updated_at)
        read.tracking = EntityTracking(
            devices=tracked,
            level=LEVELS[max(levels)] if levels else None,
            last_seen_at=max(seen) if seen else None,
            data_received_at=max(arrived) if arrived else None,
            position_time=state.latest_position_time if state else None,
            position_kind=state.latest_position_kind if state else None,
            active_alert_count=state.active_alert_count if state else 0,
        )
    return reads


def feature_read(feature: Feature, fence: FenceStatus | None = None) -> FeatureRead:
    data = FeatureRead.model_validate(feature)
    data.geometry = geom_to_geojson(feature.geom)
    if feature.feature_type == FeatureType.FENCE:
        reading = _fence_now(feature, fence, utc_now())
        data.fence_level = reading["level"]
        data.fence_sections = reading["sections"]
    return data


def _fence_now(feature: Feature, status: FenceStatus | None, now: datetime) -> dict[str, Any]:
    """A fence line's reading as of now: the stored monitors re-judged against the clock, so a
    line whose monitors fell silent reads unknown although no measurement arrived to say so
    (decision D264). The sections are cut again from the stored places."""
    thresholds = Thresholds.of(feature.attributes)
    coordinates = geom_to_geojson(feature.geom) or {}
    length = (
        line_length_m([list(c[:2]) for c in coordinates["coordinates"]])
        if coordinates.get("type") == "LineString"
        else 0.0
    )
    monitors: list[MonitorReading] = []
    for m in (status.monitors if status else None) or []:
        measured_at = datetime.fromisoformat(m["measured_at"]) if m.get("measured_at") else None
        reading = MonitorReading(
            entity_id=uuid.UUID(m["entity_id"]),
            name=str(m.get("name") or ""),
            position_m=m.get("position_m"),
            device_id=uuid.UUID(m["device_id"]) if m.get("device_id") else None,
            voltage_v=m.get("voltage_v"),
            pulses=m.get("pulses"),
            measured_at=measured_at,
            failed=bool(m.get("failed")),
        )
        reading.level = monitor_level(
            reading.voltage_v, reading.pulses, reading.failed, measured_at, now, thresholds
        )
        monitors.append(reading)
    sections = sections_of(length, monitors)
    return {
        "level": line_level(sections),
        "length_m": round(length, 1),
        "thresholds": {
            "ok_v": thresholds.ok_v,
            "down_v": thresholds.down_v,
            "interval_s": thresholds.interval_s,
        },
        "sections": [s.as_dict() for s in sections],
        "monitors": [m.as_dict() for m in monitors],
    }


async def _fence_statuses(
    session: AsyncSession, features: list[Feature]
) -> dict[uuid.UUID, FenceStatus]:
    ids = [f.id for f in features if f.feature_type == FeatureType.FENCE]
    if not ids:
        return {}
    rows = (await session.scalars(select(FenceStatus).where(FenceStatus.feature_id.in_(ids)))).all()
    return {row.feature_id: row for row in rows}


def assignment_read(
    assignment: DeviceEntityAssignment,
    *,
    device_name: str | None = None,
    entity_name: str | None = None,
) -> EntityAssignmentRead:
    valid_from, valid_to = range_bounds(assignment.validity)
    return EntityAssignmentRead(
        id=assignment.id,
        device_id=assignment.device_id,
        entity_id=assignment.entity_id,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=assignment.reason,
        created_at=assignment.created_at,
        device_name=device_name,
        entity_name=entity_name,
    )


async def check_group(
    session: AsyncSession, context: ProjectContext, group_id: uuid.UUID | None
) -> None:
    if group_id is None:
        return
    group = await get_or_404(session, Group, group_id, "Group")
    if group.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")


# Entities


@router.get("/entities", response_model=PageResponse[EntityRead])
async def list_entities(
    page: Page = Depends(page),
    entity_type_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    q: str | None = Query(None, max_length=200, description="Name contains, case-insensitive"),
    group_id: uuid.UUID | None = Query(
        None, description="In this group or one of its subgroups (decision D98)"
    ),
    ungrouped: bool = Query(False, description="Only entities in no group"),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EntityRead]:
    statement = select(Entity).where(
        context.where(Entity.project_id), context.visibility.entities(Entity.id)
    )
    if entity_type_id is not None:
        statement = statement.where(Entity.entity_type_id == entity_type_id)
    if group_id is not None:
        statement = statement.where(Entity.group_id.in_(group_and_subgroups(group_id)))
    if ungrouped:
        statement = statement.where(Entity.group_id.is_(None))
    if status_filter is not None:
        statement = statement.where(Entity.status == status_filter)
    if q:
        statement = statement.where(Entity.name.ilike(f"%{q}%"))
    rows, next_cursor = await paginate(session, Entity.id, statement, page)
    return PageResponse(items=await with_tracking(session, rows), next_cursor=next_cursor)


@router.post("/entities", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    body: EntityCreate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    entity = await _new_entity(session, context, body)
    await session.commit()
    return entity_read(entity)


async def _new_entity(session: AsyncSession, context: ProjectContext, body: EntityCreate) -> Entity:
    """The entity row with its audit entry, flushed and not committed: `create_entity` and the
    assignment that makes an entity on the spot (decision D170) share it."""
    await get_or_404(session, EntityType, body.entity_type_id, "Entity type")
    await check_group(session, context, body.group_id)
    entity = Entity(
        project_id=context.project.id,
        geom=geojson_to_geom(body.geometry.as_dict() if body.geometry else None),
        **body.model_dump(exclude={"geometry"}),
    )
    session.add(entity)
    await flush_or_409(session, "Entity")
    await record_audit(
        session,
        user=context.user,
        action="entity.created",
        object_type="entity",
        object_id=str(entity.id),
        project_id=context.project.id,
        details={"name": entity.name},
    )
    return entity


@router.post("/entities/bulk-move", response_model=EntityBulkMoveResult)
async def bulk_move_entities(
    body: EntityBulkMove,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityBulkMoveResult:
    """Put the listed entities of this project into `group_id` (or into no group). Ids of
    other projects are refused as a whole, so nothing moves by accident."""
    await check_group(session, context, body.group_id)
    wanted = set(body.entity_ids)
    entities = (
        await session.scalars(
            select(Entity).where(Entity.id.in_(wanted), Entity.project_id == context.project.id)
        )
    ).all()
    if len(entities) != len(wanted):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Some entities are not in this project")
    for entity in entities:
        entity.group_id = body.group_id
    await flush_or_409(session, "Entity")
    await record_audit(
        session,
        user=context.user,
        action="entity.moved",
        object_type="entity_group",
        object_id=str(body.group_id) if body.group_id else "none",
        project_id=context.project.id,
        details={"count": len(entities), "entity_ids": [str(e.id) for e in entities][:50]},
    )
    await session.commit()
    return EntityBulkMoveResult(moved=len(entities), group_id=body.group_id)


async def _project_entity(
    session: AsyncSession, context: ProjectContext, entity_id: uuid.UUID
) -> Entity:
    entity = await get_or_404(session, Entity, entity_id, "Entity")
    if entity.project_id != context.project.id or not context.visibility.entity_visible(entity.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    return entity


@router.get("/entities/{entity_id}", response_model=EntityRead)
async def get_entity(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    return entity_read(await _project_entity(session, context, entity_id))


@router.patch("/entities/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: uuid.UUID,
    body: EntityUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    entity = await _project_entity(session, context, entity_id)
    if "group_id" in body.model_fields_set:
        await check_group(session, context, body.group_id)
    changed = apply_patch(entity, body, exclude={"geometry"})
    if changed.keys() & {"location_source", "location_fallback_hours"}:
        # the setting decides which positions become current (decision D164): rebuild the
        # state now, since a device repeating its last estimate brings nothing new to apply it
        tracking = await session.scalar(
            select(DeviceEntityAssignment.device_id).where(
                DeviceEntityAssignment.entity_id == entity.id,
                DeviceEntityAssignment.validity.op("@>")(utc_now()),
            )
        )
        await recompute_current_state(session, tracking, {entity.id})
    if "geometry" in body.model_fields_set:
        entity.geom = geojson_to_geom(body.geometry.as_dict() if body.geometry else None)
        changed["geometry"] = body.geometry.as_dict() if body.geometry else None
    await flush_or_409(session, "Entity")
    await record_audit(
        session,
        user=context.user,
        action="entity.updated",
        object_type="entity",
        object_id=str(entity.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return entity_read(entity)


@router.get("/entities/{entity_id}/picture", response_class=Response)
async def get_entity_picture(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The entity's picture (decisions D110, D194), a 4:3 WebP landscape."""
    entity = await _project_entity(session, context, entity_id)
    return await picture_response(entity.picture_key, entity.picture_updated_at)


@router.put("/entities/{entity_id}/picture", response_model=EntityRead)
async def set_entity_picture(
    entity_id: uuid.UUID,
    file: UploadFile,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    """Set the picture from a JPEG, PNG or WebP; the server keeps a 4:3 landscape (D194)."""
    entity = await _project_entity(session, context, entity_id)
    entity.picture_key, entity.picture_updated_at = await store_picture(
        "entities", entity.id, file, PICTURE_LANDSCAPE
    )
    await record_audit(
        session,
        user=context.user,
        project_id=context.project.id,
        action="entity.picture_set",
        object_type="entity",
        object_id=str(entity.id),
        details={"name": entity.name},
    )
    await session.commit()
    await session.refresh(entity)
    return entity_read(entity)


@router.delete("/entities/{entity_id}/picture", response_model=EntityRead)
async def remove_entity_picture(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    entity = await _project_entity(session, context, entity_id)
    await drop_picture(entity.picture_key)
    entity.picture_key, entity.picture_updated_at = None, None
    await record_audit(
        session,
        user=context.user,
        project_id=context.project.id,
        action="entity.picture_removed",
        object_type="entity",
        object_id=str(entity.id),
        details={"name": entity.name},
    )
    await session.commit()
    await session.refresh(entity)
    return entity_read(entity)


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Entities with history should be archived, not deleted; deletion is for mistakes."""
    entity = await _project_entity(session, context, entity_id)
    await session.delete(entity)
    await flush_or_409(session, "Entity")
    await record_audit(
        session,
        user=context.user,
        action="entity.deleted",
        object_type="entity",
        object_id=str(entity.id),
        project_id=context.project.id,
        details={"name": entity.name},
    )
    await session.commit()


# Features


@router.get("/features", response_model=PageResponse[FeatureRead])
async def list_features(
    page: Page = Depends(page),
    feature_type: str | None = None,
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[FeatureRead]:
    statement = select(Feature).where(context.where(Feature.project_id))
    if feature_type is not None:
        statement = statement.where(Feature.feature_type == feature_type)
    rows, next_cursor = await paginate(session, Feature.id, statement, page)
    statuses = await _fence_statuses(session, list(rows))
    return PageResponse(
        items=[feature_read(r, statuses.get(r.id)) for r in rows], next_cursor=next_cursor
    )


@router.post("/features", response_model=FeatureRead, status_code=status.HTTP_201_CREATED)
async def create_feature(
    body: FeatureCreate,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    feature = Feature(
        project_id=context.project.id,
        geom=geojson_to_geom(body.geometry.as_dict()),
        **body.model_dump(exclude={"geometry"}),
    )
    session.add(feature)
    await flush_or_409(session, "Feature")
    await record_audit(
        session,
        user=context.user,
        action="feature.created",
        object_type="feature",
        object_id=str(feature.id),
        project_id=context.project.id,
        details={"name": feature.name},
    )
    await session.commit()
    return feature_read(feature)


@router.post("/features/propose", response_model=ProposedAreas)
async def propose_area(
    body: ProposeAreaRequest,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
) -> ProposedAreas:
    """The areas one read could mean (phase 33, decisions D270 and D277): the face of
    OpenStreetMap's roads, water, fences and railways that encloses the middle of the box (the
    ways people walk on do not cut it, decision D272), and every OpenStreetMap area that
    contains it, smallest first. The ground read is a box around a click or the box a person
    dragged, at most `MAX_READ_KM2`; a larger one is a 422 naming its size, since the public
    Overpass answers a read that big with a refusal. Read from the Overpass API named by
    `OVERPASS_URL`; nothing is stored. A 502 says OpenStreetMap did not answer."""
    read = (
        box_of(body.west, body.south, body.east, body.north)
        if body.west is not None
        and body.south is not None
        and body.east is not None
        and body.north is not None
        else box_around(body.lon or 0.0, body.lat or 0.0, body.radius_m)
    )
    if read.too_large:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"That box is {read.area_km2:.0f} km²; a read takes at most {MAX_READ_KM2:.0f} km²",
        )
    query = overpass_query(read)
    try:
        document = await fetch_overpass(get_settings().overpass_url, query)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, error.message) from error
    candidates = propose(document, read)
    return ProposedAreas(
        candidates=[ProposedArea(**asdict(candidate)) for candidate in candidates],
        attribution=ATTRIBUTION,
    )


@router.post("/features/union", response_model=CombinedArea)
async def union_areas(
    body: UnionAreasRequest,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> CombinedArea:
    """Several areas as one shape (phase 33, decision D274): four reserves beside each other
    are one zone to the people who patrol them. Takes the project's features, shapes that are
    not saved yet, or both, and answers their union without storing anything, so the shape can
    be seen and named before it is kept. Pieces that touch become one."""
    shapes = [geometry.as_dict() for geometry in body.geometries]
    if body.feature_ids:
        features = await _features_of(session, context, body.feature_ids)
        shapes += [g for g in (geom_to_geojson(f.geom) for f in features) if g]
    if len(shapes) < 2:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Two areas or more make a combined one"
        )
    combined = combine_areas(shapes)
    if combined is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "None of those is an area")
    return CombinedArea(geometry=combined.geometry, area_m2=combined.area_m2, parts=combined.parts)


@router.post("/features/combine", response_model=FeatureRead, status_code=status.HTTP_201_CREATED)
async def combine_features(
    body: CombineFeaturesRequest,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    """One feature out of several of the project's own (decision D274), in one go: the union is
    saved under a new name and the parts are kept unless `remove_parts` says otherwise. Both
    acts are in the audit log; a part that is still referred to keeps the whole thing from
    being saved rather than half of it."""
    features = await _features_of(session, context, body.feature_ids)
    combined = combine_areas([g for g in (geom_to_geojson(f.geom) for f in features) if g])
    if combined is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "None of those is an area")
    feature = Feature(
        project_id=context.project.id,
        feature_type=body.feature_type,
        name=body.name,
        geom=geojson_to_geom(combined.geometry),
        attributes={"combined_from": [str(part.id) for part in features]},
    )
    session.add(feature)
    await flush_or_409(session, "Feature")
    await record_audit(
        session,
        user=context.user,
        action="feature.created",
        object_type="feature",
        object_id=str(feature.id),
        project_id=context.project.id,
        details={"name": feature.name, "combined_from": [part.name for part in features]},
    )
    if body.remove_parts:
        for part in features:
            await record_audit(
                session,
                user=context.user,
                action="feature.deleted",
                object_type="feature",
                object_id=str(part.id),
                project_id=context.project.id,
                details={"name": part.name, "combined_into": feature.name},
            )
            await session.delete(part)
    await session.commit()
    return feature_read(feature)


@router.post("/features/search-areas", response_model=ProposedAreas)
async def search_areas_by_name(
    body: SearchAreasRequest,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
) -> ProposedAreas:
    """The areas of a name (phase 33, decision D273): somebody who knows what the area is
    called types it instead of finding the spot to click, and the OpenStreetMap areas whose
    name holds the text, inside the part of the map they are looking at, come back as the same
    candidates a click gives. A view wider than the widest search reads its middle and says so.
    Nothing is stored; a 502 says OpenStreetMap did not answer."""
    box = search_box(body.west, body.south, body.east, body.north)
    query = name_query(box, body.name.strip())
    try:
        document = await fetch_overpass(get_settings().overpass_url, query)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, error.message) from error
    candidates = search_areas(document, body.name.strip(), box)
    return ProposedAreas(
        candidates=[ProposedArea(**asdict(candidate)) for candidate in candidates],
        attribution=ATTRIBUTION,
        narrowed=box.narrowed,
    )


async def _project_feature(
    session: AsyncSession, context: ProjectContext, feature_id: uuid.UUID
) -> Feature:
    feature = await get_or_404(session, Feature, feature_id, "Feature")
    if feature.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found")
    return feature


async def _features_of(
    session: AsyncSession, context: ProjectContext, feature_ids: list[uuid.UUID]
) -> list[Feature]:
    """The project's features named by the ids, in the order they were asked for. An id that
    is not the project's is a 404, as it is for one feature (decision D274)."""
    rows = (
        await session.execute(
            select(Feature).where(
                Feature.project_id == context.project.id, Feature.id.in_(set(feature_ids))
            )
        )
    ).scalars()
    found = {feature.id: feature for feature in rows}
    missing = [str(i) for i in feature_ids if i not in found]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found")
    return [found[i] for i in dict.fromkeys(feature_ids)]


@router.get("/features/{feature_id}", response_model=FeatureRead)
async def get_feature(
    feature_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    feature = await _project_feature(session, context, feature_id)
    return feature_read(feature, await session.get(FenceStatus, feature.id))


@router.get("/features/{feature_id}/fence", response_model=FenceStatusRead)
async def get_fence_status(
    feature_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> FenceStatusRead:
    """A fence line's reading (phase 32): the level as of now, the sections along the line
    and what each monitor last reported. A line without monitors reads unknown and says so."""
    feature = await _project_feature(session, context, feature_id)
    if feature.feature_type != FeatureType.FENCE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a fence line")
    return await _fence_status_read(session, feature, utc_now())


async def _fence_status_read(
    session: AsyncSession, feature: Feature, now: datetime
) -> FenceStatusRead:
    status_row = await session.get(FenceStatus, feature.id)
    if status_row is None:
        # never computed: a line drawn before any monitor reported, or with none on it yet
        await recompute_fence(session, feature.id, now)
        await session.commit()
        status_row = await session.get(FenceStatus, feature.id)
    reading = _fence_now(feature, status_row, now)
    return FenceStatusRead(
        feature_id=feature.id,
        project_id=feature.project_id,
        name=feature.name,
        changed_at=status_row.changed_at if status_row else None,
        updated_at=status_row.updated_at if status_row else None,
        **reading,
    )


@router.get("/fence-monitors", response_model=list[FenceMonitorRead])
async def list_fence_monitors(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[FenceMonitorRead]:
    """Every Fence monitor entity of the project with its device today, the line it is on and
    where it stands: what the fence line's map drags from (phase 32)."""
    from sqlalchemy import func

    now = utc_now()
    rows = (
        await session.execute(
            select(
                Entity.id,
                Entity.name,
                Device.id,
                Device.name,
                Feature.id,
                Feature.name,
                func.ST_X(EntityCurrentState.latest_position),
                func.ST_Y(EntityCurrentState.latest_position),
            )
            .join(EntityType, EntityType.id == Entity.entity_type_id)
            .outerjoin(
                DeviceEntityAssignment,
                (DeviceEntityAssignment.entity_id == Entity.id)
                & DeviceEntityAssignment.validity.op("@>")(now),
            )
            .outerjoin(Device, Device.id == DeviceEntityAssignment.device_id)
            .outerjoin(FenceMonitor, FenceMonitor.entity_id == Entity.id)
            .outerjoin(Feature, Feature.id == FenceMonitor.feature_id)
            .outerjoin(EntityCurrentState, EntityCurrentState.entity_id == Entity.id)
            .where(Entity.project_id == context.project.id, EntityType.key == "fence_monitor")
            .order_by(Entity.name)
        )
    ).all()
    return [
        FenceMonitorRead(
            entity_id=row[0],
            name=row[1],
            device_id=row[2],
            device_name=row[3],
            feature_id=row[4],
            feature_name=row[5],
            longitude=float(row[6]) if row[6] is not None else None,
            latitude=float(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]


@router.put("/features/{feature_id}/monitors/{entity_id}", response_model=FenceStatusRead)
async def place_fence_monitor(
    feature_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: FenceMonitorPlace,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> FenceStatusRead:
    """A monitor dropped on the line (Tim, 2026-09-19): the point is moved onto the line, the
    monitor's device gets that as its fixed place — over any place it had, since a drop says
    the hardware moved — and the monitor is put on the line if it was not. A monitor without a
    device has nothing to place and is refused."""
    feature = await _project_feature(session, context, feature_id)
    if feature.feature_type != FeatureType.FENCE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a fence line")
    entity = await _project_entity(session, context, entity_id)
    now = utc_now()
    device_id = await session.scalar(
        select(DeviceEntityAssignment.device_id).where(
            DeviceEntityAssignment.entity_id == entity.id,
            DeviceEntityAssignment.validity.op("@>")(now),
        )
    )
    if device_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This monitor has no device; give it its FenceEdge first",
        )
    device = await get_or_404(session, Device, device_id, "Device")
    geometry = geom_to_geojson(feature.geom) or {}
    if geometry.get("type") != "LineString":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The fence line has no line")
    coordinates = [list(c[:2]) for c in geometry["coordinates"]]
    lon, lat, metres = snap_to_line(coordinates, body.longitude, body.latitude)
    placed = await place_device(session, device, lon, lat, now)
    link = await session.get(FenceMonitor, entity.id)
    previous = link.feature_id if link else None
    if link is None:
        session.add(FenceMonitor(entity_id=entity.id, feature_id=feature.id))
    else:
        link.feature_id = feature.id
    await session.flush()
    if previous is not None and previous != feature.id:
        await recompute_fence(session, previous, now)
    await recompute_fence(session, feature.id, now)
    await record_audit(
        session,
        user=context.user,
        action="entity.fence_placed",
        object_type="entity",
        object_id=str(entity.id),
        project_id=context.project.id,
        details={
            "feature_id": str(feature.id),
            "device_id": str(device.id),
            "longitude": lon,
            "latitude": lat,
            "along_m": round(metres, 1),
            "sightings_placed": placed,
        },
    )
    await session.commit()
    return await _fence_status_read(session, feature, utc_now())


@router.get("/entities/{entity_id}/fence", response_model=EntityFenceRead)
async def get_entity_fence(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> EntityFenceRead:
    """The fence line a monitor entity stands on, with the monitor's own reading."""
    entity = await _project_entity(session, context, entity_id)
    link = await session.get(FenceMonitor, entity.id)
    if link is None:
        return EntityFenceRead(feature_id=None, feature_name=None, level=None, monitor=None)
    feature = await session.get(Feature, link.feature_id)
    status_row = await session.get(FenceStatus, link.feature_id)
    reading = _fence_now(feature, status_row, utc_now()) if feature else None
    mine = next(
        (m for m in (reading["monitors"] if reading else []) if m["entity_id"] == str(entity.id)),
        None,
    )
    return EntityFenceRead(
        feature_id=link.feature_id,
        feature_name=feature.name if feature else None,
        level=reading["level"] if reading else None,
        monitor=mine,
    )


@router.put("/entities/{entity_id}/fence", response_model=EntityFenceRead)
async def set_entity_fence(
    entity_id: uuid.UUID,
    body: FenceMonitorUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityFenceRead:
    """Put a Fence monitor entity on a fence line, or take it off (decision D263). Both lines
    are recomputed, since a monitor leaving one changes what that one can say."""
    entity = await _project_entity(session, context, entity_id)
    link = await session.get(FenceMonitor, entity.id)
    previous = link.feature_id if link else None
    if body.feature_id is not None:
        feature = await _project_feature(session, context, body.feature_id)
        if feature.feature_type != FeatureType.FENCE:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a fence line")
        if link is None:
            session.add(FenceMonitor(entity_id=entity.id, feature_id=feature.id))
        else:
            link.feature_id = feature.id
    elif link is not None:
        await session.delete(link)
    await session.flush()
    now = utc_now()
    for touched in (previous, body.feature_id):
        if touched is not None:
            await recompute_fence(session, touched, now)
    await record_audit(
        session,
        user=context.user,
        action="entity.fence_set",
        object_type="entity",
        object_id=str(entity.id),
        project_id=context.project.id,
        details={"feature_id": str(body.feature_id) if body.feature_id else None},
    )
    await session.commit()
    return await get_entity_fence(entity_id, context, session)


@router.patch("/features/{feature_id}", response_model=FeatureRead)
async def update_feature(
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    feature = await _project_feature(session, context, feature_id)
    changed = apply_patch(feature, body, exclude={"geometry"})
    if body.geometry is not None:
        feature.geom = geojson_to_geom(body.geometry.as_dict())
        changed["geometry"] = body.geometry.as_dict()
    await flush_or_409(session, "Feature")
    if feature.feature_type == FeatureType.FENCE and (
        body.geometry is not None or body.attributes is not None
    ):
        # a moved line or new thresholds change where the monitors stand and what they say
        await recompute_fence(session, feature.id, utc_now())
    await record_audit(
        session,
        user=context.user,
        action="feature.updated",
        object_type="feature",
        object_id=str(feature.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return feature_read(feature, await session.get(FenceStatus, feature.id))


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature(
    feature_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.FEATURES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    feature = await _project_feature(session, context, feature_id)
    await session.delete(feature)
    await record_audit(
        session,
        user=context.user,
        action="feature.deleted",
        object_type="feature",
        object_id=str(feature.id),
        project_id=context.project.id,
        details={"name": feature.name},
    )
    await session.commit()


# Device to entity assignments


@router.get("/entity-assignments", response_model=PageResponse[EntityAssignmentRead])
async def list_entity_assignments(
    page: Page = Depends(page),
    entity_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EntityAssignmentRead]:
    """The assignments of this project's entities with the device's name,
    so an entity page can show its history without a device read per row (decision D106)."""
    statement = (
        select(DeviceEntityAssignment)
        .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
        .where(
            context.where(Entity.project_id),
            context.visibility.rows(
                DeviceEntityAssignment.entity_id, DeviceEntityAssignment.device_id
            ),
        )
    )
    if entity_id is not None:
        statement = statement.where(DeviceEntityAssignment.entity_id == entity_id)
    if device_id is not None:
        statement = statement.where(DeviceEntityAssignment.device_id == device_id)
    rows, next_cursor = await paginate(session, DeviceEntityAssignment.id, statement, page)
    names = {
        device_id: name
        for device_id, name in (
            await session.execute(
                select(Device.id, Device.name).where(Device.id.in_({r.device_id for r in rows}))
            )
        ).all()
    }
    return PageResponse(
        items=[assignment_read(r, device_name=names.get(r.device_id)) for r in rows],
        next_cursor=next_cursor,
    )


@router.post(
    "/entity-assignments", response_model=EntityAssignmentRead, status_code=status.HTTP_201_CREATED
)
async def create_entity_assignment(
    body: EntityAssignmentCreate,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> EntityAssignmentRead:
    """Assign a device to an entity of this project from `valid_from`: an existing entity, or
    a new one from `new_entity` (decision D170; the caller then needs `entities:write` too). The
    device must belong to the project at that moment. Overlapping assignments of the same device
    are rejected."""
    if body.new_entity is not None:
        allowed = permissions_for(context.role, server_admin=context.user.is_superuser)
        if Permission.ENTITIES_WRITE not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Creating an entity needs entities:write"
            )
        entity = await _new_entity(session, context, body.new_entity)
    else:
        entity = await _project_entity(session, context, body.entity_id)  # type: ignore[arg-type]
    await get_or_404(session, Device, body.device_id, "Device")
    await hold_while_attributing(session, body.device_id)
    attribution = await resolve_attribution(session, body.device_id, body.valid_from)
    if attribution.project_id != context.project.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Device is not assigned to this project at valid_from"
        )
    if body.valid_to is not None and body.valid_to <= body.valid_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    assignment = DeviceEntityAssignment(
        device_id=body.device_id,
        entity_id=entity.id,
        validity=Range(body.valid_from, body.valid_to, bounds="[)"),
        reason=body.reason,
        created_by_user_id=context.user.id,
    )
    session.add(assignment)
    await flush_or_409(session, "Entity assignment")
    # A device with a place set by hand carries it to its new entity at once (decision D261):
    # a scanner reports nothing, so no record will ever put that entity on the map.
    if body.valid_to is None:
        await place_entity_of(session, body.device_id, body.valid_from)
    # Records already decoded inside the range get the entity through a job (D103, D206).
    queued = await queue_job(
        session,
        device_id=body.device_id,
        start=body.valid_from,
        end=body.valid_to or utc_now(),
        reason="entity_assignment.created",
        user=context.user,
        project_id=context.project.id,
    )
    await record_audit(
        session,
        user=context.user,
        action="entity_assignment.created",
        object_type="device_entity_assignment",
        object_id=str(assignment.id),
        project_id=context.project.id,
        details={
            "device_id": str(body.device_id),
            "entity_id": str(entity.id),
            "valid_from": body.valid_from.isoformat(),
            "attribution_job_id": str(queued.job.id) if queued.job else None,
        },
    )
    await session.commit()
    if queued.created and queued.job is not None:
        await publish_job(bus, queued.job)
    read = assignment_read(assignment, entity_name=entity.name)
    read.attribution_job = job_read(queued.job)
    return read


@router.post(
    "/entity-assignments/{assignment_id}/extend-start", response_model=EntityAssignmentExtended
)
async def extend_entity_assignment_start(
    assignment_id: uuid.UUID,
    body: AssignmentStart,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> EntityAssignmentExtended:
    """Move the start of an entity assignment back and attribute the records in between
    (decision D103). The device must belong to this project at the new start: extend the
    project assignment first."""
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    await _project_entity(session, context, assignment.entity_id)
    await hold_while_attributing(session, assignment.device_id)
    old_from, valid_to = range_bounds(assignment.validity)
    if body.valid_from >= old_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_from must be before the current start"
        )
    attribution = await resolve_attribution(session, assignment.device_id, body.valid_from)
    if attribution.project_id != context.project.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Device is not assigned to this project at valid_from; extend the project "
            "assignment first",
        )
    assignment.validity = Range(body.valid_from, valid_to, bounds="[)")
    await flush_or_409(session, "Entity assignment")
    queued = await queue_job(
        session,
        device_id=assignment.device_id,
        start=body.valid_from,
        end=old_from,
        reason="entity_assignment.start_moved",
        user=context.user,
        project_id=context.project.id,
    )
    await record_audit(
        session,
        user=context.user,
        action="entity_assignment.start_moved",
        object_type="device_entity_assignment",
        object_id=str(assignment.id),
        project_id=context.project.id,
        details={
            "from": old_from.isoformat(),
            "to": body.valid_from.isoformat(),
            "attribution_job_id": str(queued.job.id) if queued.job else None,
        },
    )
    await session.commit()
    if queued.created and queued.job is not None:
        await publish_job(bus, queued.job)
    data = assignment_read(assignment).model_dump()
    data["attribution_job"] = job_read(queued.job)
    return EntityAssignmentExtended(**data)


@router.patch("/entity-assignments/{assignment_id}", response_model=EntityAssignmentRead)
async def change_entity_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentChange | AssignmentEnd,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> EntityAssignmentRead:
    """Change when a device tracked this entity: end it (`valid_to`), move its start, or move
    both. The device must belong to the project at the new start; records between the old
    and the new bounds are attributed again, so history follows the change."""
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    await _project_entity(session, context, assignment.entity_id)
    await hold_while_attributing(session, assignment.device_id)
    old_from, old_to = range_bounds(assignment.validity)
    change = (
        body if isinstance(body, AssignmentChange) else AssignmentChange(valid_to=body.valid_to)
    )
    new_from = change.valid_from if change.valid_from is not None else old_from
    new_to = (
        change.valid_to
        if "valid_to" in change.model_fields_set or isinstance(body, AssignmentEnd)
        else old_to
    )
    if new_to is not None and new_to <= new_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    if new_from != old_from:
        attribution = await resolve_attribution(session, assignment.device_id, new_from)
        if attribution.project_id != context.project.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Device is not assigned to this project at valid_from; extend the project "
                "assignment first",
            )
    assignment.validity = Range(new_from, new_to, bounds="[)")
    if change.reason is not None:
        assignment.reason = change.reason
    await flush_or_409(session, "Entity assignment")
    # Records between the old and the new bounds change hands: one job over the span from the
    # earliest to the latest bound that moved (D206; a start and an end moved together take the
    # assignment in between along, which the rewrite leaves as it is).
    now = utc_now()
    spans: list[tuple[datetime, datetime]] = []
    if new_from != old_from:
        spans.append((min(old_from, new_from), max(old_from, new_from)))
    if (old_to or now) != (new_to or now):
        spans.append((min(old_to or now, new_to or now), max(old_to or now, new_to or now)))
    queued = QueueResult(None, created=False)
    if spans:
        queued = await queue_job(
            session,
            device_id=assignment.device_id,
            start=min(s[0] for s in spans),
            end=max(s[1] for s in spans),
            reason="entity_assignment.changed",
            user=context.user,
            project_id=context.project.id,
        )
    await record_audit(
        session,
        user=context.user,
        action="entity_assignment.changed",
        object_type="device_entity_assignment",
        object_id=str(assignment.id),
        project_id=context.project.id,
        details={
            "from": [old_from.isoformat(), new_from.isoformat()],
            "to": [old_to.isoformat() if old_to else None, new_to.isoformat() if new_to else None],
            "attribution_job_id": str(queued.job.id) if queued.job else None,
        },
    )
    await session.commit()
    if queued.created and queued.job is not None:
        await publish_job(bus, queued.job)
    read = assignment_read(assignment)
    read.attribution_job = job_read(queued.job)
    return read
