"""Entities, features and device-to-entity assignments inside a project."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from protect_api.audit import record_audit
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
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.pictures import drop_picture, picture_response, store_picture
from protect_api.schemas.domain import (
    AssignmentChange,
    AssignmentEnd,
    AssignmentStart,
    EntityAssignmentCreate,
    EntityAssignmentExtended,
    EntityAssignmentRead,
    EntityBulkMove,
    EntityBulkMoveResult,
    EntityCreate,
    EntityRead,
    EntityUpdate,
    FeatureCreate,
    FeatureRead,
    FeatureUpdate,
)
from shared.database import get_session
from shared.domain.assignments import reattribute, resolve_attribution
from shared.models import (
    Device,
    DeviceEntityAssignment,
    Entity,
    EntityType,
    Feature,
    Group,
)
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["entities"])


def entity_read(entity: Entity) -> EntityRead:
    data = EntityRead.model_validate(entity)
    data.geometry = geom_to_geojson(entity.geom)
    return data


def feature_read(feature: Feature) -> FeatureRead:
    data = FeatureRead.model_validate(feature)
    data.geometry = geom_to_geojson(feature.geom)
    return data


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


def group_and_subgroups(group_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """The group's id and the ids of every group below it, however deep, for filters on a
    parent group (a recursive query)."""
    tree = select(Group.id).where(Group.id == group_id).cte("group_tree", recursive=True)
    below = aliased(Group)
    tree = tree.union_all(select(below.id).where(below.parent_id == tree.c.id))
    return select(tree.c.id)


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
    statement = select(Entity).where(context.where(Entity.project_id))
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
    return PageResponse(items=[entity_read(r) for r in rows], next_cursor=next_cursor)


@router.post("/entities", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    body: EntityCreate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
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
    await session.commit()
    return entity_read(entity)


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
    if entity.project_id != context.project.id:
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
    """The entity's profile picture (decision D110), a WebP square."""
    entity = await _project_entity(session, context, entity_id)
    return await picture_response(entity.picture_key, entity.picture_updated_at)


@router.put("/entities/{entity_id}/picture", response_model=EntityRead)
async def set_entity_picture(
    entity_id: uuid.UUID,
    file: UploadFile,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    """Set the profile picture from a JPEG, PNG or WebP; the server keeps a small square."""
    entity = await _project_entity(session, context, entity_id)
    entity.picture_key, entity.picture_updated_at = await store_picture("entities", entity.id, file)
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
    return PageResponse(items=[feature_read(r) for r in rows], next_cursor=next_cursor)


@router.post("/features", response_model=FeatureRead, status_code=status.HTTP_201_CREATED)
async def create_feature(
    body: FeatureCreate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
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


async def _project_feature(
    session: AsyncSession, context: ProjectContext, feature_id: uuid.UUID
) -> Feature:
    feature = await get_or_404(session, Feature, feature_id, "Feature")
    if feature.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found")
    return feature


@router.get("/features/{feature_id}", response_model=FeatureRead)
async def get_feature(
    feature_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    return feature_read(await _project_feature(session, context, feature_id))


@router.patch("/features/{feature_id}", response_model=FeatureRead)
async def update_feature(
    feature_id: uuid.UUID,
    body: FeatureUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> FeatureRead:
    feature = await _project_feature(session, context, feature_id)
    changed = apply_patch(feature, body, exclude={"geometry"})
    if body.geometry is not None:
        feature.geom = geojson_to_geom(body.geometry.as_dict())
        changed["geometry"] = body.geometry.as_dict()
    await flush_or_409(session, "Feature")
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
    return feature_read(feature)


@router.delete("/features/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature(
    feature_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
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
        .where(context.where(Entity.project_id))
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
) -> EntityAssignmentRead:
    """Assign a device to an entity of this project from `valid_from`. The device must belong to
    the project at that moment. Overlapping assignments of the same device are rejected."""
    await _project_entity(session, context, body.entity_id)
    await get_or_404(session, Device, body.device_id, "Device")
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
        entity_id=body.entity_id,
        validity=Range(body.valid_from, body.valid_to, bounds="[)"),
        reason=body.reason,
        created_by_user_id=context.user.id,
    )
    session.add(assignment)
    await flush_or_409(session, "Entity assignment")
    # Records already decoded inside the range get the entity now (decision D103).
    reattributed = await reattribute(
        session, body.device_id, body.valid_from, body.valid_to or utc_now()
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
            "entity_id": str(body.entity_id),
            "valid_from": body.valid_from.isoformat(),
            "reattributed": reattributed,
        },
    )
    await session.commit()
    return assignment_read(assignment)


@router.post(
    "/entity-assignments/{assignment_id}/extend-start", response_model=EntityAssignmentExtended
)
async def extend_entity_assignment_start(
    assignment_id: uuid.UUID,
    body: AssignmentStart,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityAssignmentExtended:
    """Move the start of an entity assignment back and attribute the records in between
    (decision D103). The device must belong to this project at the new start: extend the
    project assignment first."""
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    await _project_entity(session, context, assignment.entity_id)
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
    counts = await reattribute(session, assignment.device_id, body.valid_from, old_from)
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
            "reattributed": counts,
        },
    )
    await session.commit()
    read = assignment_read(assignment)
    return EntityAssignmentExtended(**read.model_dump(), reattributed=counts)


@router.patch("/entity-assignments/{assignment_id}", response_model=EntityAssignmentRead)
async def change_entity_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentChange | AssignmentEnd,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityAssignmentRead:
    """Change when a device tracked this entity: end it (`valid_to`), move its start, or move
    both. The device must belong to the project at the new start; records between the old
    and the new bounds are attributed again, so history follows the change."""
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    await _project_entity(session, context, assignment.entity_id)
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
    # Records between the old and the new bounds change hands; recompute that span only.
    now = utc_now()
    starts = [old_from, new_from]
    ends = [old_to or now, new_to or now]
    counts = {"positions": 0, "measurements": 0}
    if new_from != old_from:
        counts = await reattribute(session, assignment.device_id, min(starts), max(starts))
    if (old_to or now) != (new_to or now):
        more = await reattribute(session, assignment.device_id, min(ends), max(ends))
        counts = {k: counts[k] + more[k] for k in counts}
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
            "reattributed": counts,
        },
    )
    await session.commit()
    return assignment_read(assignment)
