"""Needs Attention (architecture 26.6 and 28.6): unknown identities, failed source events, dead
letters. Server admin only in phase 2. Every action is audited."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import Range, array
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.domain import DeviceRead, ExternalIdentityRead
from protect_api.serial import fill_serial_from_identity
from shared.bus import RedisStreamsBus, Topic, is_stale
from shared.config import get_settings
from shared.curation.effective import effective_time
from shared.database import get_session
from shared.enums import DeviceStatus, ProcessingStatus
from shared.ingest import republish_source_event
from shared.models import (
    DataSource,
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityType,
    ExternalIdentity,
    Group,
    Measurement,
    Metric,
    Position,
    Project,
    SourceEvent,
    User,
)
from shared.timeutil import require_aware, utc_now

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
    uncategorized_metrics: int = 0
    clock_ahead_devices: int = 0


class ClockAheadDevice(BaseModel):
    """A device with records whose device time runs ahead of the delivery (decision D119):
    kept, invalid, waiting for a curation job with a time offset."""

    device_id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    positions: int
    measurements: int
    until: datetime


class NewMetric(BaseModel):
    """A metric that registered itself on arrival (category `uncategorized`, decision D102),
    with how many devices report it and when last, so an administrator can define it."""

    key: str
    label: str
    unit: str | None
    value_type: str
    created_at: datetime
    devices: int
    last_time: datetime | None
    sample: Any = None


class NewMetricsResponse(BaseModel):
    items: list[NewMetric]
    categories: list[str]


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


BULK_MAX = 500


class BulkIdentityIds(BaseModel):
    identity_ids: list[uuid.UUID] = Field(min_length=1, max_length=BULK_MAX)


class BulkCreateDevices(BulkIdentityIds):
    """Devices for many unknown identities at once (decision D96): one type, optionally one
    project (assigned from the identity's first sighting) and one entity type, in which case
    every device gets an entity of that type with the same name, assigned from the same time.
    Names come from the platform (`name` in the identity attributes) or the external id."""

    device_type_id: uuid.UUID
    project_id: uuid.UUID | None = None
    entity_type_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = Field(
        default=None, description="The group the new entities go into (decision D98)"
    )
    reprocess: bool = True


class BulkSkipped(BaseModel):
    identity_id: uuid.UUID
    external_id: str | None = None
    reason: str


class BulkCreateResult(BaseModel):
    created: int
    entities: int
    republished: int
    device_ids: list[uuid.UUID]
    skipped: list[BulkSkipped]


class BulkIgnoreResult(BaseModel):
    ignored: int
    skipped: list[BulkSkipped]


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
    uncategorized = await session.scalar(
        select(func.count()).select_from(Metric).where(Metric.category == "uncategorized")
    )
    clock_ahead = len(await _clock_ahead_devices(session))
    return AttentionSummary(
        unknown_identities=int(unknown or 0),
        failed_source_events=int(failed or 0),
        unassigned_source_events=int(unassigned or 0),
        dead_letters={k: v for k, v in dead.items() if v},
        stale_workers=[w for w, stamp in workers.items() if is_stale(stamp)],
        workers=workers,
        uncategorized_metrics=int(uncategorized or 0),
        clock_ahead_devices=clock_ahead,
    )


async def _clock_ahead_devices(session: AsyncSession) -> list[ClockAheadDevice]:
    """Records in the future, per device: `time > now` keeps the hypertable scan to the
    chunks after today, so the count is cheap however large the history is."""
    horizon = utc_now() + timedelta(seconds=get_settings().clock_ahead_tolerance_seconds)
    found: dict[uuid.UUID, dict[str, Any]] = {}
    for model, kind in ((Position, "positions"), (Measurement, "measurements")):
        rows = (
            await session.execute(
                select(model.device_id, func.count(), func.max(effective_time(model)))
                .where(
                    model.time > horizon,  # chunk exclusion: only the chunks after today
                    or_(model.curated_time.is_(None), model.curated_time > horizon),
                )
                .group_by(model.device_id)
            )
        ).all()
        for device_id, count, until in rows:
            entry = found.setdefault(device_id, {"positions": 0, "measurements": 0, "until": until})
            entry[kind] = int(count)
            entry["until"] = max(entry["until"], until)
    if not found:
        return []
    names = {
        d.id: d.name
        for d in (await session.scalars(select(Device).where(Device.id.in_(found)))).all()
    }
    now = utc_now()
    projects = {
        device_id: project_id
        for device_id, project_id in (
            await session.execute(
                select(DeviceProjectAssignment.device_id, DeviceProjectAssignment.project_id).where(
                    DeviceProjectAssignment.device_id.in_(found),
                    DeviceProjectAssignment.validity.op("@>")(now),
                )
            )
        ).all()
    }
    return sorted(
        (
            ClockAheadDevice(
                device_id=device_id,
                name=names.get(device_id, str(device_id)),
                project_id=projects.get(device_id),
                positions=entry["positions"],
                measurements=entry["measurements"],
                until=entry["until"],
            )
            for device_id, entry in found.items()
        ),
        key=lambda d: d.name,
    )


@router.get("/clock-ahead", response_model=list[ClockAheadDevice])
async def clock_ahead_devices(
    session: AsyncSession = Depends(get_session),
) -> list[ClockAheadDevice]:
    """Devices whose records carry a device time ahead of the clock (decision D119)."""
    return await _clock_ahead_devices(session)


@router.get("/metrics", response_model=NewMetricsResponse)
async def new_metrics(session: AsyncSession = Depends(get_session)) -> NewMetricsResponse:
    """Metrics that registered themselves and wait for a label, unit and category (D102).
    Device counts and the last time come from the devices' current state, not the hypertable."""
    metrics = (
        await session.scalars(
            select(Metric).where(Metric.category == "uncategorized").order_by(Metric.key)
        )
    ).all()
    categories = sorted(
        {
            str(c)
            for c in (await session.scalars(select(Metric.category).distinct())).all()
            if c and c != "uncategorized"
        }
    )
    if not metrics:
        return NewMetricsResponse(items=[], categories=categories)
    keys = [m.key for m in metrics]
    states = (
        await session.scalars(
            select(DeviceCurrentState).where(
                DeviceCurrentState.latest_measurements.has_any(array(keys))
            )
        )
    ).all()
    devices: dict[str, int] = dict.fromkeys(keys, 0)
    last: dict[str, datetime | None] = dict.fromkeys(keys)
    sample: dict[str, Any] = {}
    for state in states:
        for key in keys:
            entry = (state.latest_measurements or {}).get(key)
            if not isinstance(entry, dict):
                continue
            devices[key] += 1
            when = datetime.fromisoformat(str(entry["time"])) if entry.get("time") else None
            newest = last[key]
            if when is not None and (newest is None or when > newest):
                last[key] = when
                sample[key] = entry.get("value")
    return NewMetricsResponse(
        items=[
            NewMetric(
                key=m.key,
                label=m.label,
                unit=m.unit,
                value_type=m.value_type,
                created_at=m.created_at,
                devices=devices[m.key],
                last_time=last[m.key],
                sample=sample.get(m.key),
            )
            for m in metrics
        ],
        categories=categories,
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
    await fill_serial_from_identity(session, device, identity)  # D101
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


async def _identities_for_bulk(
    session: AsyncSession, ids: list[uuid.UUID]
) -> tuple[list[ExternalIdentity], list[BulkSkipped]]:
    """The unlinked, not ignored identities among `ids`, and why the others are left out."""
    rows = (
        await session.scalars(select(ExternalIdentity).where(ExternalIdentity.id.in_(set(ids))))
    ).all()
    by_id = {r.id: r for r in rows}
    usable: list[ExternalIdentity] = []
    skipped: list[BulkSkipped] = []
    for identity_id in dict.fromkeys(ids):  # in the caller's order, once each
        identity = by_id.get(identity_id)
        if identity is None:
            skipped.append(BulkSkipped(identity_id=identity_id, reason="not found"))
        elif identity.device_id is not None:
            skipped.append(
                BulkSkipped(
                    identity_id=identity_id,
                    external_id=identity.external_id,
                    reason="already linked to a device",
                )
            )
        elif identity.ignored:
            skipped.append(
                BulkSkipped(
                    identity_id=identity_id, external_id=identity.external_id, reason="ignored"
                )
            )
        else:
            usable.append(identity)
    return usable, skipped


def _platform_name(identity: ExternalIdentity) -> str:
    """The name the platform knows the device by, else its external id."""
    name = str((identity.attributes or {}).get("name") or "").strip()
    return name[:200] if name else identity.external_id


@router.post(
    "/identities/bulk-create-devices",
    response_model=BulkCreateResult,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_devices(
    body: BulkCreateDevices,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> BulkCreateResult:
    """A shared network application posts every device it holds; this turns a selection of
    its unknown identities into devices in one go. A name already taken gets the external id
    appended; an entity name already taken in the project leaves that device without one."""
    await get_or_404(session, DeviceType, body.device_type_id, "Device type")
    if body.project_id is not None:
        await get_or_404(session, Project, body.project_id, "Project")
    if body.entity_type_id is not None:
        if body.project_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "An entity needs a project: set project_id"
            )
        await get_or_404(session, EntityType, body.entity_type_id, "Entity type")
    if body.group_id is not None:
        if body.entity_type_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A group needs entities: set entity_type_id"
            )
        group = await get_or_404(session, Group, body.group_id, "Group")
        if group.project_id != body.project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found in this project")
    identities, skipped = await _identities_for_bulk(session, body.identity_ids)
    wanted = {_platform_name(i) for i in identities} | {i.external_id for i in identities}
    taken_devices = set(
        (await session.scalars(select(Device.name).where(Device.name.in_(wanted)))).all()
    )
    taken_entities: set[str] = set()
    if body.entity_type_id is not None:
        taken_entities = set(
            (
                await session.scalars(
                    select(Entity.name).where(
                        Entity.project_id == body.project_id, Entity.name.in_(wanted)
                    )
                )
            ).all()
        )
    created: list[Device] = []
    linked: list[ExternalIdentity] = []
    entities = 0
    now = utc_now()
    for identity in identities:
        name = _platform_name(identity)
        if name in taken_devices:
            name = f"{name} {identity.external_id}"[:200]
        if name in taken_devices:
            skipped.append(
                BulkSkipped(
                    identity_id=identity.id,
                    external_id=identity.external_id,
                    reason=f"a device named {name!r} exists",
                )
            )
            continue
        taken_devices.add(name)
        device = Device(name=name, device_type_id=body.device_type_id, status=DeviceStatus.ACTIVE)
        session.add(device)
        await session.flush()
        identity.device_id = device.id
        await fill_serial_from_identity(session, device, identity)  # D101
        valid_from = identity.first_seen_at or now
        if body.project_id is not None:
            session.add(
                DeviceProjectAssignment(
                    device_id=device.id,
                    project_id=body.project_id,
                    validity=Range(valid_from, None, bounds="[)"),
                    reason="created from Needs Attention",
                    created_by_user_id=user.id,
                )
            )
            if body.entity_type_id is not None and name not in taken_entities:
                entity = Entity(
                    project_id=body.project_id,
                    entity_type_id=body.entity_type_id,
                    group_id=body.group_id,
                    name=name,
                )
                session.add(entity)
                await session.flush()
                session.add(
                    DeviceEntityAssignment(
                        device_id=device.id,
                        entity_id=entity.id,
                        validity=Range(valid_from, None, bounds="[)"),
                        reason="created from Needs Attention",
                        created_by_user_id=user.id,
                    )
                )
                taken_entities.add(name)
                entities += 1
        await record_audit(
            session,
            user=user,
            action="attention.device_created",
            object_type="external_identity",
            object_id=str(identity.id),
            project_id=body.project_id,
            details={
                "device_id": str(device.id),
                "external_id": identity.external_id,
                "bulk": True,
            },
        )
        created.append(device)
        linked.append(identity)
    await flush_or_409(session, "Bulk create")
    await session.commit()
    republished = 0
    if body.reprocess:
        for identity in linked:
            republished += await _reprocess_identity(session, bus, identity)
    return BulkCreateResult(
        created=len(created),
        entities=entities,
        republished=republished,
        device_ids=[d.id for d in created],
        skipped=skipped,
    )


@router.post("/identities/bulk-ignore", response_model=BulkIgnoreResult)
async def bulk_ignore_identities(
    body: BulkIdentityIds,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> BulkIgnoreResult:
    identities, skipped = await _identities_for_bulk(session, body.identity_ids)
    for identity in identities:
        identity.ignored = True
        await record_audit(
            session,
            user=user,
            action="attention.identity_ignored",
            object_type="external_identity",
            object_id=str(identity.id),
            details={"bulk": True},
        )
    await session.commit()
    return BulkIgnoreResult(ignored=len(identities), skipped=skipped)


@router.post("/identities/{identity_id}/link", response_model=ReprocessResult)
async def link_identity(
    identity_id: uuid.UUID,
    body: LinkIdentity,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ReprocessResult:
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    device = await get_or_404(session, Device, body.device_id, "Device")
    identity.device_id = body.device_id
    identity.ignored = False
    await fill_serial_from_identity(session, device, identity)  # D101
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
