"""Delivery rows: filters, idempotent enqueue, loading the object, one attempt with the retry
schedule, and backfill over a date range (decisions D60 and D61).

Shared by the integration service (live path, backfill, retries) and the API (manual retry,
test sends), so both write the same rows the same way.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.enums import (
    BackfillStatus,
    DeliveryOrigin,
    DeliveryStatus,
    ErrorCode,
    IntegrationObjectType,
    Severity,
    TraceClass,
    TraceStatus,
)
from shared.integrations.base import (
    DeliveryItem,
    IntegrationContext,
    OutboundConnector,
    PermanentFailure,
    Skipped,
    TransientFailure,
)
from shared.integrations.registry import CONNECTORS
from shared.logger import get_logger
from shared.models import (
    DataSource,
    Device,
    Entity,
    EntityCurrentState,
    EntityType,
    Event,
    Integration,
    IntegrationDelivery,
    Measurement,
    Position,
    Project,
)
from shared.secrets import decrypt_json
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("integrations")

BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 6 * 3600
MAX_ATTEMPTS = 30
BACKFILL_BATCH = 1000
SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


def backoff_seconds(attempts: int) -> int:
    """30 s, 60 s, 2 min, ... capped at six hours; 30 attempts span about three days."""
    return int(min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** max(0, attempts - 1)))


def integration_context(integration: Integration) -> IntegrationContext:
    credentials = (
        decrypt_json(integration.credentials_encrypted) if integration.credentials_encrypted else {}
    )
    return IntegrationContext(
        id=integration.id,
        project_id=integration.project_id,
        name=integration.name,
        connector_key=integration.connector_key,
        config=dict(integration.config or {}),
        credentials=credentials,
    )


@dataclass(slots=True)
class ObjectRef:
    """What the filters see: the canonical object's identity and the attributes filters use."""

    object_type: str
    object_id: str
    time: datetime
    project_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    event_type: str | None = None
    severity: str | None = None
    metric_key: str | None = None
    object_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


def matches(integration: Integration, ref: ObjectRef) -> bool:
    if ref.object_type not in (integration.object_types or []):
        return False
    connector = CONNECTORS.get(integration.connector_key)
    if connector is None or ref.object_type not in connector.supports:
        return False
    if integration.entity_ids and str(ref.entity_id) not in integration.entity_ids:
        return False
    if integration.device_ids and str(ref.device_id) not in integration.device_ids:
        return False
    if ref.object_type == IntegrationObjectType.EVENT:
        if integration.event_types and ref.event_type not in integration.event_types:
            return False
        minimum = SEVERITY_RANK.get(Severity(integration.min_severity), 0)
        if SEVERITY_RANK.get(Severity(ref.severity or "info"), 0) < minimum:
            return False
    return not (
        ref.object_type == IntegrationObjectType.MEASUREMENT
        and integration.metric_keys
        and ref.metric_key not in integration.metric_keys
    )


def is_stale(integration: Integration, ref: ObjectRef, now: datetime) -> bool:
    return (now - ref.time).total_seconds() > integration.max_object_age_seconds


async def enqueue(
    session: AsyncSession,
    integrations: list[Integration],
    refs: list[ObjectRef],
    *,
    origin: DeliveryOrigin = DeliveryOrigin.LIVE,
    now: datetime | None = None,
    honour_age: bool = True,
) -> int:
    """Insert one queued row per (integration, object) that matches; existing keys are left
    alone (idempotent, D60). Stale live objects are not queued; a stale event is recorded as
    skipped so the log explains why nothing reached the target."""
    now = now or utc_now()
    rows: list[dict[str, Any]] = []
    for integration in integrations:
        for ref in refs:
            if ref.project_id != integration.project_id or not matches(integration, ref):
                continue
            row = {
                "integration_id": integration.id,
                "project_id": ref.project_id,
                "object_type": ref.object_type,
                "object_id": ref.object_id,
                "object_version": ref.object_version,
                "object_time": ref.time,
                "entity_id": ref.entity_id,
                "device_id": ref.device_id,
                "origin": origin,
                "status": DeliveryStatus.QUEUED,
                "next_attempt_at": now,
            }
            if honour_age and is_stale(integration, ref, now):
                if ref.object_type != IntegrationObjectType.EVENT:
                    continue
                row.update(
                    status=DeliveryStatus.SKIPPED,
                    next_attempt_at=None,
                    error_message=(
                        f"older than the integration's freshness bound of "
                        f"{integration.max_object_age_seconds} s"
                    ),
                )
            rows.append(row)
    if not rows:
        return 0
    result = await session.execute(
        insert(IntegrationDelivery)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_integration_deliveries_object")
    )
    return int(getattr(result, "rowcount", 0) or 0)


