"""Network section: LoRaWAN traffic (architecture 8.3), trace search (26.3) and system health
(26.2, basic). Traffic and traces are read per project; health is server admin."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.bus import get_bus
from protect_api.deps import ProjectContext, require_permission, require_server_admin
from shared.bus import RedisStreamsBus, Topic, is_stale
from shared.database import get_session
from shared.enums import ProcessingStatus, TraceStatus
from shared.models import (
    DataSource,
    Device,
    DeviceProjectAssignment,
    ExternalIdentity,
    GatewayReception,
    ProcessingTrace,
    SourceEvent,
    User,
)
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now

router = APIRouter(tags=["network"])

MAX_ROWS = 500
WORKERS = ("ingest", "decoder", "export", "rules", "automation", "integration")
GROUPS = {
    "decoder": Topic.SOURCE_EVENT_RECEIVED,
    "export": Topic.EXPORT_REQUESTED,
    "rules": Topic.POSITION_CREATED,
    "automation": Topic.EVENT_CREATED,
    "integration": Topic.POSITION_CREATED,
}


class ReceptionRead(BaseModel):
    gateway_id: str
    rssi: float | None
    snr: float | None
    frequency_hz: int | None
    channel: int | None


class TrafficRow(BaseModel):
    source_event_id: int
    ingested_at: datetime
    time: datetime | None
    device_id: uuid.UUID | None
    device_name: str | None
    external_id: str | None
    data_source_id: uuid.UUID
    data_source_name: str
    event_type: str
    f_port: int | None
    f_cnt: int | None
    spreading_factor: int | None
    frequency_hz: int | None
    gateway_count: int
    best_rssi: float | None
    best_snr: float | None
    processing_status: str
    error_code: str | None
    trace_id: uuid.UUID | None
    payload: dict[str, Any] | None
    receptions: list[ReceptionRead]


class TraceSummary(BaseModel):
    id: uuid.UUID
    root_object_type: str
    root_object_id: str
    status: str
    trace_class: str
    started_at: datetime
    completed_at: datetime | None
    device_id: uuid.UUID | None
    data_source_id: uuid.UUID | None
    error_code: str | None


class WorkerHealth(BaseModel):
    name: str
    last_heartbeat: datetime | None
    stale: bool
    lag: int | None = None
    dead_letters: int | None = None


class SourceHealth(BaseModel):
    id: uuid.UUID
    name: str
    adapter_key: str
    enabled: bool
    events_last_hour: int
    last_event_at: datetime | None


class SystemHealth(BaseModel):
    status: str
    workers: list[WorkerHealth]
    events_per_minute: float
    failed_last_hour: int
    unassigned_last_hour: int
    unknown_identities: int
    dead_letters: dict[str, int]
    data_sources: list[SourceHealth]


async def _project_device_ids(
    session: AsyncSession, project_id: uuid.UUID, at_from: datetime, at_to: datetime
) -> list[uuid.UUID]:
    """Devices that were assigned to the project at any time in the window."""
    from sqlalchemy.dialects.postgresql import Range

    rows = await session.scalars(
        select(DeviceProjectAssignment.device_id).where(
            DeviceProjectAssignment.project_id == project_id,
            DeviceProjectAssignment.validity.op("&&")(Range(at_from, at_to, bounds="[)")),
        )
    )
    return list(set(rows))


@router.get("/projects/{project_id}/traffic", response_model=list[TrafficRow])
async def traffic(
    device_id: uuid.UUID | None = None,
    event_type: str | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=MAX_ROWS),
    include_payload: bool = False,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[TrafficRow]:
    """Source events of the project's devices, newest first. Default window: last 24 hours."""
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    device_ids = await _project_device_ids(session, context.project.id, time_from, time_to)
    if device_id is not None:
        device_ids = [d for d in device_ids if d == device_id]
    if not device_ids:
        return []
    statement = (
        select(SourceEvent, Device.name, DataSource.name)
        .join(Device, Device.id == SourceEvent.device_id)
        .join(DataSource, DataSource.id == SourceEvent.data_source_id)
        .where(
            SourceEvent.device_id.in_(device_ids),
            SourceEvent.ingested_at >= time_from,
            SourceEvent.ingested_at < time_to,
        )
    )
    if event_type is not None:
        statement = statement.where(SourceEvent.event_type == event_type)
    rows = (
        await session.execute(statement.order_by(SourceEvent.ingested_at.desc()).limit(limit))
    ).all()
    event_ids = [r[0].id for r in rows]
    receptions: dict[int, list[GatewayReception]] = {}
    if event_ids:
        for reception in await session.scalars(
            select(GatewayReception).where(GatewayReception.source_event_id.in_(event_ids))
        ):
            receptions.setdefault(reception.source_event_id or 0, []).append(reception)
    result = []
    for event, device_name, source_name in rows:
        meta = event.provider_metadata or {}
        result.append(
            TrafficRow(
                source_event_id=event.id,
                ingested_at=event.ingested_at,
                time=event.network_received_at,
                device_id=event.device_id,
                device_name=device_name,
                external_id=event.external_id,
                data_source_id=event.data_source_id,
                data_source_name=source_name,
                event_type=event.event_type,
                f_port=meta.get("f_port"),
                f_cnt=meta.get("f_cnt"),
                spreading_factor=meta.get("spreading_factor"),
                frequency_hz=meta.get("frequency_hz"),
                gateway_count=int(meta.get("gateway_count") or len(receptions.get(event.id, []))),
                best_rssi=meta.get("best_rssi"),
                best_snr=meta.get("best_snr"),
                processing_status=event.processing_status,
                error_code=event.error_code,
                trace_id=event.trace_id,
                payload=event.payload if include_payload else None,
                receptions=[
                    ReceptionRead(
                        gateway_id=r.gateway_id,
                        rssi=r.rssi,
                        snr=r.snr,
                        frequency_hz=r.frequency_hz,
                        channel=r.channel,
                    )
                    for r in receptions.get(event.id, [])
                ],
            )
        )
    return result


