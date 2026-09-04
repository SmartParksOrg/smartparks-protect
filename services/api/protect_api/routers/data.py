"""Read access to canonical data, source events and traces. Enough for the phase 2 exit criteria;
the map, traffic viewer and trace explorer APIs of phase 3 build on these."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.auth.users import current_active_user
from protect_api.crud import geom_to_geojson
from protect_api.deps import ProjectContext, accessible_project_ids, require_permission
from shared.database import get_session
from shared.models import ApplicationError as ApplicationErrorRow
from shared.models import (
    Position,
    ProcessingStep,
    ProcessingTrace,
    SourceDelivery,
    SourceEvent,
    User,
)
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now

router = APIRouter(tags=["data"])

MAX_POSITIONS = 1000


class PositionRead(BaseModel):
    id: int
    time: datetime
    ingested_at: datetime
    device_id: uuid.UUID
    project_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    data_source_id: uuid.UUID | None
    source_event_id: int | None
    record_type: str
    geometry: dict[str, Any] | None
    altitude_m: float | None
    speed_mps: float | None
    heading_deg: float | None
    accuracy_m: float | None
    satellites: int | None
    attributes: dict[str, Any]
    trace_id: uuid.UUID | None


class DeliveryRead(BaseModel):
    canonical_type: str
    canonical_id: int
    canonical_time: datetime
    source_event_id: int
    source_event_ingested_at: datetime
    acquisition_channel: str
    first: bool


class DeliveryDetail(BaseModel):
    """One delivery of a canonical record with the source event that carried it (architecture
    25.2 and 25.7): which channel, which platform, when it arrived."""

    source_event_id: int
    source_event_ingested_at: datetime
    acquisition_channel: str
    ingestion_method: str
    data_source_id: uuid.UUID
    data_source_name: str | None
    event_type: str
    processing_status: str
    first: bool
    network_received_at: datetime | None
    satellite_delivered_at: datetime | None
    ble_synced_at: datetime | None
    file_uploaded_at: datetime | None
    trace_id: uuid.UUID | None


class SourceEventRead(BaseModel):
    id: int
    ingested_at: datetime
    data_source_id: uuid.UUID
    external_id: str | None
    external_identity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    event_type: str
    acquisition_channel: str
    ingestion_method: str
    processing_status: str
    payload: dict[str, Any] | None
    payload_object_key: str | None
    payload_size: int | None
    provider_metadata: dict[str, Any]
    network_received_at: datetime | None
    satellite_delivered_at: datetime | None
    ble_synced_at: datetime | None
    file_uploaded_at: datetime | None
    trace_id: uuid.UUID | None
    error_code: str | None
    deliveries: list[DeliveryRead]
    links: list[dict[str, str]] = []
    data_source_name: str | None = None


class StepRead(BaseModel):
    sequence: int
    component: str
    operation: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    input_ref: str | None
    output_ref: str | None
    retry_count: int
    metadata: dict[str, Any]
    error: dict[str, Any] | None


class TraceRead(BaseModel):
    id: uuid.UUID
    root_object_type: str
    root_object_id: str
    status: str
    trace_class: str
    compact: bool
    started_at: datetime
    completed_at: datetime | None
    project_id: uuid.UUID | None
    device_id: uuid.UUID | None
    data_source_id: uuid.UUID | None
    error: dict[str, Any] | None
    steps: list[StepRead]


def position_read(position: Position) -> PositionRead:
    return PositionRead(
        id=position.id,
        time=position.time,
        ingested_at=position.ingested_at,
        device_id=position.device_id,
        project_id=position.project_id,
        entity_id=position.entity_id,
        data_source_id=position.data_source_id,
        source_event_id=position.source_event_id,
        record_type=position.record_type,
        geometry=geom_to_geojson(position.geom),
        altitude_m=position.altitude_m,
        speed_mps=position.speed_mps,
        heading_deg=position.heading_deg,
        accuracy_m=position.accuracy_m,
        satellites=position.satellites,
        attributes=position.attributes,
        trace_id=position.trace_id,
    )


@router.get("/projects/{project_id}/positions", response_model=list[PositionRead])
async def list_positions(
    device_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=MAX_POSITIONS),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[PositionRead]:
    """Positions attributed to the project, newest first, within a time window (default the last
    24 hours) and a row limit."""
    time_to = require_aware(time_to) if time_to else utc_now()
    time_from = require_aware(time_from) if time_from else time_to - timedelta(hours=24)
    statement = select(Position).where(
        Position.project_id == context.project.id,
        Position.time >= time_from,
        Position.time < time_to,
    )
    if device_id is not None:
        statement = statement.where(Position.device_id == device_id)
    if entity_id is not None:
        statement = statement.where(Position.entity_id == entity_id)
    rows = await session.scalars(statement.order_by(Position.time.desc()).limit(limit))
    return [position_read(r) for r in rows]


async def _device_visible(session: AsyncSession, user: User, device_id: uuid.UUID | None) -> bool:
    if user.is_superuser:
        return True
    if device_id is None:
        return False
    from shared.models import DeviceProjectAssignment

    projects = await accessible_project_ids(user, session) or []
    row = await session.scalar(
        select(DeviceProjectAssignment.id)
        .where(
            DeviceProjectAssignment.device_id == device_id,
            DeviceProjectAssignment.project_id.in_(projects),
        )
        .limit(1)
    )
    return row is not None


@router.get("/source-events/{source_event_id}", response_model=SourceEventRead)
async def get_source_event(
    source_event_id: int,
    ingested_at: datetime,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SourceEventRead:
    """A raw source event with every canonical row it delivered. Visible to server admins and to
    members of a project the device was assigned to."""
    event = await session.scalar(
        select(SourceEvent).where(
            SourceEvent.id == source_event_id, SourceEvent.ingested_at == require_aware(ingested_at)
        )
    )
    if event is None or not await _device_visible(session, user, event.device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source event not found")
    deliveries = (
        await session.scalars(
            select(SourceDelivery)
            .where(SourceDelivery.source_event_id == event.id)
            .order_by(SourceDelivery.id)
        )
    ).all()
    from shared.domain.links import resolve_links
    from shared.models import DataSource, ExternalIdentity

    source = await session.get(DataSource, event.data_source_id)
    identity = (
        await session.get(ExternalIdentity, event.external_identity_id)
        if event.external_identity_id
        else None
    )
    skip = {"deliveries", "links", "data_source_name"}
    return SourceEventRead(
        **{c: getattr(event, c) for c in SourceEventRead.model_fields if c not in skip},
        deliveries=[DeliveryRead.model_validate(d, from_attributes=True) for d in deliveries],
        links=resolve_links(source, identity) if source else [],
        data_source_name=source.name if source else None,
    )


@router.get("/deliveries", response_model=list[DeliveryDetail])
async def list_deliveries(
    canonical_type: str = Query(pattern="^(position|measurement|state|event)$"),
    canonical_id: int = Query(ge=1),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[DeliveryDetail]:
    """Every delivery of one canonical record, oldest first: the delivery that created it and
    every repeat over another path (architecture 25.7)."""
    from shared.models import DataSource

    rows = (
        await session.execute(
            select(SourceDelivery, SourceEvent)
            .join(
                SourceEvent,
                (SourceEvent.id == SourceDelivery.source_event_id)
                & (SourceEvent.ingested_at == SourceDelivery.source_event_ingested_at),
            )
            .where(
                SourceDelivery.canonical_type == canonical_type,
                SourceDelivery.canonical_id == canonical_id,
            )
            .order_by(SourceDelivery.id)
        )
    ).all()
    if not rows:
        return []
    if not await _device_visible(session, user, rows[0][1].device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    sources = {
        s.id: s.name
        for s in (
            await session.scalars(
                select(DataSource).where(
                    DataSource.id.in_({event.data_source_id for _, event in rows})
                )
            )
        ).all()
    }
    return [
        DeliveryDetail(
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            acquisition_channel=event.acquisition_channel,
            ingestion_method=event.ingestion_method,
            data_source_id=event.data_source_id,
            data_source_name=sources.get(event.data_source_id),
            event_type=event.event_type,
            processing_status=event.processing_status,
            first=delivery.first,
            network_received_at=event.network_received_at,
            satellite_delivered_at=event.satellite_delivered_at,
            ble_synced_at=event.ble_synced_at,
            file_uploaded_at=event.file_uploaded_at,
            trace_id=event.trace_id,
        )
        for delivery, event in rows
    ]


async def _error_dict(session: AsyncSession, error_id: int | None) -> dict[str, Any] | None:
    if error_id is None:
        return None
    row = await session.get(ApplicationErrorRow, error_id)
    if row is None:
        return None
    return {
        "error_code": row.error_code,
        "severity": row.severity,
        "retryable": row.retryable,
        "user_actionable": row.user_actionable,
        "component": row.component,
        "message": row.message,
        "technical_context": row.technical_context,
    }


@router.get("/traces/{trace_id}", response_model=TraceRead)
async def get_trace(
    trace_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> TraceRead:
    trace = await session.get(ProcessingTrace, trace_id)
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found")
    if not user.is_superuser:
        projects = await accessible_project_ids(user, session) or []
        allowed = trace.project_id in projects or await _device_visible(
            session, user, trace.device_id
        )
        if not allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found")
    steps: list[StepRead] = []
    if trace.compact and trace.compact_steps:
        steps = [
            StepRead(
                sequence=s["sequence"],
                component=s["component"],
                operation=s["operation"],
                status=s["status"],
                started_at=None,
                completed_at=None,
                duration_ms=s.get("duration_ms"),
                input_ref=None,
                output_ref=s.get("output_ref"),
                retry_count=0,
                metadata={},
                error=None,
            )
            for s in trace.compact_steps
        ]
    rows = (
        await session.scalars(
            select(ProcessingStep)
            .where(ProcessingStep.trace_id == trace.id)
            .order_by(ProcessingStep.sequence)
        )
    ).all()
    for row in rows:
        steps.append(
            StepRead(
                sequence=row.sequence,
                component=row.component,
                operation=row.operation,
                status=row.status,
                started_at=row.started_at,
                completed_at=row.completed_at,
                duration_ms=row.duration_ms,
                input_ref=row.input_ref,
                output_ref=row.output_ref,
                retry_count=row.retry_count,
                metadata=row.metadata_,
                error=await _error_dict(session, row.error_id),
            )
        )
    steps.sort(key=lambda s: s.sequence)
    return TraceRead(
        id=trace.id,
        root_object_type=trace.root_object_type,
        root_object_id=trace.root_object_id,
        status=trace.status,
        trace_class=trace.trace_class,
        compact=trace.compact,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        project_id=trace.project_id,
        device_id=trace.device_id,
        data_source_id=trace.data_source_id,
        error=await _error_dict(session, trace.error_id),
        steps=steps,
    )
