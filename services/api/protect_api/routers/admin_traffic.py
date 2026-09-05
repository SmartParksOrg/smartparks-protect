"""Server admin, Traffic: everything the server receives, delivers and sends to devices, side
by side (architecture 8.3 and 26). Three lists with their own columns, one summary, bounded
by a window and a row limit like every other list."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.crud import get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page
from protect_api.routers.network import MAX_ROWS, TrafficRow, traffic_rows
from protect_api.schemas.platform import (
    AdminCommandRead,
    AdminDeliveryDetail,
    AdminDeliveryRead,
    TrafficSummary,
)
from shared.database import get_session
from shared.enums import DeliveryStatus, ProcessingStatus
from shared.models import (
    Command,
    DataSource,
    Device,
    Integration,
    IntegrationDelivery,
    Project,
    SourceEvent,
)
from shared.timeutil import require_aware, utc_now

router = APIRouter(
    prefix="/admin/traffic", tags=["admin"], dependencies=[Depends(require_server_admin)]
)


@router.get("/summary", response_model=TrafficSummary)
async def traffic_summary(session: AsyncSession = Depends(get_session)) -> TrafficSummary:
    since = utc_now() - timedelta(hours=1)
    inbound = await session.execute(
        select(
            func.count(),
            func.count().filter(SourceEvent.processing_status == ProcessingStatus.FAILED),
            func.count().filter(SourceEvent.device_id.is_(None)),
        ).where(SourceEvent.ingested_at >= since)
    )
    total, failed, unassigned = inbound.one()
    outbound = await session.execute(
        select(IntegrationDelivery.status, func.count())
        .where(IntegrationDelivery.created_at >= since)
        .group_by(IntegrationDelivery.status)
    )
    commands = await session.execute(
        select(Command.status, func.count())
        .where(Command.created_at >= since)
        .group_by(Command.status)
    )
    return TrafficSummary(
        inbound_events=int(total or 0),
        inbound_failed=int(failed or 0),
        inbound_unassigned=int(unassigned or 0),
        outbound_by_status={str(k): int(v) for k, v in outbound.all()},
        commands_by_status={str(k): int(v) for k, v in commands.all()},
    )


@router.get("/inbound", response_model=list[TrafficRow])
async def inbound(
    data_source_id: uuid.UUID | None = None,
    external_id: str | None = None,
    event_type: str | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=MAX_ROWS),
    include_payload: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[TrafficRow]:
    """Every source event across all data sources, newest first, linked to a device or not."""
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    statement = (
        select(SourceEvent, Device.name, DataSource.name)
        .outerjoin(Device, Device.id == SourceEvent.device_id)
        .join(DataSource, DataSource.id == SourceEvent.data_source_id)
        .where(SourceEvent.ingested_at >= time_from, SourceEvent.ingested_at < time_to)
    )
    if data_source_id is not None:
        statement = statement.where(SourceEvent.data_source_id == data_source_id)
    if event_type is not None:
        statement = statement.where(SourceEvent.event_type == event_type)
    if external_id:
        statement = statement.where(SourceEvent.external_id.ilike(f"%{external_id}%"))
    rows = (
        await session.execute(statement.order_by(SourceEvent.ingested_at.desc()).limit(limit))
    ).all()
    return await traffic_rows(session, rows, include_payload)


def _delivery_read(
    delivery: IntegrationDelivery, integration: Integration | None, project_name: str | None
) -> AdminDeliveryRead:
    return AdminDeliveryRead(
        **IntegrationDeliveryRead_fields(delivery),
        integration_name=integration.name if integration else None,
        connector_key=integration.connector_key if integration else None,
        project_name=project_name,
    )


def IntegrationDeliveryRead_fields(delivery: IntegrationDelivery) -> dict[str, Any]:
    from protect_api.schemas.integrations import IntegrationDeliveryRead

    return IntegrationDeliveryRead.model_validate(delivery).model_dump()


@router.get("/outbound", response_model=PageResponse[AdminDeliveryRead])
async def outbound(
    page: Page = Depends(page),
    project_id: uuid.UUID | None = None,
    integration_id: uuid.UUID | None = None,
    delivery_status: DeliveryStatus | None = Query(None, alias="status"),
    object_type: str | None = None,
    stale: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AdminDeliveryRead]:
    """Every integration delivery across all projects, newest first."""
    statement = (
        select(IntegrationDelivery, Integration, Project.name)
        .outerjoin(Integration, Integration.id == IntegrationDelivery.integration_id)
        .outerjoin(Project, Project.id == IntegrationDelivery.project_id)
    )
    if project_id is not None:
        statement = statement.where(IntegrationDelivery.project_id == project_id)
    if integration_id is not None:
        statement = statement.where(IntegrationDelivery.integration_id == integration_id)
    if delivery_status is not None:
        statement = statement.where(IntegrationDelivery.status == delivery_status)
    if object_type is not None:
        statement = statement.where(IntegrationDelivery.object_type == object_type)
    if stale:
        statement = statement.where(IntegrationDelivery.stale_at.is_not(None))
    if page.cursor is not None:
        try:
            cursor = datetime.fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(IntegrationDelivery.created_at < cursor)
    rows = (
        await session.execute(
            statement.order_by(IntegrationDelivery.created_at.desc()).limit(page.limit + 1)
        )
    ).all()
    items = [_delivery_read(d, i, name) for d, i, name in rows[: page.limit]]
    next_cursor = items[-1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)


@router.get("/outbound/{delivery_id}", response_model=AdminDeliveryDetail)
async def outbound_detail(
    delivery_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AdminDeliveryDetail:
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    integration = await session.get(Integration, delivery.integration_id)
    project_name = await session.scalar(
        select(Project.name).where(Project.id == delivery.project_id)
    )
    from protect_api.schemas.integrations import IntegrationDeliveryDetail

    return AdminDeliveryDetail(
        **IntegrationDeliveryDetail.model_validate(delivery).model_dump(),
        integration_name=integration.name if integration else None,
        connector_key=integration.connector_key if integration else None,
        project_name=project_name,
    )


@router.get("/commands", response_model=PageResponse[AdminCommandRead])
async def commands(
    page: Page = Depends(page),
    project_id: uuid.UUID | None = None,
    command_status: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AdminCommandRead]:
    """Every command across all devices, newest first."""
    from protect_api.schemas.control import CommandRead

    statement = (
        select(Command, Project.name, Device.name)
        .outerjoin(Project, Project.id == Command.project_id)
        .outerjoin(Device, Device.id == Command.device_id)
    )
    if project_id is not None:
        statement = statement.where(Command.project_id == project_id)
    if command_status:
        statement = statement.where(Command.status == command_status)
    if page.cursor:
        try:
            before = datetime.fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(Command.created_at < before)
    rows = (
        await session.execute(statement.order_by(Command.created_at.desc()).limit(page.limit + 1))
    ).all()
    items = [
        AdminCommandRead(
            **CommandRead.model_validate(c).model_dump(), project_name=pname, device_name=dname
        )
        for c, pname, dname in rows[: page.limit]
    ]
    next_cursor = items[-1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)
