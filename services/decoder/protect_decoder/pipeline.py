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
from datetime import datetime, timedelta
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.connectivity.network_location import (
    ESTIMATE_RECORD_TYPES,
    NETWORK_RECORD_TYPE,
    NetworkLocation,
)
from shared.connectivity.satellite import SatelliteSession, estimate_disagreement
from shared.control.commands import (
    apply_provider_signal,
    apply_satellite_delivery,
    interpret_device_records,
)
from shared.curation.effective import device_fix, effective_geom, effective_time, visible
from shared.device_drivers.base import (
    DecodedEvent,
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    SourceEventData,
    canonical_key,
    fingerprint,
    lorawan_frame,
    raw_frame,
)
from shared.device_drivers.registry import DRIVERS
from shared.domain.assignments import Attribution, resolve_attribution
from shared.domain.contacts import (
    HUMAN_PRESENCE_EVENT,
    HUMAN_PRESENCE_METRIC,
    HUMAN_PRESENCE_NOTE,
    HUMAN_PRESENCE_TITLE,
    Resolver,
    human_presence_description,
    resolver_for,
    scanning_of,
    watches_for_people,
)
from shared.domain.contacts import normalise as normalise_address
from shared.domain.device_settings import record_settings_frame
from shared.domain.fence import (
    FENCE_STATUS_EVENT,
    SEVERITY_OF,
    changed_level,
    recompute_fence,
    status_title,
)
from shared.domain.movement import derive_activity, movement_times, previous_sample
from shared.domain.outliers import ATTRIBUTE as OUTLIER_ATTRIBUTE
from shared.domain.outliers import EVENT_TYPE as OUTLIER_EVENT_TYPE
from shared.domain.outliers import outlier_of
from shared.domain.reboot import detect_reboots, previous_uptime
from shared.domain.static_place import Sighting, place_sightings
from shared.domain.trap import (
    TRAP_ENTITY_TYPE,
    closed_when_active,
    derive_trap,
    previous_closed,
)
from shared.enums import (
    AcquisitionChannel,
    ConnectivityStatus,
    ContactResolution,
    ErrorCode,
    LocationSource,
    ProcessingStatus,
    Severity,
    TraceStatus,
    ValueType,
)
from shared.logger import get_logger
from shared.models import (
    ConnectivityState,
    Device,
    DeviceContact,
    DeviceCurrentState,
    DeviceStateHistory,
    DeviceType,
    Entity,
    EntityCurrentState,
    Event,
    Measurement,
    Metric,
    Position,
    SourceDelivery,
    SourceEvent,
)
from shared.storage import get_object
from shared.timeutil import clock_ahead, clock_behind, delivers_live, utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("decoder")

AttributionAt = Callable[[datetime], Awaitable[Attribution]]
# Channels whose deliveries are raw frames without a LoRaWAN port (architecture 25.1).
FRAME_CHANNELS = frozenset(
    {AcquisitionChannel.WEBBLE, AcquisitionChannel.LOG_FILE, AcquisitionChannel.IRIDIUM}
)


@dataclass(slots=True)
class Outcome:
    source_event_id: int
    status: ProcessingStatus
    created: dict[str, int] = field(
        default_factory=lambda: {
            "positions": 0,
            "measurements": 0,
            "states": 0,
            "events": 0,
            "contacts": 0,
        }
    )
    duplicates: int = 0
    messages: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    trace_id: uuid.UUID | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    firmware_version: str | None = None
    decoder_version: str | None = None
    # records whose device time ran ahead of the delivery (decision D119), kept invalid
    clock_ahead: int = 0
    clock_ahead_seconds: float = 0.0
    # fixes flagged as outliers (decision D221), kept invalid until approved; their times, so
    # the current state skips them
    outliers: int = 0
    outlier_times: set[datetime] = field(default_factory=set)
    # settings the device reported that changed what Protect knew (decision D229)
    settings_changed: int = 0
    # contacts whose address named more than one device, so they belong to neither (D254)
    ambiguous_contacts: int = 0