def _point(geom: Any) -> tuple[float, float] | None:
    if geom is None:
        return None
    shape = to_shape(geom)
    return (shape.y, shape.x)


async def load_item(session: AsyncSession, delivery: IntegrationDelivery) -> DeliveryItem | None:
    """The object with its names, or None when the object no longer exists."""
    project = await session.get(Project, delivery.project_id)
    if project is None:
        return None
    item = DeliveryItem(
        object_type=delivery.object_type,
        object_id=delivery.object_id,
        object_version=delivery.object_version,
        time=delivery.object_time,
        project_id=project.id,
        project_name=project.name,
        project_slug=project.slug,
    )
    device_id = delivery.device_id
    entity_id = delivery.entity_id
    data_source_id: uuid.UUID | None = None
    base_url = get_settings().public_url.rstrip("/")
    if delivery.object_type == IntegrationObjectType.POSITION:
        position = await session.scalar(
            select(Position).where(
                Position.id == int(delivery.object_id), Position.time == delivery.object_time
            )
        )
        if position is None:
            return None
        device_id, entity_id, data_source_id = (
            position.device_id,
            position.entity_id,
            position.data_source_id,
        )
        item.location = _point(position.geom)
        item.data = {
            "record_type": position.record_type,
            "altitude_m": position.altitude_m,
            "speed_mps": position.speed_mps,
            "heading_deg": position.heading_deg,
            "accuracy_m": position.accuracy_m,
            "satellites": position.satellites,
            "attributes": position.attributes,
        }
    elif delivery.object_type == IntegrationObjectType.EVENT:
        event = await session.get(Event, uuid.UUID(delivery.object_id))
        if event is None:
            return None
        device_id, entity_id = event.device_id, event.entity_id
        item.location = _point(event.geom)
        item.data = {
            "event_type": event.event_type,
            "severity": event.severity,
            "title": event.title,
            "description": event.description,
            "context": event.context,
        }
        item.link = f"{base_url}/projects/{project.id}/rules/events?event={event.id}"
    elif delivery.object_type == IntegrationObjectType.MEASUREMENT:
        measurement = await session.scalar(
            select(Measurement).where(
                Measurement.id == int(delivery.object_id),
                Measurement.time == delivery.object_time,
            )
        )
        if measurement is None:
            return None
        device_id, entity_id, data_source_id = (
            measurement.device_id,
            measurement.entity_id,
            measurement.data_source_id,
        )
        value: Any = measurement.value_num
        if value is None:
            value = measurement.value_bool
        if value is None:
            value = measurement.value_text
        if value is None:
            value = measurement.value_json
        item.data = {"metric_key": measurement.metric_key, "value": value}
    if entity_id is not None:
        row = (
            await session.execute(
                select(Entity, EntityType)
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(Entity.id == entity_id)
            )
        ).first()
        if row is not None:
            entity, entity_type = row
            item.entity_id = entity.id
            item.entity_name = entity.name
            item.entity_type_key = entity_type.key
            item.entity_type_label = entity_type.label
        if item.location is None and delivery.object_type == IntegrationObjectType.EVENT:
            current = await session.get(EntityCurrentState, entity_id)
            if current is not None and current.latest_position is not None:
                item.location = _point(current.latest_position)
                item.location_is_fallback = True
    if device_id is not None:
        device = await session.get(Device, device_id)
        if device is not None:
            item.device_id = device.id
            item.device_name = device.name
            item.device_serial = device.serial_number
            if item.link is None:
                item.link = f"{base_url}/projects/{project.id}/devices/{device.id}"
    if data_source_id is not None:
        item.data_source_name = await session.scalar(
            select(DataSource.name).where(DataSource.id == data_source_id)
        )
    return item


async def _record_failure(tracer: Tracer, error: ApplicationError) -> None:
    """A failed step closes the trace as failed; the tracer records errors raised in a step."""
    try:
        async with tracer.step("integration", "delivery failed"):
            raise error
    except ApplicationError:
        pass