@router.get("/projects/{project_id}/traces", response_model=list[TraceSummary])
async def search_traces(
    device_id: uuid.UUID | None = None,
    data_source_id: uuid.UUID | None = None,
    external_id: str | None = None,
    status_filter: TraceStatus | None = Query(None, alias="status"),
    error_code: str | None = None,
    root_object_type: str | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=MAX_ROWS),
    context: ProjectContext = Depends(require_permission(Permission.TRACES_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[TraceSummary]:
    """Traces of the project's devices, or attributed to the project, newest first."""
    from shared.models import ApplicationError as ApplicationErrorRow

    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    device_ids = await _project_device_ids(session, context.project.id, time_from, time_to)
    if external_id is not None:
        identity_devices = list(
            await session.scalars(
                select(ExternalIdentity.device_id).where(
                    ExternalIdentity.external_id == external_id
                )
            )
        )
        device_ids = [d for d in device_ids if d in identity_devices]
    if device_id is not None:
        device_ids = [d for d in device_ids if d == device_id]
    statement = (
        select(ProcessingTrace, ApplicationErrorRow.error_code)
        .outerjoin(ApplicationErrorRow, ApplicationErrorRow.id == ProcessingTrace.error_id)
        .where(ProcessingTrace.started_at >= time_from, ProcessingTrace.started_at < time_to)
    )
    if device_ids or device_id is not None or external_id is not None:
        statement = statement.where(ProcessingTrace.device_id.in_(device_ids))
    else:
        statement = statement.where(ProcessingTrace.project_id == context.project.id)
    if data_source_id is not None:
        statement = statement.where(ProcessingTrace.data_source_id == data_source_id)
    if status_filter is not None:
        statement = statement.where(ProcessingTrace.status == status_filter)
    if root_object_type is not None:
        statement = statement.where(ProcessingTrace.root_object_type == root_object_type)
    if error_code is not None:
        statement = statement.where(ApplicationErrorRow.error_code == error_code)
    rows = (
        await session.execute(statement.order_by(ProcessingTrace.started_at.desc()).limit(limit))
    ).all()
    return [
        TraceSummary(
            id=t.id,
            root_object_type=t.root_object_type,
            root_object_id=t.root_object_id,
            status=t.status,
            trace_class=t.trace_class,
            started_at=t.started_at,
            completed_at=t.completed_at,
            device_id=t.device_id,
            data_source_id=t.data_source_id,
            error_code=code,
        )
        for t, code in rows
    ]


@router.get("/system/health", response_model=SystemHealth)
async def system_health(
    _: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> SystemHealth:
    """Pipeline health for administrators: workers, throughput, failures, sources."""
    now = utc_now()
    hour_ago = now - timedelta(hours=1)
    heartbeats = await bus.heartbeats()
    dead = {
        topic: await bus.dead_count(topic)
        for topic in (
            Topic.SOURCE_EVENT_RECEIVED,
            Topic.POSITION_CREATED,
            Topic.MEASUREMENT_CREATED,
            Topic.DEVICE_STATE_CHANGED,
            Topic.EVENT_CREATED,
            Topic.NEEDS_ATTENTION_CREATED,
        )
    }
    workers = []
    for name in WORKERS:
        stamp = heartbeats.get(name)
        topic = GROUPS.get(name)
        workers.append(
            WorkerHealth(
                name=name,
                last_heartbeat=stamp,
                stale=is_stale(stamp),
                lag=await bus.lag(topic, name) if topic else None,
                dead_letters=dead.get(topic) if topic else None,
            )
        )
    events_last_hour = (
        await session.scalar(
            select(func.count()).select_from(SourceEvent).where(SourceEvent.ingested_at >= hour_ago)
        )
        or 0
    )
    failed = (
        await session.scalar(
            select(func.count())
            .select_from(SourceEvent)
            .where(
                SourceEvent.ingested_at >= hour_ago,
                SourceEvent.processing_status == ProcessingStatus.FAILED,
            )
        )
        or 0
    )
    unassigned = (
        await session.scalar(
            select(func.count())
            .select_from(SourceEvent)
            .where(
                SourceEvent.ingested_at >= hour_ago,
                SourceEvent.processing_status == ProcessingStatus.UNASSIGNED,
            )
        )
        or 0
    )
    unknown = (
        await session.scalar(
            select(func.count())
            .select_from(ExternalIdentity)
            .where(ExternalIdentity.device_id.is_(None), ExternalIdentity.ignored.is_(False))
        )
        or 0
    )
    sources = []
    for source in await session.scalars(select(DataSource).order_by(DataSource.name)):
        count = (
            await session.scalar(
                select(func.count())
                .select_from(SourceEvent)
                .where(SourceEvent.data_source_id == source.id, SourceEvent.ingested_at >= hour_ago)
            )
            or 0
        )
        last = await session.scalar(
            select(func.max(SourceEvent.ingested_at)).where(SourceEvent.data_source_id == source.id)
        )
        sources.append(
            SourceHealth(
                id=source.id,
                name=source.name,
                adapter_key=source.adapter_key,
                enabled=source.enabled,
                events_last_hour=int(count),
                last_event_at=last,
            )
        )
    degraded = any(w.stale for w in workers) or any(dead.values())
    return SystemHealth(
        status="degraded" if degraded else "ok",
        workers=workers,
        events_per_minute=round(int(events_last_hour) / 60, 2),
        failed_last_hour=int(failed),
        unassigned_last_hour=int(unassigned),
        unknown_identities=int(unknown),
        dead_letters={k: v for k, v in dead.items() if v},
        data_sources=sources,
    )
