"""Network section: LoRaWAN traffic (architecture 8.3), trace search (26.3) and system health
(26.2, basic). Traffic and traces are read per project; `/system/health` is server admin,
`/system/status` (the health dot, decision D181) is any signed-in account."""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.deps import (
    ProjectContext,
    ScopeContext,
    require_permission,
    require_scope_permission,
    require_server_admin,
)
from protect_api.health_areas import AreaHealth, area_health
from shared.bus import RedisStreamsBus, Topic, is_stale
from shared.config import get_settings
from shared.connectivity.satellite import SatelliteSession
from shared.database import get_session
from shared.device_drivers.base import lorawan_frame, raw_frame
from shared.enums import AcquisitionChannel, AlertStatus, ProcessingStatus, TraceStatus
from shared.models import (
    Alert,
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


class SatelliteSessionRead(BaseModel):
    """The Iridium session behind a satellite delivery (decision D158)."""

    status: str
    status_text: str
    status_code: int | None = None
    sequence: int | None = Field(default=None, description="MOMSN, the modem's session counter")
    mt_sequence: int | None = Field(
        default=None, description="MTMSN of the message delivered to the modem in the session"
    )
    latitude: float | None = None
    longitude: float | None = None
    cep_km: float | None = Field(default=None, description="Circular error probable, km")
    bytes: int = 0
    session_at: datetime | None = None
    missed_since_last: int | None = Field(
        default=None, description="Sessions the counter skipped since the identity's last one"
    )
    duplicate_of: int | None = Field(
        default=None, description="The earlier source event this delivery repeated"
    )


def satellite_read(meta: dict[str, Any]) -> SatelliteSessionRead | None:
    data = meta.get("satellite_session")
    if not isinstance(data, dict):
        return None
    parsed = SatelliteSession.from_dict(data)
    if parsed is None:
        return None
    return SatelliteSessionRead(
        status=parsed.status,
        status_text=parsed.status_text,
        status_code=parsed.status_code,
        sequence=parsed.sequence,
        mt_sequence=parsed.mt_sequence,
        latitude=parsed.latitude,
        longitude=parsed.longitude,
        cep_km=parsed.cep_km,
        bytes=parsed.bytes,
        session_at=parsed.session_at,
        missed_since_last=data.get("missed_since_last"),
        duplicate_of=data.get("duplicate_of"),
    )


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
    acquisition_channel: str = Field(
        default="lorawan", description="lorawan, webble, log_file, iridium, cellular or api"
    )
    ingestion_method: str = Field(default="webhook")
    frame_bytes: int | None = Field(default=None, description="Length of the device frame")
    delivered_at: datetime | None = Field(
        default=None,
        description="When the delivery left the device's path: synced over Bluetooth, "
        "uploaded as a file or delivered by the satellite service",
    )
    log_file_id: uuid.UUID | None = Field(
        default=None, description="The raw log file or browser sync this frame came from"
    )
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
    satellite: SatelliteSessionRead | None = Field(
        default=None, description="The Iridium session of a satellite delivery"
    )


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
    areas: list[AreaHealth] = Field(default_factory=list)
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


async def _scope_device_ids(
    session: AsyncSession, context: ScopeContext, at_from: datetime, at_to: datetime
) -> list[uuid.UUID]:
    """Devices assigned to the scope's project at any time in the window (decision D115); in
    the all scope every device, the ones in no project during the window included, since a
    server admin sees unassigned data there (decision D120)."""
    from sqlalchemy.dialects.postgresql import Range

    window = Range(at_from, at_to, bounds="[)")
    rows = await session.scalars(
        select(DeviceProjectAssignment.device_id).where(
            context.where(DeviceProjectAssignment.project_id),
            DeviceProjectAssignment.validity.op("&&")(window),
        )
    )
    ids = set(rows)
    if context.is_all:
        assigned = select(DeviceProjectAssignment.device_id).where(
            DeviceProjectAssignment.validity.op("&&")(window)
        )
        ids |= set(await session.scalars(select(Device.id).where(Device.id.not_in(assigned))))
    return list(ids)


@router.get("/projects/{project_id}/traffic", response_model=list[TrafficRow])
async def traffic(
    device_id: uuid.UUID | None = None,
    event_type: str | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=MAX_ROWS),
    include_payload: bool = False,
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[TrafficRow]:
    """Source events of the project's devices, newest first. Default window: last 24 hours."""
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    device_ids = await _scope_device_ids(session, context, time_from, time_to)
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
    return await traffic_rows(session, rows, include_payload)


@router.get("/data-sources/{data_source_id}/traffic", response_model=list[TrafficRow])
async def data_source_traffic(
    data_source_id: uuid.UUID,
    external_id: str | None = None,
    event_type: str | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=MAX_ROWS),
    include_payload: bool = False,
    _: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> list[TrafficRow]:
    """Everything one data source received, newest first, linked to a device or not: what an
    administrator watches while connecting a platform, before any device exists."""
    source = await session.get(DataSource, data_source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data source not found")
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    statement = (
        select(SourceEvent, Device.name, DataSource.name)
        .outerjoin(Device, Device.id == SourceEvent.device_id)
        .join(DataSource, DataSource.id == SourceEvent.data_source_id)
        .where(
            SourceEvent.data_source_id == data_source_id,
            SourceEvent.ingested_at >= time_from,
            SourceEvent.ingested_at < time_to,
        )
    )
    if event_type is not None:
        statement = statement.where(SourceEvent.event_type == event_type)
    if external_id:
        statement = statement.where(SourceEvent.external_id.ilike(f"%{external_id}%"))
    rows = (
        await session.execute(statement.order_by(SourceEvent.ingested_at.desc()).limit(limit))
    ).all()
    return await traffic_rows(session, rows, include_payload)


async def traffic_rows(
    session: AsyncSession, rows: Sequence[Any], include_payload: bool
) -> list[TrafficRow]:
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
        frame: bytes | None = None
        if event.payload is not None:
            if event.acquisition_channel == AcquisitionChannel.LORAWAN:
                frame, _port = lorawan_frame(event.payload, meta)
            else:
                frame = raw_frame(event.payload, meta)
        log_file_id = meta.get("log_file_id")
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
                acquisition_channel=event.acquisition_channel,
                ingestion_method=event.ingestion_method,
                frame_bytes=len(frame) if frame is not None else None,
                delivered_at=event.ble_synced_at
                or event.file_uploaded_at
                or event.satellite_delivered_at,
                log_file_id=uuid.UUID(str(log_file_id)) if log_file_id else None,
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
                satellite=satellite_read(meta),
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


class SystemStatus(BaseModel):
    """What the health dot shows every signed-in account (decision D181): green while every
    worker reported within the stale window and no system alert is open; amber once a worker
    has been silent past the window or a system alert has stayed open over 30 minutes."""

    level: str  # ok | degraded
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime


SYSTEM_ALERT_GRACE = timedelta(minutes=30)


@router.get("/system/status", response_model=SystemStatus)
async def system_status(
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> SystemStatus:
    """The health dot's summary, deliberately slow to worry (decision D181)."""
    now = utc_now()
    heartbeats = await bus.heartbeats()
    reasons = [
        f"the {name} worker has not reported for over "
        f"{get_settings().heartbeat_stale_minutes} minutes"
        for name in WORKERS
        if is_stale(heartbeats.get(name), now)
    ]
    lingering = (
        await session.scalar(
            select(func.count())
            .select_from(Alert)
            .where(
                Alert.project_id.is_(None),
                Alert.status == AlertStatus.OPEN,
                Alert.created_at <= now - SYSTEM_ALERT_GRACE,
            )
        )
        or 0
    )
    if lingering:
        reasons.append(
            f"{lingering} system alert{'s' if lingering != 1 else ''} open for over 30 minutes"
        )
    return SystemStatus(level="degraded" if reasons else "ok", reasons=reasons, checked_at=now)


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
    areas = await area_health(session)
    degraded = (
        any(w.stale for w in workers)
        or any(dead.values())
        or any(a.status == "critical" for a in areas)
    )
    return SystemHealth(
        status="degraded" if degraded else "ok",
        workers=workers,
        areas=areas,
        events_per_minute=round(int(events_last_hour) / 60, 2),
        failed_last_hour=int(failed),
        unassigned_last_hour=int(unassigned),
        unknown_identities=int(unknown),
        dead_letters={k: v for k, v in dead.items() if v},
        data_sources=sources,
    )