async def attempt(
    session: AsyncSession,
    delivery: IntegrationDelivery,
    integration: Integration,
    *,
    now: datetime | None = None,
    connector: OutboundConnector | None = None,
) -> str:
    """One delivery attempt. Updates the row and the integration's status fields; the caller
    commits. Returns the resulting status."""
    now = now or utc_now()
    connector = connector or CONNECTORS.get(integration.connector_key)
    tracer = (
        await Tracer.resume(session, delivery.trace_id)
        if delivery.trace_id is not None
        else Tracer(
            session,
            root_object_type="integration_delivery",
            root_object_id=str(delivery.id),
            trace_class=TraceClass.ROUTINE,
            compact=True,
            project_id=delivery.project_id,
            device_id=delivery.device_id,
        )
    )
    if delivery.trace_id is None:
        await tracer.start()
        delivery.trace_id = tracer.trace_id
    delivery.attempts += 1
    delivery.last_attempt_at = now
    context = integration_context(integration)
    try:
        if connector is None:
            raise PermanentFailure(f"unknown connector {integration.connector_key!r}")
        async with tracer.step("integration", "object loaded") as step:
            item = await load_item(session, delivery)
            if item is None:
                step.skip("object no longer exists")
                raise Skipped("the object no longer exists")
            step.output_ref = f"{delivery.object_type}:{delivery.object_id}"
        async with tracer.step("integration", f"rendered for {connector.label}"):
            payload = connector.render(context, item)
            payload_with_id = {**payload, "delivery_id": str(delivery.id)}
            delivery.request = payload
        async with tracer.step("integration", f"delivered to {connector.label}") as step:
            result = await connector.deliver(context, item, payload_with_id)
            step.output_ref = f"external:{result.external_id}" if result.external_id else None
        delivery.status = DeliveryStatus.SENT
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        delivery.external_id = result.external_id
        delivery.response = result.response
        delivery.error_code = None
        delivery.error_message = None
        integration.last_delivery_at = now
        await tracer.finish()
    except Skipped as exc:
        delivery.status = DeliveryStatus.SKIPPED
        delivery.next_attempt_at = None
        delivery.error_code = None
        delivery.error_message = str(exc)
        await tracer.finish()
    except PermanentFailure as exc:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        delivery.error_code = ErrorCode.INTEGRATION_DELIVERY_FAILED
        delivery.error_message = str(exc)
        integration.last_error = str(exc)
        integration.last_error_at = now
        await _record_failure(
            tracer,
            ApplicationError(
                code=ErrorCode.INTEGRATION_DELIVERY_FAILED,
                message=str(exc),
                component=f"integration.{integration.connector_key}",
                user_actionable=True,
            ),
        )
    except (TransientFailure, Exception) as exc:
        message = str(exc) if isinstance(exc, TransientFailure) else f"{type(exc).__name__}: {exc}"
        integration.last_error = message
        integration.last_error_at = now
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = DeliveryStatus.FAILED
            delivery.next_attempt_at = None
            delivery.error_code = ErrorCode.INTEGRATION_DELIVERY_FAILED
            delivery.error_message = f"gave up after {delivery.attempts} attempts: {message}"
            await _record_failure(
                tracer,
                ApplicationError(
                    code=ErrorCode.INTEGRATION_DELIVERY_FAILED,
                    message=delivery.error_message,
                    component=f"integration.{integration.connector_key}",
                    retryable=True,
                ),
            )
        else:
            delay = backoff_seconds(delivery.attempts)
            delivery.status = DeliveryStatus.QUEUED
            delivery.next_attempt_at = now + timedelta(seconds=delay)
            delivery.error_code = ErrorCode.INTEGRATION_DELIVERY_FAILED
            delivery.error_message = f"{message} (retry in {delay} s)"
            tracer.trace.status = TraceStatus.RETRYING
        if not isinstance(exc, TransientFailure):
            log.error(
                "integration delivery crashed",
                delivery_id=str(delivery.id),
                connector=integration.connector_key,
                exc_info=True,
            )
    await session.flush()
    return str(delivery.status)


async def due_deliveries(
    session: AsyncSession, now: datetime, *, limit: int = 200
) -> list[IntegrationDelivery]:
    return list(
        (
            await session.scalars(
                select(IntegrationDelivery)
                .where(
                    IntegrationDelivery.status == DeliveryStatus.QUEUED,
                    IntegrationDelivery.next_attempt_at <= now,
                )
                .order_by(IntegrationDelivery.next_attempt_at, IntegrationDelivery.created_at)
                .limit(limit)
            )
        ).all()
    )


def requeue(delivery: IntegrationDelivery, now: datetime | None = None) -> None:
    """Manual retry: back to the queue for an immediate attempt, attempts kept for the record."""
    delivery.status = DeliveryStatus.QUEUED
    delivery.next_attempt_at = now or utc_now()
    delivery.origin = DeliveryOrigin.RETRY
    delivery.error_code = None
    delivery.error_message = None


