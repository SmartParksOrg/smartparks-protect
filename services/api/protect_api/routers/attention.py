"""Needs Attention (architecture 26.6 and 28.6): unknown identities, failed source events, dead
letters. Server admin only in phase 2. Every action is audited."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.domain import DeviceRead, ExternalIdentityRead
from shared.bus import RedisStreamsBus, Topic, is_stale
from shared.database import get_session
from shared.enums import DeviceStatus, ProcessingStatus
from shared.ingest import republish_source_event
from shared.models import (
    DataSource,
    Device,
    DeviceProjectAssignment,
    DeviceType,
    ExternalIdentity,
    Project,
    SourceEvent,
    User,
)
from shared.timeutil import require_aware

router = APIRouter(
    prefix="/attention", tags=["needs attention"], dependencies=[Depends(require_server_admin)]
)

REPROCESS_BATCH = 1000
DEAD_TOPICS = (
    Topic.SOURCE_EVENT_RECEIVED,
    Topic.POSITION_CREATED,
    Topic.MEASUREMENT_CREATED,
    Topic.DEVICE_STATE_CHANGED,
    Topic.EVENT_CREATED,
    Topic.NEEDS_ATTENTION_CREATED,
)


class AttentionSummary(BaseModel):
    unknown_identities: int
    failed_source_events: int
    unassigned_source_events: int
    dead_letters: dict[str, int]
    stale_workers: list[str]
    workers: dict[str, datetime | None]


class UnknownIdentity(ExternalIdentityRead):
    data_source_name: str
    adapter_key: str
    inferred_type: str | None = None


class CreateDeviceForIdentity(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    device_type_id: uuid.UUID
    project_id: uuid.UUID | None = None
    valid_from: datetime | None = None
    reprocess: bool = True


class LinkIdentity(BaseModel):
    device_id: uuid.UUID
    reprocess: bool = True


class ReprocessResult(BaseModel):
    republished: int


class SourceEventSummary(BaseModel):
    id: int
    ingested_at: datetime
    data_source_id: uuid.UUID
    external_id: str | None
    device_id: uuid.UUID | None
    event_type: str
    processing_status: str
    error_code: str | None
    trace_id: uuid.UUID | None


class DeadLetter(BaseModel):
    id: str
    topic: str
    error_code: str | None = None
    error: str | None = None
    delivery_count: int | None = None
    dead_at: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any]


@router.get("/summary", response_model=AttentionSummary)
async def summary(
    session: AsyncSession = Depends(get_session), bus: RedisStreamsBus = Depends(get_bus)
) -> AttentionSummary:
    unknown = await session.scalar(
        select(func.count())
        .select_from(ExternalIdentity)
        .where(ExternalIdentity.device_id.is_(None), ExternalIdentity.ignored.is_(False))
    )
    failed = await session.scalar(
        select(func.count())
        .select_from(SourceEvent)
        .where(SourceEvent.processing_status == ProcessingStatus.FAILED)
    )
    unassigned = await session.scalar(
        select(func.count())
        .select_from(SourceEvent)
        .where(SourceEvent.processing_status == ProcessingStatus.UNASSIGNED)
    )
    dead = {topic: await bus.dead_count(topic) for topic in DEAD_TOPICS}
    workers = await bus.heartbeats()
    return AttentionSummary(
        unknown_identities=int(unknown or 0),
        failed_source_events=int(failed or 0),
        unassigned_source_events=int(unassigned or 0),
        dead_letters={k: v for k, v in dead.items() if v},
        stale_workers=[w for w, stamp in workers.items() if is_stale(stamp)],
        workers=workers,
    )


@router.get("/identities", response_model=PageResponse[UnknownIdentity])
async def unknown_identities(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[UnknownIdentity]:
    statement = select(ExternalIdentity).where(
        ExternalIdentity.device_id.is_(None), ExternalIdentity.ignored.is_(False)
    )
    rows, next_cursor = await paginate(session, ExternalIdentity.id, statement, page)
    sources = {
        s.id: s
        for s in (
            await session.scalars(
                select(DataSource).where(DataSource.id.in_({r.data_source_id for r in rows}))
            )
        ).all()
    }
    items = [
        UnknownIdentity(
            **ExternalIdentityRead.model_validate(r).model_dump(),
            data_source_name=sources[r.data_source_id].name,
            adapter_key=sources[r.data_source_id].adapter_key,
            inferred_type=r.attributes.get("inferred_type"),
        )
        for r in rows
    ]
    return PageResponse(items=items, next_cursor=next_cursor)


async def _reprocess_identity(
    session: AsyncSession, bus: RedisStreamsBus, identity: ExternalIdentity
) -> int:
    """Attach the device to retained source events of this identity and put them back on the bus."""
    events = (
        await session.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.external_identity_id == identity.id,
                SourceEvent.processing_status.in_(
                    [ProcessingStatus.UNASSIGNED, ProcessingStatus.FAILED, ProcessingStatus.IGNORED]
                ),
            )
            .order_by(SourceEvent.ingested_at)
            .limit(REPROCESS_BATCH)
        )
    ).all()
    for event in events:
        event.device_id = identity.device_id
        event.processing_status = ProcessingStatus.RECEIVED
        event.error_code = None
    await session.commit()
    for event in events:
        await republish_source_event(bus, event)
    return len(events)


@router.post(
    "/identities/{identity_id}/create-device",
    response_model=DeviceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_device_for_identity(
    identity_id: uuid.UUID,
    body: CreateDeviceForIdentity,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> Device:
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    if identity.device_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Identity is already linked to a device")
    await get_or_404(session, DeviceType, body.device_type_id, "Device type")
    device = Device(name=body.name, device_type_id=body.device_type_id, status=DeviceStatus.ACTIVE)
    session.add(device)
    await flush_or_409(session, "Device")
    identity.device_id = device.id
    if body.project_id is not None:
        await get_or_404(session, Project, body.project_id, "Project")
        valid_from = (
            require_aware(body.valid_from)
            if body.valid_from
            else (identity.first_seen_at or device.created_at)
        )
        session.add(
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=body.project_id,
                validity=Range(valid_from, None, bounds="[)"),
                reason="created from Needs Attention",
                created_by_user_id=user.id,
            )
        )
        await flush_or_409(session, "Project assignment")
    await record_audit(
        session,
        user=user,
        action="attention.device_created",
        object_type="external_identity",
        object_id=str(identity.id),
        project_id=body.project_id,
        details={"device_id": str(device.id), "external_id": identity.external_id},
    )
    await session.commit()
    if body.reprocess:
        await _reprocess_identity(session, bus, identity)
    return device


@router.post("/identities/{identity_id}/link", response_model=ReprocessResult)
async def link_identity(
    identity_id: uuid.UUID,
    body: LinkIdentity,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ReprocessResult:
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    await get_or_404(session, Device, body.device_id, "Device")
    identity.device_id = body.device_id
    identity.ignored = False
    await record_audit(
        session,
        user=user,
        action="attention.identity_linked",
        object_type="external_identity",
        object_id=str(identity.id),
        details={"device_id": str(body.device_id)},
    )
    await session.commit()
    count = await _reprocess_identity(session, bus, identity) if body.reprocess else 0
    return ReprocessResult(republished=count)


@router.post("/identities/{identity_id}/ignore", status_code=status.HTTP_204_NO_CONTENT)
async def ignore_identity(
    identity_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    identity.ignored = True
    await record_audit(
        session,
        user=user,
        action="attention.identity_ignored",
        object_type="external_identity",
        object_id=str(identity.id),
    )
    await session.commit()


@router.post("/identities/{identity_id}/reprocess", response_model=ReprocessResult)
async def reprocess_identity(
    identity_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ReprocessResult:
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    if identity.device_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link the identity to a device first")
    await record_audit(
        session,
        user=user,
        action="attention.identity_reprocessed",
        object_type="external_identity",
        object_id=str(identity.id),
    )
    await session.commit()
    return ReprocessResult(republished=await _reprocess_identity(session, bus, identity))


@router.get("/source-events", response_model=list[SourceEventSummary])
async def failed_source_events(
    status_filter: ProcessingStatus = Query(ProcessingStatus.FAILED, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    before: datetime | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SourceEventSummary]:
    """Newest first, keyset on ingested_at."""
    statement = select(SourceEvent).where(SourceEvent.processing_status == status_filter)
    if before is not None:
        statement = statement.where(SourceEvent.ingested_at < require_aware(before))
    rows = await session.scalars(statement.order_by(SourceEvent.ingested_at.desc()).limit(limit))
    return [SourceEventSummary.model_validate(r, from_attributes=True) for r in rows]


@router.post("/source-events/{source_event_id}/reprocess", response_model=ReprocessResult)
async def reprocess_source_event(
    source_event_id: int,
    ingested_at: datetime,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ReprocessResult:
    event = await session.scalar(
        select(SourceEvent).where(
            SourceEvent.id == source_event_id, SourceEvent.ingested_at == require_aware(ingested_at)
        )
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source event not found")
    if event.device_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Source event has no device; resolve its identity first"
        )
    event.processing_status = ProcessingStatus.RECEIVED
    event.error_code = None
    await record_audit(
        session,
        user=user,
        action="attention.source_event_reprocessed",
        object_type="source_event",
        object_id=str(event.id),
    )
    await session.commit()
    await republish_source_event(bus, event)
    return ReprocessResult(republished=1)


@router.get("/dead-letters", response_model=list[DeadLetter])
async def dead_letters(
    topic: str = Query(Topic.SOURCE_EVENT_RECEIVED),
    limit: int = Query(100, ge=1, le=500),
    bus: RedisStreamsBus = Depends(get_bus),
) -> list[DeadLetter]:
    entries = await bus.list_dead(topic, count=limit)
    return [
        DeadLetter(
            id=e["id"],
            topic=topic,
            error_code=e.get("error_code"),
            error=e.get("error"),
            delivery_count=int(e["delivery_count"]) if e.get("delivery_count") else None,
            dead_at=e.get("dead_at"),
            trace_id=e.get("trace_id") or None,
            payload=e["payload"],
        )
        for e in entries
    ]


@router.post("/dead-letters/{topic}/{dead_id}/retry", response_model=ReprocessResult)
async def retry_dead_letter(
    topic: str,
    dead_id: str,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ReprocessResult:
    new_id = await bus.retry_dead(topic, dead_id)
    if new_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dead letter not found")
    await record_audit(
        session,
        user=user,
        action="attention.dead_letter_retried",
        object_type="dead_letter",
        object_id=f"{topic}/{dead_id}",
    )
    await session.commit()
    return ReprocessResult(republished=1)


@router.post("/dead-letters/{topic}/{dead_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_dead_letter(
    topic: str,
    dead_id: str,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> None:
    if not await bus.resolve_dead(topic, dead_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dead letter not found")
    await record_audit(
        session,
        user=user,
        action="attention.dead_letter_resolved",
        object_type="dead_letter",
        object_id=f"{topic}/{dead_id}",
    )
    await session.commit()
