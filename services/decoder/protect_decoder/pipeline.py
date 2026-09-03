"""Source event to canonical rows (architecture 25, 26, 28.5).

For one source event: select the driver from the device type, decode, resolve the canonical time
per record, compute the canonical key, deduplicate against existing rows (a repeat delivery links
to the existing row and creates nothing), resolve project and entity at the canonical time, write
canonical rows and current state in one transaction, then publish domain events after commit.
Every step lands on the trace the ingest started. Expected failures raise `ApplicationError`
with a code; the bus dead-letters them without retry because a decode failure does not fix
itself.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.device_drivers.base import (
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    SourceEventData,
    canonical_key,
    fingerprint,
)
from shared.device_drivers.registry import DRIVERS
from shared.domain.assignments import Attribution, resolve_attribution
from shared.enums import ConnectivityStatus, ErrorCode, ProcessingStatus, TraceStatus, ValueType
from shared.logger import get_logger
from shared.models import (
    ConnectivityState,
    Device,
    DeviceCurrentState,
    DeviceStateHistory,
    DeviceType,
    EntityCurrentState,
    Event,
    Measurement,
    Metric,
    Position,
    SourceDelivery,
    SourceEvent,
)
from shared.storage import get_object
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("decoder")

AttributionAt = Callable[[datetime], Awaitable[Attribution]]


@dataclass(slots=True)
class Outcome:
    source_event_id: int
    status: ProcessingStatus
    created: dict[str, int] = field(
        default_factory=lambda: {"positions": 0, "measurements": 0, "states": 0, "events": 0}
    )
    duplicates: int = 0
    messages: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    trace_id: uuid.UUID | None = None


def event_age(record_time: datetime, ingested_at: datetime) -> float:
    """Seconds between the canonical time of a record and its arrival (architecture 25.8)."""
    return (ingested_at - record_time).total_seconds()


async def load_source_event(
    session: AsyncSession, source_event_id: int, ingested_at: datetime
) -> SourceEvent:
    event = await session.scalar(
        select(SourceEvent).where(
            SourceEvent.id == source_event_id, SourceEvent.ingested_at == ingested_at
        )
    )
    if event is None:
        raise ApplicationError(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"source event {source_event_id} at {ingested_at.isoformat()} not found",
            component="decoder",
        )
    return event


async def payload_of(event: SourceEvent) -> dict[str, Any]:
    if event.payload is not None:
        return event.payload
    if event.payload_object_key is None:
        raise ApplicationError(
            code=ErrorCode.INTERNAL_ERROR,
            message="source event has no payload",
            component="decoder",
        )
    import json

    from shared.config import get_settings

    data = json.loads(
        await get_object(get_settings().minio_bucket_uploads, event.payload_object_key)
    )
    return data if isinstance(data, dict) else {"value": data}


async def process_source_event(
    session: AsyncSession, source_event_id: int, ingested_at: datetime, *, reprocess: bool = False
) -> Outcome:
    """Decode one source event inside the caller's session. Commits nothing; the caller commits
    and publishes `outcome.messages`."""
    event = await load_source_event(session, source_event_id, ingested_at)
    outcome = Outcome(
        source_event_id=event.id, status=ProcessingStatus.PROCESSED, trace_id=event.trace_id
    )
    if event.processing_status == ProcessingStatus.PROCESSED and not reprocess:
        outcome.status = ProcessingStatus.PROCESSED
        return outcome
    if event.device_id is None:
        event.processing_status = ProcessingStatus.UNASSIGNED
        outcome.status = ProcessingStatus.UNASSIGNED
        return outcome

    tracer = (
        await Tracer.resume(session, event.trace_id)
        if event.trace_id
        else Tracer(
            session,
            root_object_type="source_event",
            root_object_id=str(event.id),
            compact=True,
            device_id=event.device_id,
        )
    )
    if event.trace_id is None:
        await tracer.start()
        event.trace_id = tracer.trace_id
        outcome.trace_id = tracer.trace_id
    tracer.trace.device_id = event.device_id

    try:
        async with tracer.step(
            "decoder", "driver selected", input_ref=f"device:{event.device_id}"
        ) as step:
            device = await session.get(Device, event.device_id)
            if device is None:
                raise ApplicationError(
                    code=ErrorCode.DEVICE_NOT_FOUND,
                    message=f"device {event.device_id} not found",
                    component="decoder",
                    user_actionable=True,
                )
            device_type = await session.get(DeviceType, device.device_type_id)
            assert device_type is not None
            driver = DRIVERS.get(device_type.driver_key)
            if driver is None:
                raise ApplicationError(
                    code=ErrorCode.PAYLOAD_DECODE_FAILED,
                    message=f"no driver {device_type.driver_key!r} for type {device_type.key}",
                    component="decoder",
                    user_actionable=True,
                )
            step.output_ref = f"driver:{driver.key}"

        async with tracer.step("decoder", "payload decoded") as step:
            records = driver.decode(
                SourceEventData(
                    id=event.id,
                    event_type=event.event_type,
                    payload=await payload_of(event),
                    provider_metadata=event.provider_metadata,
                    network_received_at=event.network_received_at,
                    ingested_at=event.ingested_at,
                    device_attributes=device.attributes,
                    device_type_settings=device_type.default_settings,
                )
            )
            step.metadata.update(
                positions=len(records.positions),
                measurements=len(records.measurements),
                states=len(records.states),
                events=len(records.events),
                decoder_version=records.decoder_version,
            )
            if records.empty:
                step.skip("payload holds no records")

        async with tracer.step("decoder", "canonical rows written") as step:
            attributions: dict[datetime, Attribution] = {}

            async def attribution_at(time: datetime) -> Attribution:
                if time not in attributions:
                    attributions[time] = await resolve_attribution(session, device.id, time)
                return attributions[time]

            await _write_positions(session, event, device, records, outcome, attribution_at)
            await _write_measurements(session, event, device, records, outcome, attribution_at)
            await _write_states(session, event, device, records, outcome, attribution_at)
            await _write_events(session, event, device, records, outcome, attribution_at)
            total = sum(outcome.created.values())
            step.metadata.update(created=total, duplicates=outcome.duplicates)
            if total == 0 and outcome.duplicates > 0:
                step.duplicate(of="existing canonical rows")
            unassigned = [t for t, a in attributions.items() if not a.assigned]
            if unassigned:
                step.metadata["unassigned_times"] = [t.isoformat() for t in unassigned]

        await _update_current_state(session, event, device, records, attributions)
    except ApplicationError as error:
        event.processing_status = ProcessingStatus.FAILED
        event.error_code = error.code
        outcome.status = ProcessingStatus.FAILED
        raise
    if sum(outcome.created.values()) == 0 and outcome.duplicates > 0:
        event.processing_status = ProcessingStatus.DUPLICATE
        outcome.status = ProcessingStatus.DUPLICATE
        await tracer.finish(TraceStatus.DUPLICATE)
    else:
        event.processing_status = ProcessingStatus.PROCESSED
        await tracer.finish()
    event.error_code = None
    return outcome


async def _link_delivery(
    session: AsyncSession,
    event: SourceEvent,
    canonical_type: str,
    canonical_id: int,
    canonical_time: datetime,
    first: bool,
) -> None:
    session.add(
        SourceDelivery(
            canonical_type=canonical_type,
            canonical_id=canonical_id,
            canonical_time=canonical_time,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            acquisition_channel=event.acquisition_channel,
            first=first,
        )
    )


async def _existing_delivery(
    session: AsyncSession, event: SourceEvent, canonical_type: str, canonical_id: int
) -> bool:
    return (
        await session.scalar(
            select(SourceDelivery.id).where(
                SourceDelivery.canonical_type == canonical_type,
                SourceDelivery.canonical_id == canonical_id,
                SourceDelivery.source_event_id == event.id,
            )
        )
    ) is not None


async def _write_positions(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    for record in records.positions:
        key = canonical_key(device.id, record.time, record.record_type, record.fingerprint)
        existing = await session.scalar(
            select(Position).where(Position.canonical_key == key, Position.time == record.time)
        )
        if existing is not None:
            outcome.duplicates += 1
            if not await _existing_delivery(session, event, "position", existing.id):
                await _link_delivery(
                    session, event, "position", existing.id, existing.time, first=False
                )
            continue
        attribution = await attribution_at(record.time)
        position = Position(
            time=record.time,
            device_id=device.id,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            data_source_id=event.data_source_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            record_type=record.record_type,
            canonical_key=key,
            geom=from_shape(Point(record.longitude, record.latitude), srid=4326),
            altitude_m=record.altitude_m,
            speed_mps=record.speed_mps,
            heading_deg=record.heading_deg,
            accuracy_m=record.accuracy_m,
            satellites=record.satellites,
            attributes=record.attributes,
            trace_id=event.trace_id,
        )
        session.add(position)
        await session.flush()
        await _link_delivery(session, event, "position", position.id, position.time, first=True)
        outcome.created["positions"] += 1
        outcome.messages.append(
            (
                Topic.POSITION_CREATED,
                {
                    "position_id": position.id,
                    "time": position.time.isoformat(),
                    "device_id": str(device.id),
                    "project_id": str(attribution.project_id) if attribution.project_id else None,
                    "entity_id": str(attribution.entity_id) if attribution.entity_id else None,
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "source_event_id": event.id,
                    "age_seconds": event_age(position.time, event.ingested_at),
                },
            )
        )


def _value_columns(value: Any) -> tuple[dict[str, Any], ValueType]:
    if isinstance(value, bool):
        return {"value_bool": value}, ValueType.BOOLEAN
    if isinstance(value, int | float):
        return {"value_num": float(value)}, ValueType.NUMERIC
    if isinstance(value, str):
        return {"value_text": value}, ValueType.TEXT
    return {"value_json": value}, ValueType.JSON


async def _ensure_metric(session: AsyncSession, key: str, value_type: ValueType) -> None:
    if await session.get(Metric, key) is None:
        session.add(
            Metric(
                key=key,
                label=key.replace("_", " "),
                value_type=value_type,
                category="uncategorized",
            )
        )
        await session.flush()
        log.warning("metric registered automatically, set its unit and category", metric_key=key)


async def _write_measurements(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    created_ids: list[int] = []
    for record in records.measurements:
        extra = record.metric_key + (f":{record.fingerprint}" if record.fingerprint else "")
        key = canonical_key(device.id, record.time, record.record_type, extra)
        existing = await session.scalar(
            select(Measurement).where(
                Measurement.canonical_key == key, Measurement.time == record.time
            )
        )
        if existing is not None:
            outcome.duplicates += 1
            if not await _existing_delivery(session, event, "measurement", existing.id):
                await _link_delivery(
                    session, event, "measurement", existing.id, existing.time, first=False
                )
            continue
        columns, value_type = _value_columns(record.value)
        await _ensure_metric(session, record.metric_key, value_type)
        attribution = await attribution_at(record.time)
        measurement = Measurement(
            time=record.time,
            device_id=device.id,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            data_source_id=event.data_source_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            metric_key=record.metric_key,
            canonical_key=key,
            trace_id=event.trace_id,
            **columns,
        )
        session.add(measurement)
        await session.flush()
        await _link_delivery(
            session, event, "measurement", measurement.id, measurement.time, first=True
        )
        outcome.created["measurements"] += 1
        created_ids.append(measurement.id)
    if created_ids:
        outcome.messages.append(
            (
                Topic.MEASUREMENT_CREATED,
                {
                    "measurement_ids": created_ids,
                    "device_id": str(device.id),
                    "source_event_id": event.id,
                },
            )
        )


async def _write_states(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    for record in records.states:
        attribution = await attribution_at(record.time)
        exists = await session.scalar(
            select(DeviceStateHistory.id).where(
                DeviceStateHistory.device_id == device.id, DeviceStateHistory.time == record.time
            )
        )
        if exists is not None:
            outcome.duplicates += 1
            continue
        row = DeviceStateHistory(
            time=record.time,
            device_id=device.id,
            project_id=attribution.project_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            state=record.state,
        )
        session.add(row)
        await session.flush()
        await _link_delivery(session, event, "state", row.id, row.time, first=True)
        outcome.created["states"] += 1
        outcome.messages.append(
            (
                Topic.DEVICE_STATE_CHANGED,
                {
                    "device_id": str(device.id),
                    "time": record.time.isoformat(),
                    "state": record.state,
                    "source_event_id": event.id,
                },
            )
        )


async def _write_events(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    for record in records.events:
        attribution = await attribution_at(record.time)
        if attribution.project_id is None:
            log.warning(
                "device event without project skipped",
                device_id=str(device.id),
                event_type=record.event_type,
            )
            continue
        dedup = fingerprint([str(device.id), record.time.isoformat(), record.event_type])
        exists = await session.scalar(
            select(Event.id).where(Event.context["dedup"].astext == dedup)
        )
        if exists is not None:
            outcome.duplicates += 1
            continue
        row = Event(
            time=record.time,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            device_id=device.id,
            event_type=record.event_type,
            severity=record.severity,
            title=record.title,
            context={**record.context, "dedup": dedup},
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            trace_id=event.trace_id,
        )
        session.add(row)
        await session.flush()
        outcome.created["events"] += 1
        outcome.messages.append(
            (
                Topic.EVENT_CREATED,
                {
                    "event_id": str(row.id),
                    "project_id": str(attribution.project_id),
                    "event_type": record.event_type,
                    "time": record.time.isoformat(),
                },
            )
        )


async def _update_current_state(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    attributions: dict[datetime, Attribution],
) -> None:
    now = utc_now()
    latest_position: DecodedPosition | None = max(
        records.positions, key=lambda p: p.time, default=None
    )
    latest_state = max(records.states, key=lambda s: s.time, default=None)
    latest_measurements: dict[str, DecodedMeasurement] = {}
    for m in records.measurements:
        if (
            m.metric_key not in latest_measurements
            or m.time > latest_measurements[m.metric_key].time
        ):
            latest_measurements[m.metric_key] = m
    seen_at = max(
        [
            r.time
            for r in records.positions + records.measurements + records.states + records.events
        ],
        default=event.network_received_at or event.ingested_at,
    )

    current = await session.get(DeviceCurrentState, device.id)
    if current is None:
        current = DeviceCurrentState(device_id=device.id, latest_state={})
        session.add(current)
    if current.last_seen_at is None or seen_at > current.last_seen_at:
        current.last_seen_at = seen_at
    if latest_position is not None and (
        current.latest_position_time is None or latest_position.time > current.latest_position_time
    ):
        current.latest_position_time = latest_position.time
        current.latest_position = from_shape(
            Point(latest_position.longitude, latest_position.latitude), srid=4326
        )
    if latest_state is not None:
        current.latest_state = {**(current.latest_state or {}), **latest_state.state}
    if "battery_voltage" in latest_measurements and isinstance(
        latest_measurements["battery_voltage"].value, int | float
    ):
        current.battery_voltage = float(latest_measurements["battery_voltage"].value)
    current.updated_at = now

    connectivity = await session.get(ConnectivityState, (device.id, event.data_source_id))
    if connectivity is None:
        connectivity = ConnectivityState(device_id=device.id, data_source_id=event.data_source_id)
        session.add(connectivity)
    connectivity.status = ConnectivityStatus.ONLINE
    connectivity.last_uplink_at = event.network_received_at or event.ingested_at
    connectivity.updated_at = now

    if latest_position is not None:
        attribution = attributions.get(latest_position.time)
        if (
            attribution is not None
            and attribution.entity_id is not None
            and attribution.project_id is not None
        ):
            entity_state = await session.get(EntityCurrentState, attribution.entity_id)
            if entity_state is None:
                entity_state = EntityCurrentState(
                    entity_id=attribution.entity_id, project_id=attribution.project_id
                )
                session.add(entity_state)
            if (
                entity_state.latest_position_time is None
                or latest_position.time > entity_state.latest_position_time
            ):
                entity_state.latest_position_time = latest_position.time
                entity_state.latest_position = from_shape(
                    Point(latest_position.longitude, latest_position.latitude), srid=4326
                )
                entity_state.device_id = device.id
            if entity_state.last_seen_at is None or seen_at > entity_state.last_seen_at:
                entity_state.last_seen_at = seen_at
            entity_state.updated_at = now


async def publish_outcome(bus: RedisStreamsBus, outcome: Outcome) -> None:
    for topic, payload in outcome.messages:
        await bus.publish(
            topic, payload, trace_id=str(outcome.trace_id) if outcome.trace_id else None
        )