def _position_ref(row: Position) -> ObjectRef:
    return ObjectRef(
        object_type=IntegrationObjectType.POSITION,
        object_id=str(row.id),
        time=row.time,
        project_id=row.project_id or uuid.UUID(int=0),
        entity_id=row.entity_id,
        device_id=row.device_id,
    )


def event_ref(row: Event) -> ObjectRef:
    return ObjectRef(
        object_type=IntegrationObjectType.EVENT,
        object_id=str(row.id),
        time=row.time,
        project_id=row.project_id or uuid.UUID(int=0),
        entity_id=row.entity_id,
        device_id=row.device_id,
        event_type=row.event_type,
        severity=row.severity,
    )


def measurement_ref(row: Measurement) -> ObjectRef:
    return ObjectRef(
        object_type=IntegrationObjectType.MEASUREMENT,
        object_id=str(row.id),
        time=row.time,
        project_id=row.project_id or uuid.UUID(int=0),
        entity_id=row.entity_id,
        device_id=row.device_id,
        metric_key=row.metric_key,
    )


async def backfill(
    session: AsyncSession,
    integration: Integration,
    time_from: datetime,
    time_to: datetime,
    *,
    batch: int = BACKFILL_BATCH,
) -> int:
    """Queue every matching object of the project in [time_from, time_to) in batches; existing
    keys are skipped. Progress lands on `integration.backfill` after every batch, so the UI
    can follow a long run. The caller commits at the end; the function commits per batch."""
    queued = 0
    scanned = 0
    integration.backfill = {
        **integration.backfill,
        "status": BackfillStatus.RUNNING,
        "from": time_from.isoformat(),
        "to": time_to.isoformat(),
        "queued": 0,
        "scanned": 0,
        "started_at": utc_now().isoformat(),
        "finished_at": None,
        "error": None,
    }
    await session.commit()
    try:
        for object_type in integration.object_types or []:
            model: Any
            make: Any
            if object_type == IntegrationObjectType.POSITION:
                model, make = Position, _position_ref
            elif object_type == IntegrationObjectType.EVENT:
                model, make = Event, event_ref
            elif object_type == IntegrationObjectType.MEASUREMENT:
                model, make = Measurement, measurement_ref
            else:
                continue
            cursor = time_from
            last_id: Any = None
            while True:
                statement = (
                    select(model)
                    .where(
                        model.project_id == integration.project_id,
                        model.time >= cursor,
                        model.time < time_to,
                    )
                    .order_by(model.time, model.id)
                    .limit(batch)
                )
                rows = list((await session.scalars(statement)).all())
                if last_id is not None:
                    rows = [r for r in rows if not (r.time == cursor and r.id <= last_id)]
                if not rows:
                    break
                refs = [make(row) for row in rows]
                queued += await enqueue(
                    session,
                    [integration],
                    refs,
                    origin=DeliveryOrigin.BACKFILL,
                    honour_age=False,
                )
                scanned += len(rows)
                integration.backfill = {
                    **integration.backfill,
                    "queued": queued,
                    "scanned": scanned,
                }
                await session.commit()
                last = rows[-1]
                if len(rows) < batch and last.time == cursor and last_id is not None:
                    break
                cursor, last_id = last.time, last.id
                if len(rows) < batch:
                    break
        integration.backfill = {
            **integration.backfill,
            "status": BackfillStatus.DONE,
            "queued": queued,
            "scanned": scanned,
            "finished_at": utc_now().isoformat(),
        }
    except Exception as exc:
        integration.backfill = {
            **integration.backfill,
            "status": BackfillStatus.FAILED,
            "error": f"{type(exc).__name__}: {exc}",
            "finished_at": utc_now().isoformat(),
        }
        await session.commit()
        raise
    await session.commit()
    return queued


async def delivery_counts(
    session: AsyncSession, integration_id: uuid.UUID, since: datetime | None = None
) -> dict[str, int]:
    statement = (
        select(IntegrationDelivery.status, func.count())
        .where(IntegrationDelivery.integration_id == integration_id)
        .group_by(IntegrationDelivery.status)
    )
    if since is not None:
        statement = statement.where(IntegrationDelivery.created_at >= since)
    counts = {status.value: 0 for status in DeliveryStatus}
    for status, count in (await session.execute(statement)).all():
        counts[str(status)] = int(count)
    return counts
