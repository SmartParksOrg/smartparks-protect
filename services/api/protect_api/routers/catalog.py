"""Server-level catalogues: entity types, device types, metrics. Any account reads them, server
admins change them."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.domain import (
    DeviceTypeCreate,
    DeviceTypeRead,
    DeviceTypeUpdate,
    EntityTypeCreate,
    EntityTypeRead,
    EntityTypeUpdate,
    MetricCreate,
    MetricRead,
    MetricUpdate,
)
from shared.database import get_session
from shared.models import DeviceType, EntityType, Metric, User

router = APIRouter(tags=["catalog"])


async def _delete(session: AsyncSession, obj: Any, user: User, what: str, object_type: str) -> None:
    await session.delete(obj)
    try:
        await session.flush()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{what} is in use and cannot be deleted"
        ) from None
    await record_audit(
        session,
        user=user,
        action=f"{object_type}.deleted",
        object_type=object_type,
        object_id=str(getattr(obj, "id", getattr(obj, "key", None))),
    )
    await session.commit()


# Entity types


@router.get("/entity-types", response_model=PageResponse[EntityTypeRead])
async def list_entity_types(
    page: Page = Depends(page),
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EntityTypeRead]:
    rows, next_cursor = await paginate(session, EntityType.id, select(EntityType), page)
    return PageResponse(
        items=[EntityTypeRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post("/entity-types", response_model=EntityTypeRead, status_code=status.HTTP_201_CREATED)
async def create_entity_type(
    body: EntityTypeCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> EntityType:
    row = EntityType(**body.model_dump())
    session.add(row)
    await flush_or_409(session, "Entity type")
    await record_audit(
        session,
        user=user,
        action="entity_type.created",
        object_type="entity_type",
        object_id=str(row.id),
        details={"key": row.key},
    )
    await session.commit()
    return row


@router.get("/entity-types/{entity_type_id}", response_model=EntityTypeRead)
async def get_entity_type(
    entity_type_id: uuid.UUID,
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> EntityType:
    return await get_or_404(session, EntityType, entity_type_id, "Entity type")


@router.patch("/entity-types/{entity_type_id}", response_model=EntityTypeRead)
async def update_entity_type(
    entity_type_id: uuid.UUID,
    body: EntityTypeUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> EntityType:
    row = await get_or_404(session, EntityType, entity_type_id, "Entity type")
    changed = apply_patch(row, body)
    await record_audit(
        session,
        user=user,
        action="entity_type.updated",
        object_type="entity_type",
        object_id=str(row.id),
        details=changed,
    )
    await session.commit()
    return row


@router.delete("/entity-types/{entity_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity_type(
    entity_type_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_or_404(session, EntityType, entity_type_id, "Entity type")
    await _delete(session, row, user, "Entity type", "entity_type")


# Device types


@router.get("/device-types", response_model=PageResponse[DeviceTypeRead])
async def list_device_types(
    page: Page = Depends(page),
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[DeviceTypeRead]:
    rows, next_cursor = await paginate(session, DeviceType.id, select(DeviceType), page)
    return PageResponse(
        items=[DeviceTypeRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post("/device-types", response_model=DeviceTypeRead, status_code=status.HTTP_201_CREATED)
async def create_device_type(
    body: DeviceTypeCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceType:
    row = DeviceType(**body.model_dump())
    session.add(row)
    await flush_or_409(session, "Device type")
    await record_audit(
        session,
        user=user,
        action="device_type.created",
        object_type="device_type",
        object_id=str(row.id),
        details={"key": row.key},
    )
    await session.commit()
    return row


@router.get("/device-types/{device_type_id}", response_model=DeviceTypeRead)
async def get_device_type(
    device_type_id: uuid.UUID,
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceType:
    return await get_or_404(session, DeviceType, device_type_id, "Device type")


@router.patch("/device-types/{device_type_id}", response_model=DeviceTypeRead)
async def update_device_type(
    device_type_id: uuid.UUID,
    body: DeviceTypeUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceType:
    row = await get_or_404(session, DeviceType, device_type_id, "Device type")
    changed = apply_patch(row, body)
    await record_audit(
        session,
        user=user,
        action="device_type.updated",
        object_type="device_type",
        object_id=str(row.id),
        details=changed,
    )
    await session.commit()
    return row


@router.delete("/device-types/{device_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device_type(
    device_type_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_or_404(session, DeviceType, device_type_id, "Device type")
    await _delete(session, row, user, "Device type", "device_type")


# Metrics


@router.get("/metrics", response_model=PageResponse[MetricRead])
async def list_metrics(
    page: Page = Depends(page),
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[MetricRead]:
    rows, next_cursor = await paginate(session, Metric.key, select(Metric), page)
    return PageResponse(items=[MetricRead.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.post("/metrics", response_model=MetricRead, status_code=status.HTTP_201_CREATED)
async def create_metric(
    body: MetricCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Metric:
    row = Metric(**body.model_dump())
    session.add(row)
    await flush_or_409(session, "Metric")
    await record_audit(
        session, user=user, action="metric.created", object_type="metric", object_id=row.key
    )
    await session.commit()
    return row


@router.get("/metrics/{key}", response_model=MetricRead)
async def get_metric(
    key: str, _: User = Depends(current_active_user), session: AsyncSession = Depends(get_session)
) -> Metric:
    return await get_or_404(session, Metric, key, "Metric")


@router.patch("/metrics/{key}", response_model=MetricRead)
async def update_metric(
    key: str,
    body: MetricUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Metric:
    row = await get_or_404(session, Metric, key, "Metric")
    changed = apply_patch(row, body)
    await record_audit(
        session,
        user=user,
        action="metric.updated",
        object_type="metric",
        object_id=row.key,
        details=changed,
    )
    await session.commit()
    return row


@router.delete("/metrics/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(
    key: str,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await get_or_404(session, Metric, key, "Metric")
    await _delete(session, row, user, "Metric", "metric")
