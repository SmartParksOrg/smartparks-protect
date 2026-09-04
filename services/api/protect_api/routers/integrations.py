"""Outbound integrations per project (architecture 18): connectors, integrations, the delivery
log with request and response inspection, retry, test sends and backfill requests."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.integrations import (
    BackfillRequest,
    IntegrationCreate,
    IntegrationDeliveryDetail,
    IntegrationDeliveryRead,
    IntegrationDetail,
    IntegrationRead,
    IntegrationTestRequest,
    IntegrationTestResult,
    IntegrationUpdate,
)
from shared.bus import RedisStreamsBus, Topic
from shared.database import get_session
from shared.enums import BackfillStatus, DeliveryStatus
from shared.integrations.base import PermanentFailure, Skipped, TransientFailure
from shared.integrations.deliveries import (
    delivery_counts,
    integration_context,
    requeue,
)
from shared.integrations.registry import CONNECTORS, describe_connector
from shared.models import EntityCurrentState, Integration, IntegrationDelivery
from shared.permissions import Permission
from shared.secrets import encrypt_json
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}/integrations", tags=["integrations"])

MAX_BACKFILL_DAYS = 400


def _read(integration: Integration) -> IntegrationRead:
    data = IntegrationRead.model_validate(integration)
    data.has_credentials = integration.credentials_encrypted is not None
    return data


async def _integration(
    session: AsyncSession, project_id: uuid.UUID, integration_id: uuid.UUID
) -> Integration:
    integration = await get_or_404(session, Integration, integration_id, "Integration")
    if integration.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    return integration


def _check_connector(key: str, object_types: list[Any]) -> None:
    connector = CONNECTORS.get(key)
    if connector is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown connector {key}; known: {sorted(CONNECTORS)}",
        )
    unsupported = [str(t) for t in object_types if str(t) not in connector.supports]
    if unsupported:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{connector.label} cannot receive {', '.join(unsupported)}",
        )


@router.get("/connectors", response_model=list[dict[str, Any]])
async def list_connectors(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
) -> list[dict[str, Any]]:
    return [describe_connector(c) for c in CONNECTORS.values()]


@router.get("", response_model=PageResponse[IntegrationRead])
async def list_integrations(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    page: Page = Depends(page),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[IntegrationRead]:
    rows, next_cursor = await paginate(
        session,
        Integration.id,
        select(Integration).where(Integration.project_id == context.project.id),
        page,
    )
    return PageResponse(items=[_read(r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
async def create_integration(
    body: IntegrationCreate,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationRead:
    _check_connector(body.connector_key, body.object_types)
    integration = Integration(
        project_id=context.project.id,
        name=body.name,
        description=body.description,
        connector_key=body.connector_key,
        enabled=body.enabled,
        config=body.config,
        credentials_encrypted=encrypt_json(body.credentials) if body.credentials else None,
        object_types=[str(t) for t in body.object_types],
        entity_ids=[str(i) for i in body.entity_ids],
        device_ids=[str(i) for i in body.device_ids],
        event_types=[t.upper() for t in body.event_types],
        metric_keys=body.metric_keys,
        min_severity=body.min_severity,
        max_object_age_seconds=body.max_object_age_seconds,
        created_by_user_id=context.user.id,
    )
    session.add(integration)
    await flush_or_409(session, "Integration")
    await record_audit(
        session,
        user=context.user,
        action="integration.create",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"name": integration.name, "connector": integration.connector_key},
    )
    await session.commit()
    return _read(integration)


@router.get("/deliveries", response_model=PageResponse[IntegrationDeliveryRead])
async def list_deliveries(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    page: Page = Depends(page),
    integration_id: uuid.UUID | None = Query(None),
    delivery_status: DeliveryStatus | None = Query(None, alias="status"),
    object_type: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[IntegrationDeliveryRead]:
    statement = select(IntegrationDelivery).where(
        IntegrationDelivery.project_id == context.project.id
    )
    if integration_id is not None:
        statement = statement.where(IntegrationDelivery.integration_id == integration_id)
    if delivery_status is not None:
        statement = statement.where(IntegrationDelivery.status == delivery_status)
    if object_type is not None:
        statement = statement.where(IntegrationDelivery.object_type == object_type)
    cursor = None
    if page.cursor is not None:
        try:
            cursor = datetime.fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(IntegrationDelivery.created_at < cursor)
    rows = list(
        (
            await session.scalars(
                statement.order_by(IntegrationDelivery.created_at.desc()).limit(page.limit + 1)
            )
        ).all()
    )
    next_cursor = rows[page.limit - 1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(
        items=[IntegrationDeliveryRead.model_validate(r) for r in rows[: page.limit]],
        next_cursor=next_cursor,
    )


@router.get("/deliveries/{delivery_id}", response_model=IntegrationDeliveryDetail)
async def get_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDeliveryDetail:
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    if delivery.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    return IntegrationDeliveryDetail.model_validate(delivery)


@router.post("/deliveries/{delivery_id}/retry", response_model=IntegrationDeliveryRead)
async def retry_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDeliveryRead:
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    if delivery.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    if delivery.status == DeliveryStatus.SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery was sent already")
    requeue(delivery)
    await session.commit()
    return IntegrationDeliveryRead.model_validate(delivery)


@router.get("/{integration_id}", response_model=IntegrationDetail)
async def get_integration(
    integration_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDetail:
    integration = await _integration(session, context.project.id, integration_id)
    data = IntegrationDetail(**_read(integration).model_dump())
    data.counts = await delivery_counts(session, integration.id)
    data.counts_24h = await delivery_counts(
        session, integration.id, since=utc_now() - timedelta(hours=24)
    )
    return data


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def update_integration(
    integration_id: uuid.UUID,
    body: IntegrationUpdate,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationRead:
    integration = await _integration(session, context.project.id, integration_id)
    patch = body.model_dump(exclude_unset=True)
    credentials = patch.pop("credentials", None)
    if "object_types" in patch and patch["object_types"] is not None:
        _check_connector(integration.connector_key, patch["object_types"])
        patch["object_types"] = [str(t) for t in patch["object_types"]]
    for key in ("entity_ids", "device_ids"):
        if patch.get(key) is not None:
            patch[key] = [str(i) for i in patch[key]]
    if patch.get("event_types") is not None:
        patch["event_types"] = [t.upper() for t in patch["event_types"]]
    for key, value in patch.items():
        setattr(integration, key, value)
    if credentials:
        integration.credentials_encrypted = encrypt_json(credentials)
    await flush_or_409(session, "Integration")
    await record_audit(
        session,
        user=context.user,
        action="integration.update",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"fields": sorted(patch) + (["credentials"] if credentials else [])},
    )
    await session.commit()
    return _read(integration)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    integration = await _integration(session, context.project.id, integration_id)
    await record_audit(
        session,
        user=context.user,
        action="integration.delete",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"name": integration.name},
    )
    await session.delete(integration)
    await session.commit()


async def _test_location(
    session: AsyncSession, project_id: uuid.UUID, body: IntegrationTestRequest
) -> tuple[float, float] | None:
    if body.latitude is not None and body.longitude is not None:
        return (body.latitude, body.longitude)
    current = await session.scalar(
        select(EntityCurrentState)
        .where(
            EntityCurrentState.project_id == project_id,
            EntityCurrentState.latest_position.is_not(None),
        )
        .order_by(EntityCurrentState.latest_position_time.desc())
        .limit(1)
    )
    if current is None or current.latest_position is None:
        return None
    from geoalchemy2.shape import to_shape

    point = to_shape(current.latest_position)
    return (point.y, point.x)


@router.post("/{integration_id}/test", response_model=IntegrationTestResult)
async def test_integration(
    integration_id: uuid.UUID,
    body: IntegrationTestRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationTestResult:
    integration = await _integration(session, context.project.id, integration_id)
    connector = CONNECTORS.get(integration.connector_key)
    if connector is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown connector")
    location = await _test_location(session, context.project.id, body)
    try:
        response = await connector.test(integration_context(integration), location)
    except (PermanentFailure, TransientFailure, Skipped) as exc:
        integration.last_error = str(exc)
        integration.last_error_at = utc_now()
        await session.commit()
        return IntegrationTestResult(ok=False, detail=str(exc))
    integration.last_error = None
    await session.commit()
    return IntegrationTestResult(
        ok=True, detail=f"{connector.label} accepted the test", response=response
    )


@router.post("/{integration_id}/backfill", response_model=IntegrationRead)
async def request_backfill(
    integration_id: uuid.UUID,
    body: BackfillRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> IntegrationRead:
    integration = await _integration(session, context.project.id, integration_id)
    if body.time_to <= body.time_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "time_to must be after time_from"
        )
    if body.time_to - body.time_from > timedelta(days=MAX_BACKFILL_DAYS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"a backfill covers at most {MAX_BACKFILL_DAYS} days",
        )
    if integration.backfill.get("status") in (BackfillStatus.QUEUED, BackfillStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, "a backfill is running already")
    integration.backfill = {
        "status": BackfillStatus.QUEUED,
        "from": body.time_from.isoformat(),
        "to": body.time_to.isoformat(),
        "queued": 0,
        "scanned": 0,
        "requested_at": utc_now().isoformat(),
        "requested_by": str(context.user.id),
    }
    await record_audit(
        session,
        user=context.user,
        action="integration.backfill",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"from": body.time_from.isoformat(), "to": body.time_to.isoformat()},
    )
    await session.commit()
    await bus.publish(
        Topic.INTEGRATION_BACKFILL_REQUESTED,
        {
            "integration_id": str(integration.id),
            "from": body.time_from.isoformat(),
            "to": body.time_to.isoformat(),
        },
    )
    return _read(integration)
