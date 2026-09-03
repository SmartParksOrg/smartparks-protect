"""Entities, features and device-to-entity assignments inside a project."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import (
    apply_patch,
    flush_or_409,
    geojson_to_geom,
    geom_to_geojson,
    get_or_404,
    range_bounds,
)
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.domain import (
    AssignmentEnd,
    EntityAssignmentCreate,
    EntityAssignmentRead,
    EntityCreate,
    EntityRead,
    EntityUpdate,
    FeatureCreate,
    FeatureRead,
    FeatureUpdate,
)
from shared.database import get_session
from shared.domain.assignments import resolve_attribution
from shared.models import Device, DeviceEntityAssignment, Entity, EntityType, Feature
from shared.permissions import Permission

router = APIRouter(prefix="/projects/{project_id}", tags=["entities"])


def entity_read(entity: Entity) -> EntityRead:
    data = EntityRead.model_validate(entity)
    data.geometry = geom_to_geojson(entity.geom)
    return data


def feature_read(feature: Feature) -> FeatureRead:
    data = FeatureRead.model_validate(feature)
    data.geometry = geom_to_geojson(feature.geom)
    return data


def assignment_read(assignment: DeviceEntityAssignment) -> EntityAssignmentRead:
    valid_from, valid_to = range_bounds(assignment.validity)
    return EntityAssignmentRead(
        id=assignment.id,
        device_id=assignment.device_id,
        entity_id=assignment.entity_id,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=assignment.reason,
        created_at=assignment.created_at,
    )


# Entities


@router.get("/entities", response_model=PageResponse[EntityRead])
async def list_entities(
    page: Page = Depends(page),
    entity_type_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EntityRead]:
    statement = select(Entity).where(Entity.project_id == context.project.id)
    if entity_type_id is not None:
        statement = statement.where(Entity.entity_type_id == entity_type_id)
    if status_filter is not None:
        statement = statement.where(Entity.status == status_filter)
    rows, next_cursor = await paginate(session, Entity.id, statement, page)
    return PageResponse(items=[entity_read(r) for r in rows], next_cursor=next_cursor)


@router.post("/entities", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    body: EntityCreate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityRead:
    await get_or_404(session, EntityType, body.entity_type_id, "Entity type")
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
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[FeatureRead]:
    statement = select(Feature).where(Feature.project_id == context.project.id)
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
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EntityAssignmentRead]:
    statement = (
        select(DeviceEntityAssignment)
        .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
        .where(Entity.project_id == context.project.id)
    )
    if entity_id is not None:
        statement = statement.where(DeviceEntityAssignment.entity_id == entity_id)
    if device_id is not None:
        statement = statement.where(DeviceEntityAssignment.device_id == device_id)
    rows, next_cursor = await paginate(session, DeviceEntityAssignment.id, statement, page)
    return PageResponse(items=[assignment_read(r) for r in rows], next_cursor=next_cursor)


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
        },
    )
    await session.commit()
    return assignment_read(assignment)


@router.patch("/entity-assignments/{assignment_id}", response_model=EntityAssignmentRead)
async def end_entity_assignment(
    assignment_id: uuid.UUID,
    body: AssignmentEnd,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityAssignmentRead:
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    await _project_entity(session, context, assignment.entity_id)
    valid_from, _ = range_bounds(assignment.validity)
    if body.valid_to <= valid_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    assignment.validity = Range(valid_from, body.valid_to, bounds="[)")
    await flush_or_409(session, "Entity assignment")
    await record_audit(
        session,
        user=context.user,
        action="entity_assignment.ended",
        object_type="device_entity_assignment",
        object_id=str(assignment.id),
        project_id=context.project.id,
        details={"valid_to": body.valid_to.isoformat()},
    )
    await session.commit()
    return assignment_read(assignment)