async def _previous_fix(
    session: AsyncSession, device_id: uuid.UUID, before: datetime
) -> tuple[float, float, datetime] | None:
    """The device's last valid own fix before `before`, at its effective time and place (a
    fix written earlier in this transaction counts, so a log file is judged in order)."""
    row = (
        await session.execute(
            select(
                func.ST_Y(effective_geom()),
                func.ST_X(effective_geom()),
                effective_time(Position).label("at"),
            )
            .where(
                Position.device_id == device_id,
                effective_time(Position) < before,
                visible(Position),
                device_fix(),
            )
            .order_by(effective_time(Position).desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return float(row[0]), float(row[1]), row[2]


def _ahead_of_delivery(event: SourceEvent, record_time: datetime) -> float:
    """Seconds the record's device time runs ahead of the delivery beyond the tolerance."""
    received = event.network_received_at or event.ingested_at
    return clock_ahead(record_time, received, get_settings().clock_ahead_tolerance_seconds)


def _behind_delivery(event: SourceEvent, record_time: datetime) -> float:
    """Seconds the record's device time runs behind its delivery beyond the tolerance (D259).

    Only on a path that delivers as it happens: a log file carries the past on purpose, and a
    device out of coverage delivers late for good reasons. Zero when the clock is believable."""
    if not delivers_live(event.acquisition_channel):
        return 0.0
    return clock_behind(
        record_time, event.ingested_at, get_settings().clock_behind_tolerance_seconds
    )


def _believed_time(event: SourceEvent, record_time: datetime) -> tuple[datetime, float]:
    """When a record is filed, and by how far its device disagreed (decision D259).

    Every record of one scan has to be filed the same way, or the scan lands twice under two
    times: SP051464's clock runs 45 hours behind, and its sightings were corrected while the scan
    that made them was not, so the same scan sat 45 hours apart in two tables and the chart of
    what a reader heard ended two days before its own sightings did.

    Only records the driver marks `device_clock`, which are the ones whose time is the same
    reading the contacts carry. Not every old record in a delivery: a genuine backfill over a
    live channel carries the past on purpose and moving it would be a lie of its own. And not
    positions, since rewriting when an animal was somewhere moves tracks and attribution, which
    is a heavier thing than moving a reading and is Tim's to decide."""
    behind = _behind_delivery(event, record_time)
    return (event.ingested_at if behind else record_time), behind


def event_age(record_time: datetime, ingested_at: datetime) -> float:
    """Seconds between the canonical time of a record and its arrival (architecture 25.8)."""
    return (ingested_at - record_time).total_seconds()


def _add_network_position(event: SourceEvent, records: DecodedRecords) -> None:
    """A location the network provided (decision D162) becomes a position of its own record
    type next to the driver's records: the radius as accuracy, the method in the attributes.
    The canonical key keeps it apart from a device fix at the same moment."""
    location = NetworkLocation.from_dict((event.provider_metadata or {}).get("network_location"))
    if location is None:
        return
    records.positions.append(
        DecodedPosition(
            time=location.time,
            latitude=location.latitude,
            longitude=location.longitude,
            record_type=NETWORK_RECORD_TYPE,
            altitude_m=location.altitude_m,
            accuracy_m=location.accuracy_m,
            attributes={"method": location.method, **(location.attributes or {})},
        )
    )


def _note_estimate_disagreement(event: SourceEvent, records: DecodedRecords) -> None:
    """A decoded fix far outside the satellite network's location estimate is worth a note on
    the trace (decision D158): a GNSS fault, a clock fault or a device that travelled a long
    way between the fix and the session."""
    satellite = SatelliteSession.from_dict((event.provider_metadata or {}).get("satellite_session"))
    if satellite is None or not records.positions:
        return
    farthest = max(
        (
            estimate_disagreement(satellite, p.latitude, p.longitude) or 0.0
            for p in records.positions
            if p.record_type not in ESTIMATE_RECORD_TYPES
        ),
        default=0.0,
    )
    if farthest > 0:
        records.notes.append(
            f"a fix lies {farthest / 1000:.0f} km from the Iridium estimate "
            f"(CEP {satellite.cep_km:g} km)"
        )


def network_event_records(event: SourceEvent, payload: dict[str, Any]) -> DecodedRecords:
    """Records from network-level events that need no device driver (architecture 8.1): a
    LoRaWAN status event carries battery level and link margin; joins and downlink
    acknowledgements only touch connectivity state, handled in `_update_current_state`."""
    records = DecodedRecords(decoder_version="network")
    time = event.network_received_at or event.ingested_at
    if event.event_type == "status":
        level = payload.get("batteryLevel")
        if isinstance(level, int | float) and not payload.get("batteryLevelUnavailable"):
            records.measurements.append(
                DecodedMeasurement(
                    time=time,
                    metric_key="battery_level",
                    value=float(level),
                    record_type="network_status",
                )
            )
        margin = payload.get("margin")
        if isinstance(margin, int | float):
            records.measurements.append(
                DecodedMeasurement(
                    time=time,
                    metric_key="link_margin",
                    value=float(margin),
                    record_type="network_status",
                )
            )
    return records


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
            payload = await payload_of(event)
            frame, f_port = (None, None)
            if event.acquisition_channel == AcquisitionChannel.LORAWAN:
                frame, f_port = lorawan_frame(payload, event.provider_metadata)
            elif event.acquisition_channel in FRAME_CHANNELS:
                frame = raw_frame(payload, event.provider_metadata)
            if (
                event.event_type in driver.decodable_event_types
                and event.acquisition_channel == AcquisitionChannel.LORAWAN
                and (f_port == 0 or frame == b"")
            ):
                # A MAC-only uplink (port 0) or an explicitly empty payload holds nothing for a
                # driver; it still proves the device is alive, which the connectivity state
                # records. A missing frame is left to the driver: not every LoRaWAN source
                # carries one (a platform that delivers decoded JSON).
                records = DecodedRecords(decoder_version="none")
                records.notes.append(
                    "no application payload" + (" (port 0)" if f_port == 0 else "")
                )
            elif event.event_type in driver.decodable_event_types:
                records = driver.decode(
                    SourceEventData(
                        id=event.id,
                        event_type=event.event_type,
                        payload=payload,
                        provider_metadata=event.provider_metadata,
                        network_received_at=event.network_received_at,
                        ingested_at=event.ingested_at,
                        device_attributes=device.attributes,
                        device_type_settings=device_type.default_settings,
                        frame=frame,
                        f_port=f_port,
                        acquisition_channel=event.acquisition_channel,
                        firmware_version=device.firmware_version,
                    )
                )
            else:
                records = network_event_records(event, payload)
                step.metadata["network_event"] = event.event_type
                outcome.messages += await apply_provider_signal(session, event, payload)
            step.metadata.update(
                positions=len(records.positions),
                measurements=len(records.measurements),
                states=len(records.states),
                events=len(records.events),
                decoder_version=records.decoder_version,
            )
            _note_estimate_disagreement(event, records)
            _add_network_position(event, records)
            _summarize(outcome, records)
            if records.notes:
                step.metadata["notes"] = list(records.notes)
            if records.empty:
                step.skip("; ".join(records.notes) or "payload holds no records")

        async with tracer.step("decoder", "canonical rows written") as step:
            attributions: dict[datetime, Attribution] = {}

            async def attribution_at(time: datetime) -> Attribution:
                if time not in attributions:
                    attributions[time] = await resolve_attribution(session, device.id, time)
                return attributions[time]

            # movement from the accelerometer sample of a status message: the change against
            # the sample before it, stored as `activity` (shared/domain/movement.py)
            before = await session.get(DeviceCurrentState, device.id)
            records.measurements += derive_activity(
                records.measurements,
                previous_sample(before.latest_measurements if before else None),
            )
            # a reboot from an uptime lower than the one before it (shared/domain/reboot.py)
            wrap = getattr(driver, "uptime_wrap_seconds", None)
            records.events += detect_reboots(
                records.measurements,
                records.states,
                previous_uptime(before.latest_measurements if before else None),
                wrap(device.firmware_version) if callable(wrap) else None,
            )
            # a switch on a trap says whether the door is shut (shared/domain/trap.py)
            if any(m.metric_key == "switch_active" for m in records.measurements):
                trap = await _trap_entity(
                    session, await attribution_at(records.measurements[0].time)
                )
                if trap is not None:
                    derive_trap(
                        records,
                        entity_name=trap,
                        wiring_closed_when_active=closed_when_active(device.attributes),
                        was_closed=previous_closed(before.latest_measurements if before else None),
                    )
            await _write_positions(session, event, device, records, outcome, attribution_at)
            await _write_measurements(session, event, device, records, outcome, attribution_at)
            await _write_states(session, event, device, records, outcome, attribution_at)
            await _write_events(session, event, device, records, outcome, attribution_at)
            await _write_contacts(session, event, device, records, outcome, attribution_at)
            # a fence reading changes what a stretch of fence line says (shared/domain/fence.py)
            fence_records = [
                r for r in records.measurements + records.states if r.record_type == "fence"
            ]
            if fence_records:
                await _update_fence(session, event, device, fence_records[0].time, outcome)
            total = sum(outcome.created.values())
            step.metadata.update(created=total, duplicates=outcome.duplicates)
            if outcome.settings_changed:
                step.metadata["settings_changed"] = outcome.settings_changed
            if outcome.outliers:
                step.metadata["outliers"] = outcome.outliers
                step.metadata["outlier_note"] = (
                    f"{outcome.outliers} fixes flagged as outliers (an impossible speed from the "
                    "last valid fix), kept invalid until approved under Curation"
                )
            if outcome.clock_ahead:
                step.metadata["clock_ahead_records"] = outcome.clock_ahead
                step.metadata["clock_ahead_days"] = round(outcome.clock_ahead_seconds / 86400, 2)
                step.metadata["note"] = (
                    f"device clock {outcome.clock_ahead_seconds / 86400:.1f} days ahead of the "
                    f"delivery: {outcome.clock_ahead} records kept invalid until curated"
                )
            if total == 0 and outcome.duplicates > 0:
                step.duplicate(of="existing canonical rows")
            unassigned = [t for t, a in attributions.items() if not a.assigned]
            if unassigned:
                step.metadata["unassigned_times"] = [t.isoformat() for t in unassigned]

        await _update_current_state(session, event, device, records, attributions, outcome)
        outcome.messages += await interpret_device_records(session, device, driver, event, records)
        satellite = SatelliteSession.from_dict(
            (event.provider_metadata or {}).get("satellite_session")
        )
        if satellite is not None:
            outcome.messages += await apply_satellite_delivery(
                session, device, event, satellite.mt_sequence
            )
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


def _summarize(outcome: Outcome, records: DecodedRecords) -> None:
    """Period and versions of the decoded records, for the log file counters."""
    times = [
        r.time
        for group in (records.positions, records.measurements, records.states, records.events)
        for r in group
    ]
    if times:
        outcome.earliest, outcome.latest = min(times), max(times)
    outcome.decoder_version = records.decoder_version
    for state in records.states:
        version = state.state.get("firmware_version") if isinstance(state.state, dict) else None
        if version:
            outcome.firmware_version = str(version)


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
        ahead = _ahead_of_delivery(event, record.time)
        if ahead:
            outcome.clock_ahead += 1
            outcome.clock_ahead_seconds = max(outcome.clock_ahead_seconds, ahead)
        attributes = dict(record.attributes)
        outlier = None
        if not ahead and record.record_type not in ESTIMATE_RECORD_TYPES:
            previous = await _previous_fix(session, device.id, record.time)
            if previous is not None:
                settings = get_settings()
                outlier = outlier_of(
                    previous,
                    (record.latitude, record.longitude, record.time),
                    max_speed_mps=settings.outlier_max_speed_mps,
                    min_jump_m=settings.outlier_min_jump_m,
                )
        if outlier is not None:
            # flagged and kept invalid until a person approves it (decision D221); the event
            # lets rules and the lists say so
            settings = get_settings()
            attributes[OUTLIER_ATTRIBUTE] = outlier.attribute(
                max_speed_mps=settings.outlier_max_speed_mps,
                min_jump_m=settings.outlier_min_jump_m,
            )
            outcome.outliers += 1
            outcome.outlier_times.add(record.time)
            records.events.append(
                DecodedEvent(
                    time=record.time,
                    event_type=OUTLIER_EVENT_TYPE,
                    title=outlier.title(),
                    severity=Severity.INFO,
                    context={**attributes[OUTLIER_ATTRIBUTE], "record_type": record.record_type},
                    latitude=record.latitude,
                    longitude=record.longitude,
                )
            )
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
            valid=not ahead and outlier is None,
            geom=from_shape(Point(record.longitude, record.latitude), srid=4326),
            altitude_m=record.altitude_m,
            speed_mps=record.speed_mps,
            heading_deg=record.heading_deg,
            accuracy_m=record.accuracy_m,
            satellites=record.satellites,
            attributes=attributes,
            trace_id=event.trace_id,
        )
        session.add(position)
        await session.flush()
        await _link_delivery(session, event, "position", position.id, position.time, first=True)
        outcome.created["positions"] += 1
        if not position.valid:
            # an invalid fix (a clock ahead, an outlier) moves no map, fires no rule and
            # reaches no integration; it waits for a curation
            continue
        outcome.messages.append(
            (
                Topic.POSITION_CREATED,
                {
                    "position_id": position.id,
                    "time": position.time.isoformat(),
                    "record_type": record.record_type,
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


def _stored_number(state: DeviceCurrentState, metric: str) -> float | None:
    """The newest value a current state holds for a metric, when it is a number."""
    entry = (state.latest_measurements or {}).get(metric)
    value = entry.get("value") if isinstance(entry, dict) else None
    return float(value) if isinstance(value, int | float) else None


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


async def _write_contacts(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    records: DecodedRecords,
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    """A sighting becomes a contact (decision D252), resolved once here and never re-guessed.

    The resolver belongs to the project the row is attributed to, and is read once per project
    rather than once per sighting: a scan carries up to twenty of them and they all look at the
    same fleet. Once per project and not once per delivery, because the time a row is attributed
    at is not always the time the device claimed: a clock far behind its delivery is corrected
    first (decision D259), and a reader 45 hours behind claimed times from before it had joined
    the project at all, which left every one of its sightings unresolved against an empty fleet
    while the row itself was attributed correctly."""
    if not records.contacts:
        return
    # what the device was looking for decides what a sighting can mean (decision D260): under
    # the phone filter nothing is resolved, because a phone's address is random and a match
    # would be a coincidence, and nothing is moved by it
    scanning = await scanning_of(session, device.id)
    people = watches_for_people(scanning)
    resolvers: dict[uuid.UUID | None, Resolver] = {}

    async def resolver_of(project_id: uuid.UUID | None) -> Resolver:
        if people:
            return Resolver(by_suffix={})
        if project_id not in resolvers:
            resolvers[project_id] = await resolver_for(session, project_id)
        return resolvers[project_id]

    heard: dict[uuid.UUID, datetime] = {}
    # what the device it heard was carrying at that moment, attributed like every other record
    # (decision D103). Cached per counterpart: one scan's sightings share a time, so a herd of
    # twenty neighbours costs twenty lookups and not twenty per sighting.
    worn_by: dict[uuid.UUID, uuid.UUID | None] = {}
    # per scan window, the addresses heard and the strongest signal of each: one window is one
    # presence, however many addresses it carried, since one person carries several
    presence: dict[datetime, dict[str, int | None]] = {}
    for record in records.contacts:
        address = normalise_address(record.address)
        # a device clock is believed unless the delivery says it cannot be right (decision
        # D259): only on a path that arrives as it happens, since a log file carries the past
        # on purpose. The device's own claim stays on the row, so nothing is lost.
        claimed = record.time
        when, behind = _believed_time(event, record.time)
        ahead = _ahead_of_delivery(event, record.time)
        if ahead:
            when = event.ingested_at
            outcome.clock_ahead += 1
            outcome.clock_ahead_seconds = max(outcome.clock_ahead_seconds, ahead)
        # the address is part of the key, so one scan's several sightings are several contacts
        # and the same scan redelivered is one each, as a position redelivered is one position
        key = canonical_key(device.id, when, f"contact:{address}")
        existing = await session.scalar(
            select(DeviceContact.id).where(
                DeviceContact.canonical_key == key, DeviceContact.time == when
            )
        )
        if existing is not None:
            outcome.duplicates += 1
            continue
        attribution = await attribution_at(when)
        found = (await resolver_of(attribution.project_id)).resolve(address, device.id)
        if found.resolution == ContactResolution.AMBIGUOUS:
            outcome.ambiguous_contacts += 1
        counterpart_entity: uuid.UUID | None = None
        if found.device_id is not None:
            if found.device_id not in worn_by:
                seen_at = await resolve_attribution(session, found.device_id, when)
                worn_by[found.device_id] = seen_at.entity_id
            counterpart_entity = worn_by[found.device_id]
        session.add(
            DeviceContact(
                time=when,
                device_time=claimed if when != claimed else None,
                clock_offset_s=round(behind or -ahead) if (behind or ahead) else None,
                device_id=device.id,
                project_id=attribution.project_id,
                entity_id=attribution.entity_id,
                address=address,
                rssi_dbm=record.rssi_dbm,
                sightings=record.sightings,
                scan_kind=record.scan_kind,
                contact_device_id=found.device_id,
                contact_entity_id=counterpart_entity,
                resolution=found.resolution,
                candidates=[str(c) for c in found.candidates] or None,
                canonical_key=key,
                data_source_id=event.data_source_id,
                source_event_id=event.id,
                source_event_ingested_at=event.ingested_at,
            )
        )
        outcome.created["contacts"] += 1
        outcome.earliest = min(outcome.earliest or when, when)
        outcome.latest = max(outcome.latest or when, when)
        if people:
            window = presence.setdefault(when, {})
            best = window.get(address)
            if best is None or (record.rssi_dbm is not None and record.rssi_dbm > best):
                window[address] = record.rssi_dbm
        if found.device_id is not None:
            heard.setdefault(found.device_id, when)
            heard[found.device_id] = max(heard[found.device_id], when)
    # a tag says nothing of itself, so being heard is the only sign it is alive and in range
    # of anything; the same is true of a collar whose own uplinks have stopped (decision D257)
    for seen_id, when in heard.items():
        state = await session.get(DeviceCurrentState, seen_id)
        if state is None:
            state = DeviceCurrentState(device_id=seen_id, latest_state={})
            session.add(state)
        if state.last_seen_at is None or when > state.last_seen_at:
            state.last_seen_at = when
    # and where it was, when the device that heard it has a place of its own (decision D258).
    # Only a device whose place a person set: a collar's own last fix says where the collar was,
    # not where the thing it heard was.
    if device.static_geom is not None and heard:
        await _place_heard_devices(session, event, device, heard, outcome)
    if presence:
        await _write_human_presence(session, event, device, presence, outcome, attribution_at)


async def _write_human_presence(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    presence: dict[datetime, dict[str, int | None]],
    outcome: Outcome,
    attribution_at: AttributionAt,
) -> None:
    """One event and one measurement per scan window that heard a phone (decision D260).

    Per window and not per sighting, because one person carries a phone, a watch and a pair of
    earbuds and each of those advertises separately; and never a count of people, because the
    addresses rotate every few minutes, so the same phone an hour apart is two addresses and two
    phones in one window may be one person. What the platform states is that something human-worn
    was within Bluetooth range of this device at this time, which is the operational reason to
    scan for phones in a reserve at all.

    The measurement exists because the rules engine triggers on measurements and its event
    triggers are still reserved (`shared/rules/schema.py`): a rule that says "tell me when
    somebody is at the north gate" needs a number to threshold, and the number is 1.
    """
    for when, window in sorted(presence.items()):
        attribution = await attribution_at(when)
        if attribution.project_id is None:
            log.warning(
                "human presence without project skipped",
                device_id=str(device.id),
                time=when.isoformat(),
            )
            continue
        dedup = fingerprint([str(device.id), when.isoformat(), HUMAN_PRESENCE_EVENT])
        exists = await session.scalar(
            select(Event.id).where(Event.context["dedup"].astext == dedup)
        )
        if exists is not None:
            outcome.duplicates += 1
            continue
        strongest = max((r for r in window.values() if r is not None), default=None)
        row = Event(
            time=when,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            device_id=device.id,
            event_type=HUMAN_PRESENCE_EVENT,
            severity=Severity.INFO,
            title=HUMAN_PRESENCE_TITLE,
            description=human_presence_description(device.name, len(window)),
            # at the reader when a person placed it, so the event lands on the map where the
            # hardware is; a device that reports its own position has no place to claim here
            geom=device.static_geom,
            context={
                "addresses": len(window),
                "strongest_rssi_dbm": strongest,
                "note": HUMAN_PRESENCE_NOTE,
                "dedup": dedup,
            },
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
                    "event_type": HUMAN_PRESENCE_EVENT,
                    "time": when.isoformat(),
                },
            )
        )
        key = canonical_key(device.id, when, HUMAN_PRESENCE_METRIC)
        already = await session.scalar(
            select(Measurement.id).where(Measurement.canonical_key == key, Measurement.time == when)
        )
        if already is not None:
            continue
        await _ensure_metric(session, HUMAN_PRESENCE_METRIC, ValueType.NUMERIC)
        measurement = Measurement(
            time=when,
            device_id=device.id,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            data_source_id=event.data_source_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            metric_key=HUMAN_PRESENCE_METRIC,
            canonical_key=key,
            value_num=1.0,
            trace_id=event.trace_id,
        )
        session.add(measurement)
        await session.flush()
        outcome.created["measurements"] += 1
        outcome.messages.append(
            (
                Topic.MEASUREMENT_CREATED,
                {
                    "measurement_ids": [measurement.id],
                    "device_id": str(device.id),
                    "source_event_id": event.id,
                },
            )
        )


async def _place_heard_devices(
    session: AsyncSession,
    event: SourceEvent,
    reader: Device,
    heard: dict[uuid.UUID, datetime],
    outcome: Outcome,
) -> None:
    """A position for every device this reader heard, at the reader (decision D258).

    The writing itself lives in `shared.domain.static_place`, because the same positions have to
    be written when a place or an address arrives after the sightings did, which happens in the
    API and not here."""
    outcome.created["positions"] += await place_sightings(
        session,
        reader,
        [
            Sighting(
                seen_id=seen_id,
                when=when,
                data_source_id=event.data_source_id,
                source_event_id=event.id,
                source_event_ingested_at=event.ingested_at,
            )
            for seen_id, when in heard.items()
        ],
    )


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
        filed = _believed_time(event, record.time)[0] if record.device_clock else record.time
        key = canonical_key(device.id, filed, record.record_type, extra)
        existing = await session.scalar(
            select(Measurement).where(Measurement.canonical_key == key, Measurement.time == filed)
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
        # a reading of a scan follows that scan's sightings (D259); everything else keeps the
        # time it was given, because a backfill carries the past on purpose
        when = filed
        attribution = await attribution_at(when)
        ahead = _ahead_of_delivery(event, record.time)
        if ahead:
            outcome.clock_ahead += 1
            outcome.clock_ahead_seconds = max(outcome.clock_ahead_seconds, ahead)
        measurement = Measurement(
            time=when,
            device_id=device.id,
            project_id=attribution.project_id,
            entity_id=attribution.entity_id,
            data_source_id=event.data_source_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            metric_key=record.metric_key,
            canonical_key=key,
            valid=not ahead,
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
        # the same correction its sightings get, or one scan lands twice under two times (D259)
        when, behind = (
            _believed_time(event, record.time) if record.device_clock else (record.time, 0.0)
        )
        state = (
            {
                **record.state,
                "device_time": record.time.isoformat(),
                "clock_offset_s": round(behind),
            }
            if behind
            else record.state
        )
        attribution = await attribution_at(when)
        exists = await session.scalar(
            select(DeviceStateHistory.id).where(
                DeviceStateHistory.device_id == device.id, DeviceStateHistory.time == when
            )
        )
        if exists is not None:
            outcome.duplicates += 1
            continue
        row = DeviceStateHistory(
            time=when,
            device_id=device.id,
            project_id=attribution.project_id,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            state=state,
        )
        session.add(row)
        await session.flush()
        await _link_delivery(session, event, "state", row.id, row.time, first=True)
        outcome.created["states"] += 1
        if "port_3_tlv" in record.state:
            # the settings the device reported become the values Protect knows (D229)
            device_type = await session.get(DeviceType, device.device_type_id)
            outcome.settings_changed += await record_settings_frame(
                session,
                device.id,
                device_type.driver_key if device_type else "",
                record.state,
                source="ble" if event.acquisition_channel == AcquisitionChannel.WEBBLE else "frame",
                observed_at=record.time,
                source_event_id=event.id,
            )
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


async def _trap_entity(session: AsyncSession, attribution: Attribution) -> str | None:
    """The name of the Trap entity the device is on right now, or None when it is not on one."""
    if attribution.entity_id is None:
        return None
    from shared.models import EntityType

    name = await session.scalar(
        select(Entity.name)
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .where(Entity.id == attribution.entity_id, EntityType.key == TRAP_ENTITY_TYPE)
    )
    return str(name) if name is not None else None


async def _update_fence(
    session: AsyncSession,
    event: SourceEvent,
    device: Device,
    when: datetime,
    outcome: Outcome,
) -> None:
    """Recompute the fence line the device's entity stands on, and raise a FENCE_STATUS event
    on the line when a section changed level (decision D265). The event is put on the map in
    the middle of the stretch that changed, since an event is a point; the entity is the
    monitor that reported and the feature is named in the context."""
    from shared.models import FenceMonitor

    attribution = await resolve_attribution(session, device.id, when)
    if attribution.entity_id is None or attribution.project_id is None:
        return
    feature_id = await session.scalar(
        select(FenceMonitor.feature_id).where(FenceMonitor.entity_id == attribution.entity_id)
    )
    if feature_id is None:
        return
    now = utc_now()
    reading = await recompute_fence(session, feature_id, now)
    if reading is None or not reading.changed:
        return
    dedup = fingerprint([str(feature_id), now.isoformat(), FENCE_STATUS_EVENT])
    row = Event(
        time=now,
        project_id=attribution.project_id,
        entity_id=attribution.entity_id,
        device_id=device.id,
        event_type=FENCE_STATUS_EVENT,
        severity=SEVERITY_OF[changed_level(reading.changed)],
        title=status_title(reading.name, reading.changed, reading.monitors),
        geom=from_shape(Point(*reading.where), srid=4326),
        context={
            "feature_id": str(feature_id),
            "feature_name": reading.name,
            "level": reading.level,
            "section_level": changed_level(reading.changed),
            "sections": [s.as_dict() for s in reading.changed],
            "dedup": dedup,
        },
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
                "event_type": FENCE_STATUS_EVENT,
                "time": now.isoformat(),
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
            description=record.description,
            geom=(
                from_shape(Point(record.longitude, record.latitude), srid=4326)
                if record.latitude is not None and record.longitude is not None
                else None
            ),
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
    outcome: Outcome,
) -> None:
    now = utc_now()
    # a record from the future (decision D119) must not become the newest position, state or
    # last seen: it would block every real update until the clock is curated
    timely_positions = [
        p
        for p in records.positions
        if not _ahead_of_delivery(event, p.time) and p.time not in outcome.outlier_times
    ]
    timely_states = [s for s in records.states if not _ahead_of_delivery(event, s.time)]
    timely_measurements = [m for m in records.measurements if not _ahead_of_delivery(event, m.time)]
    timely_events = [e for e in records.events if not _ahead_of_delivery(event, e.time)]
    # an estimate of any kind is not a fix (D163): a proximity position counted as one would
    # make the device that was heard look as though it had fixed itself at the reader
    fixes = [p for p in timely_positions if p.record_type not in ESTIMATE_RECORD_TYPES]
    network = [p for p in timely_positions if p.record_type in ESTIMATE_RECORD_TYPES]
    newest_fix: DecodedPosition | None = max(fixes, key=lambda p: p.time, default=None)
    newest_network: DecodedPosition | None = max(network, key=lambda p: p.time, default=None)
    latest_state = max(timely_states, key=lambda s: s.time, default=None)
    latest_measurements: dict[str, DecodedMeasurement] = {}
    for m in timely_measurements:
        if (
            m.metric_key not in latest_measurements
            or m.time > latest_measurements[m.metric_key].time
        ):
            latest_measurements[m.metric_key] = m
    seen_at = max(
        [r.time for r in timely_positions + timely_measurements + timely_states + timely_events],
        default=event.network_received_at or event.ingested_at,
    )

    current = await session.get(DeviceCurrentState, device.id)
    if current is None:
        current = DeviceCurrentState(device_id=device.id, latest_state={})
        session.add(current)
    # read before this delivery's values overwrite it below: the movement rule needs the
    # activity the device had *before* now, to see two above the threshold in a row
    previous_activity = _stored_number(current, "activity")
    if current.last_seen_at is None or seen_at > current.last_seen_at:
        current.last_seen_at = seen_at
    latest_position = _apply_position(
        current, newest_fix, newest_network, device.location_source, device.location_fallback_hours
    )
    if latest_state is not None:
        current.latest_state = {**(current.latest_state or {}), **latest_state.state}
        if current.latest_state_time is None or latest_state.time > current.latest_state_time:
            current.latest_state_time = latest_state.time
        firmware = latest_state.state.get("firmware_version")
        if firmware is not None and str(firmware) != (device.firmware_version or ""):
            device.firmware_version = str(firmware)
    # The address is read from any state that carries it, not only the newest: it arrives in its
    # own message (an answer to a command) which is rarely the newest thing in a delivery.
    for state in timely_states:
        mac = state.state.get("ble_mac") if isinstance(state.state, dict) else None
        if mac and str(mac) != (device.ble_mac or ""):
            device.ble_mac = str(mac).lower()
    # The newest value per metric, for the health card and the lists (decision D104).
    kept = dict(current.latest_measurements or {})
    for key, measurement in latest_measurements.items():
        previous = kept.get(key)
        previous_time = (
            datetime.fromisoformat(str(previous["time"]))
            if isinstance(previous, dict) and previous.get("time")
            else None
        )
        if previous_time is None or measurement.time > previous_time:
            kept[key] = {"value": measurement.value, "time": measurement.time.isoformat()}
    if kept != (current.latest_measurements or {}):
        current.latest_measurements = kept
    if "battery_voltage" in latest_measurements and isinstance(
        latest_measurements["battery_voltage"].value, int | float
    ):
        current.battery_voltage = float(latest_measurements["battery_voltage"].value)
    # a device moved when two activity samples in a row cross the threshold, not one: a device
    # on a post drifts past any single threshold as its temperature changes
    activities = sorted(
        (m.time, float(m.value))
        for m in timely_measurements
        if m.metric_key == "activity" and isinstance(m.value, int | float)
    )
    moved_at = movement_times(activities, previous_activity)
    if moved_at and (current.last_movement_at is None or max(moved_at) > current.last_movement_at):
        current.last_movement_at = max(moved_at)
    reboots = [e.time for e in timely_events if e.event_type == "device_reset"]
    if reboots and (current.last_reset_at is None or max(reboots) > current.last_reset_at):
        current.last_reset_at = max(reboots)
    current.updated_at = now

    connectivity = await session.get(ConnectivityState, (device.id, event.data_source_id))
    if connectivity is None:
        connectivity = ConnectivityState(device_id=device.id, data_source_id=event.data_source_id)
        session.add(connectivity)
    connectivity.status = ConnectivityStatus.ONLINE
    received = event.network_received_at or event.ingested_at
    if event.event_type == "join":
        connectivity.last_join_at = received
    elif event.event_type in ("downlink_ack", "downlink_transmitted"):
        connectivity.last_downlink_at = received
    else:
        connectivity.last_uplink_at = received
    meta = event.provider_metadata or {}
    if meta.get("best_rssi") is not None:
        connectivity.last_rssi = float(meta["best_rssi"])
    if meta.get("best_snr") is not None:
        connectivity.last_snr = float(meta["best_snr"])
    if isinstance(meta.get("satellite_session"), dict):
        # the last Iridium session per device and source (decision D159), read by the health
        connectivity.attributes = {
            **(connectivity.attributes or {}),
            "satellite": dict(meta["satellite_session"]),
        }
    connectivity.updated_at = now

    # the entity the device is on is seen whenever the device reports, not only when it fixes
    # (Tim, 2026-09-19: a fence monitor with a place set by hand reads "last seen never" on
    # the map while its readings arrive every hour); a position moves it, a reading marks it
    candidate = newest_fix or newest_network
    attribution = attributions.get(candidate.time if candidate is not None else seen_at)
    if attribution is None and candidate is None:
        attribution = await resolve_attribution(session, device.id, seen_at)
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
        if candidate is not None:
            entity = await session.get(Entity, attribution.entity_id)
            moved = _apply_position(
                entity_state,
                newest_fix,
                newest_network,
                entity.location_source if entity else "device",
                entity.location_fallback_hours if entity else 24,
            )
            if moved is not None:
                entity_state.device_id = device.id
        if entity_state.last_seen_at is None or seen_at > entity_state.last_seen_at:
            entity_state.last_seen_at = seen_at
        entity_state.updated_at = now
    del latest_position


def _apply_position(
    state: DeviceCurrentState | EntityCurrentState,
    newest_fix: DecodedPosition | None,
    newest_network: DecodedPosition | None,
    location_source: str,
    fallback_hours: int,
) -> DecodedPosition | None:
    """What becomes the current position (decision D164). A device fix newer than the newest
    fix known always wins: it moves the position whatever a network estimate showed. A network
    location counts only when the setting says `network` (newest wins) or
    `device_else_network` and no device fix arrived within the fallback period before it.
    Returns the position that became current, if any."""
    moved: DecodedPosition | None = None
    if newest_fix is not None:
        newer_fix = state.latest_fix_time is None or newest_fix.time > state.latest_fix_time
        if newer_fix:
            state.latest_fix_time = newest_fix.time
        if newer_fix and (
            state.latest_position_time is None
            or newest_fix.time > state.latest_position_time
            or state.latest_position_kind in ESTIMATE_RECORD_TYPES
        ):
            _set_position(state, newest_fix, "device")
            moved = newest_fix
    if newest_network is not None and location_source != LocationSource.DEVICE:
        newer = (
            state.latest_position_time is None or newest_network.time > state.latest_position_time
        )
        stale_fix = state.latest_fix_time is None or (
            newest_network.time - state.latest_fix_time
        ) > timedelta(hours=max(0, fallback_hours))
        if newer and (location_source == LocationSource.NETWORK or stale_fix):
            _set_position(state, newest_network, NETWORK_RECORD_TYPE)
            moved = newest_network
    return moved


def _set_position(
    state: DeviceCurrentState | EntityCurrentState, position: DecodedPosition, kind: str
) -> None:
    state.latest_position_time = position.time
    state.latest_position = from_shape(Point(position.longitude, position.latitude), srid=4326)
    state.latest_position_kind = kind
    state.latest_accuracy_m = position.accuracy_m


async def publish_outcome(bus: RedisStreamsBus, outcome: Outcome) -> None:
    for topic, payload in outcome.messages:
        await bus.publish(
            topic, payload, trace_id=str(outcome.trace_id) if outcome.trace_id else None
        )
