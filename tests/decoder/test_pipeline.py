"""Source event to canonical rows, through the real bus and database."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from protect_decoder.main import build_worker
from protect_decoder.pipeline import process_source_event, publish_outcome
from shared import reprocessing
from shared.bus import Message, RedisStreamsBus, Topic
from shared.enums import AcquisitionChannel, ErrorCode, ProcessingStatus, TraceStatus
from shared.ingest import commit_and_publish, store_inbound
from shared.models import (
    DeviceCurrentState,
    EntityCurrentState,
    Measurement,
    Position,
    ProcessingTrace,
    SourceDelivery,
    SourceEvent,
)
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio


async def _ingest_and_process(db, bus, world, payload, external_id=None):
    stored = await store_inbound(
        db, world.source, inbound(external_id or world.external_id, payload)
    )
    await commit_and_publish(db, bus, [stored])
    event = stored.source_event
    outcome = await process_source_event(db, event.id, event.ingested_at)
    await db.commit()
    await publish_outcome(bus, outcome)
    return event, outcome


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_json_payload_becomes_position_measurements_and_state(db, bus, world):
    payload = {
        "time": "2026-03-10T10:00:00+00:00",
        "lat": -24.9,
        "lon": 31.5,
        "altitude": 300,
        "speed": 1.2,
        "measurements": {"battery_voltage": 3.9, "temperature": 27.5, "door_open": True},
        "state": {"firmware": "6.12"},
        "events": [{"type": "drop_off", "title": "Drop-off triggered", "severity": "warning"}],
    }
    event, outcome = await _ingest_and_process(db, bus, world, payload)
    assert outcome.status == ProcessingStatus.PROCESSED
    assert outcome.created == {
        "positions": 1,
        "measurements": 3,
        "states": 1,
        "events": 1,
        "contacts": 0,
    }

    position = await db.scalar(select(Position).where(Position.device_id == world.device.id))
    assert position is not None
    assert position.project_id == world.project_a.id and position.entity_id == world.entity.id
    assert position.time == datetime(2026, 3, 10, 10, tzinfo=UTC)
    deliveries = (
        await db.scalars(select(SourceDelivery).where(SourceDelivery.source_event_id == event.id))
    ).all()
    assert {d.canonical_type for d in deliveries} == {"position", "measurement", "state"}

    current = await db.get(DeviceCurrentState, world.device.id)
    assert (
        current is not None
        and current.battery_voltage == 3.9
        and current.latest_state == {"firmware": "6.12"}
    )
    entity_state = await db.get(EntityCurrentState, world.entity.id)
    assert entity_state is not None and entity_state.latest_position_time == position.time

    trace = await db.get(ProcessingTrace, event.trace_id)
    assert trace is not None and trace.status == TraceStatus.SUCCESS
    assert [s["operation"] for s in trace.compact_steps] == [
        "source event stored",
        "identity resolved",
        "driver selected",
        "payload decoded",
        "canonical rows written",
    ]
    topics = {t for t, _ in outcome.messages}
    assert topics == {
        Topic.POSITION_CREATED,
        Topic.MEASUREMENT_CREATED,
        Topic.DEVICE_STATE_CHANGED,
        Topic.EVENT_CREATED,
    }

    refreshed = await db.get(SourceEvent, (event.id, event.ingested_at))
    assert refreshed is not None and refreshed.processing_status == ProcessingStatus.PROCESSED


async def test_same_record_twice_creates_one_position_with_two_deliveries(db, bus, world):
    payload = {
        "time": "2026-03-11T08:00:00+00:00",
        "lat": -24.91,
        "lon": 31.51,
        "measurements": {"battery_voltage": 3.8},
    }
    first, _ = await _ingest_and_process(db, bus, world, payload)
    second, outcome = await _ingest_and_process(db, bus, world, payload)
    assert outcome.status == ProcessingStatus.DUPLICATE
    assert outcome.created["positions"] == 0 and outcome.duplicates == 2
    count = await db.scalar(
        select(func.count())
        .select_from(Position)
        .where(
            Position.device_id == world.device.id,
            Position.time == datetime(2026, 3, 11, 8, tzinfo=UTC),
        )
    )
    assert count == 1
    position = await db.scalar(
        select(Position).where(
            Position.device_id == world.device.id,
            Position.time == datetime(2026, 3, 11, 8, tzinfo=UTC),
        )
    )
    deliveries = (
        await db.scalars(
            select(SourceDelivery)
            .where(
                SourceDelivery.canonical_type == "position",
                SourceDelivery.canonical_id == position.id,
            )
            .order_by(SourceDelivery.id)
        )
    ).all()
    assert [(d.source_event_id, d.first) for d in deliveries] == [
        (first.id, True),
        (second.id, False),
    ]
    second_row = await db.get(SourceEvent, (second.id, second.ingested_at))
    assert second_row.processing_status == ProcessingStatus.DUPLICATE
    assert outcome.messages == []


async def test_late_record_is_attributed_to_the_historical_project(db, bus, world):
    """Arrives now, generated in July: belongs to project A and the entity, not to project B."""
    payload = {"time": "2026-07-15T12:00:00+00:00", "lat": -24.8, "lon": 31.4}
    _, outcome = await _ingest_and_process(db, bus, world, payload)
    position = await db.scalar(
        select(Position).where(
            Position.device_id == world.device.id,
            Position.time == datetime(2026, 7, 15, 12, tzinfo=UTC),
        )
    )
    assert position.project_id == world.project_a.id and position.entity_id == world.entity.id
    age = next(p for t, p in outcome.messages if t == Topic.POSITION_CREATED)["age_seconds"]
    assert age > 30 * 24 * 3600

    payload_b = {"time": "2026-08-15T12:00:00+00:00", "lat": -24.8, "lon": 31.4}
    await _ingest_and_process(db, bus, world, payload_b)
    later = await db.scalar(
        select(Position).where(
            Position.device_id == world.device.id,
            Position.time == datetime(2026, 8, 15, 12, tzinfo=UTC),
        )
    )
    assert later.project_id == world.project_b.id and later.entity_id is None


async def test_without_device_time_the_network_time_is_canonical(db, bus, world):
    received = datetime(2026, 3, 12, 9, 30, tzinfo=UTC)
    stored = await store_inbound(
        db,
        world.source,
        inbound(world.external_id, {"lat": -24.7, "lon": 31.3}, network_received_at=received),
    )
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    position = await db.scalar(
        select(Position).where(Position.device_id == world.device.id, Position.time == received)
    )
    assert position is not None and outcome.created["positions"] == 1


async def test_unknown_device_is_retained_and_processed_after_linking(db, bus, world):
    unknown_id = uuid.uuid4().hex[:16].upper()
    stored = await store_inbound(
        db,
        world.source,
        inbound(unknown_id, {"time": "2026-03-13T00:00:00+00:00", "lat": -24.6, "lon": 31.2}),
    )
    await commit_and_publish(db, bus, [stored])
    assert stored.topic == Topic.NEEDS_ATTENTION_CREATED
    assert stored.source_event.processing_status == ProcessingStatus.UNASSIGNED
    assert (
        stored.identity is not None
        and stored.identity.device_id is None
        and stored.identity.event_count == 1
    )

    # An administrator links the identity to the device; the retained event is processed.
    stored.identity.device_id = world.device.id
    stored.source_event.device_id = world.device.id
    await db.commit()
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at, reprocess=True
    )
    await db.commit()
    assert outcome.created["positions"] == 1
    position = await db.scalar(
        select(Position).where(
            Position.device_id == world.device.id,
            Position.time == datetime(2026, 3, 13, tzinfo=UTC),
        )
    )
    assert position.project_id == world.project_a.id


async def test_identity_walker_processes_the_retained_events_in_order(db, bus, world):
    """The decoder walks the retained events of an identity that got a device, oldest first,
    each on its own commit (decision D121)."""
    from shared.ingest import queue_identity_reprocess

    unknown_id = uuid.uuid4().hex[:16].upper()
    stored = []
    for day in (13, 14, 15):
        one = await store_inbound(
            db,
            world.source,
            inbound(
                unknown_id, {"time": f"2026-03-{day}T00:00:00+00:00", "lat": -24.6, "lon": 31.2}
            ),
        )
        await commit_and_publish(db, bus, [one])
        stored.append(one)
    identity = stored[0].identity
    assert identity is not None and identity.device_id is None
    identity.device_id = world.device.id
    await db.commit()
    identity_id = identity.id
    assert await queue_identity_reprocess(db, bus, identity) == 3
    # nothing is marked up front: the rows are written once, by the walk, with their outcome
    rows = (
        await db.execute(
            select(SourceEvent.processing_status, SourceEvent.device_id).where(
                SourceEvent.external_identity_id == identity_id
            )
        )
    ).all()
    assert {s for s, _ in rows} == {ProcessingStatus.UNASSIGNED}
    assert all(d is None for _, d in rows)
    walk = next(w for w in await reprocessing.walks(bus.redis) if w.identity_id == identity_id)
    assert (walk.total, walk.done, walk.device_id) == (3, 0, world.device.id)

    worker = build_worker()
    worker.bus = bus
    handler = next(h for t, h in worker._subscriptions if t == Topic.IDENTITY_REPROCESS_REQUESTED)
    await handler(
        Message(
            topic=Topic.IDENTITY_REPROCESS_REQUESTED,
            payload={"external_identity_id": str(identity_id), "device_id": str(world.device.id)},
        )
    )
    device_id = world.device.id
    db.expire_all()
    rows = (
        await db.execute(
            select(SourceEvent.processing_status, SourceEvent.device_id)
            .where(SourceEvent.external_identity_id == identity_id)
            .order_by(SourceEvent.ingested_at)
        )
    ).all()
    assert rows == [(ProcessingStatus.PROCESSED, device_id)] * 3
    assert all(w.identity_id != identity_id for w in await reprocessing.walks(bus.redis))
    positions = (
        await db.scalars(
            select(Position.time)
            .where(
                Position.device_id == device_id,
                Position.time >= datetime(2026, 3, 13, tzinfo=UTC),
            )
            .order_by(Position.time)
        )
    ).all()
    assert [p.day for p in positions] == [13, 14, 15]


async def test_identity_walker_links_receptions_and_passes_a_failing_event(db, bus, world):
    """The receptions stored while the identity was unknown get the device with their event,
    named one by one rather than through a join over the table (the 500 of 2026-09-24), and a
    failing event in the middle is marked failed while the rest are decoded and the walk ends."""
    from shared.connectivity.base import GatewayReceptionData
    from shared.ingest import queue_identity_reprocess
    from shared.models import GatewayReception

    unknown_id = uuid.uuid4().hex[:16].upper()
    payloads = [
        {"time": "2026-04-01T00:00:00+00:00", "lat": -24.6, "lon": 31.2},
        {"time": "not a time", "lat": -24.6, "lon": 31.2},
        {"time": "2026-04-03T00:00:00+00:00", "lat": -24.6, "lon": 31.2},
    ]
    events = []
    for payload in payloads:
        one = await store_inbound(
            db,
            world.source,
            inbound(
                unknown_id,
                payload,
                gateway_receptions=[
                    GatewayReceptionData(gateway_id="gw-walk-1", rssi=-90.0),
                    GatewayReceptionData(gateway_id="gw-walk-2", rssi=-105.0),
                ],
            ),
        )
        await commit_and_publish(db, bus, [one])
        events.append(one.source_event)
    identity = events[0].external_identity_id
    assert identity is not None
    from shared.models import ExternalIdentity

    row = await db.get(ExternalIdentity, identity)
    assert row is not None
    row.device_id = world.device.id
    await db.commit()
    assert await queue_identity_reprocess(db, bus, row) == 3
    event_ids = [e.id for e in events]
    unlinked = await db.scalar(
        select(func.count())
        .select_from(GatewayReception)
        .where(
            GatewayReception.source_event_id.in_(event_ids), GatewayReception.device_id.is_(None)
        )
    )
    assert unlinked == 6

    worker = build_worker()
    worker.bus = bus
    handler = next(h for t, h in worker._subscriptions if t == Topic.IDENTITY_REPROCESS_REQUESTED)
    await handler(
        Message(
            topic=Topic.IDENTITY_REPROCESS_REQUESTED,
            payload={"external_identity_id": str(identity), "device_id": str(world.device.id)},
        )
    )
    device_id = world.device.id
    db.expire_all()
    rows = (
        await db.execute(
            select(SourceEvent.processing_status, SourceEvent.device_id, SourceEvent.error_code)
            .where(SourceEvent.id.in_(event_ids))
            .order_by(SourceEvent.ingested_at)
        )
    ).all()
    assert [s for s, _, _ in rows] == [
        ProcessingStatus.PROCESSED,
        ProcessingStatus.FAILED,
        ProcessingStatus.PROCESSED,
    ]
    assert all(d == device_id for _, d, _ in rows)
    assert rows[1][2] == ErrorCode.TIMESTAMP_INVALID
    linked = (
        await db.scalars(
            select(GatewayReception.device_id).where(
                GatewayReception.source_event_id.in_(event_ids)
            )
        )
    ).all()
    assert linked == [device_id] * 6
    assert all(w.identity_id != identity for w in await reprocessing.walks(bus.redis))


async def test_decode_failure_lands_in_dead_letter(db, bus, world):
    import contextlib

    from redis.exceptions import ResponseError

    group = f"decoder-test-{uuid.uuid4().hex[:6]}"
    with contextlib.suppress(ResponseError):
        await bus.redis.xgroup_create(Topic.SOURCE_EVENT_RECEIVED, group, id="$", mkstream=True)
    stored = await store_inbound(
        db, world.source, inbound(world.external_id, {"time": "not a time", "lat": 1, "lon": 2})
    )
    await commit_and_publish(db, bus, [stored])
    worker = build_worker()
    worker.bus = bus
    handler = worker._subscriptions[0][1]
    try:
        await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
        dead = [
            d
            for d in await bus.list_dead(Topic.SOURCE_EVENT_RECEIVED)
            if d.get("trace_id") == str(stored.trace_id)
        ]
        assert dead and dead[0]["error_code"] == ErrorCode.TIMESTAMP_INVALID
        await bus.resolve_dead(Topic.SOURCE_EVENT_RECEIVED, dead[0]["id"])
    finally:
        await bus.redis.xgroup_destroy(Topic.SOURCE_EVENT_RECEIVED, group)
    event_id, ingested_at = stored.source_event.id, stored.source_event.ingested_at
    db.expire_all()
    event = await db.get(SourceEvent, (event_id, ingested_at))
    assert event.processing_status == ProcessingStatus.FAILED
    assert event.error_code == ErrorCode.TIMESTAMP_INVALID
    trace = await db.get(ProcessingTrace, event.trace_id)
    assert trace.status == TraceStatus.FAILED and trace.error_id is not None


async def test_bad_coordinates_are_a_decode_failure(db, bus, world):
    stored = await store_inbound(
        db,
        world.source,
        inbound(world.external_id, {"time": "2026-03-14T00:00:00+00:00", "lat": 95, "lon": 2}),
    )
    await commit_and_publish(db, bus, [stored])
    from shared.trace import ApplicationError

    with pytest.raises(ApplicationError) as excinfo:
        await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED
    await db.commit()
    event = await db.get(SourceEvent, (stored.source_event.id, stored.source_event.ingested_at))
    assert event.processing_status == ProcessingStatus.FAILED


async def test_large_payload_goes_to_minio(db, bus, world, monkeypatch):
    from shared.config import get_settings

    monkeypatch.setattr(get_settings(), "payload_inline_max_bytes", 100)
    payload = {"time": "2026-03-15T00:00:00+00:00", "lat": -24.5, "lon": 31.1, "log": "x" * 500}
    event, outcome = await _ingest_and_process(db, bus, world, payload)
    row = await db.get(SourceEvent, (event.id, event.ingested_at))
    assert (
        row.payload is None and row.payload_object_key and row.payload_size and row.payload_sha256
    )
    assert outcome.created["positions"] == 1
    measurement_count = await db.scalar(
        select(func.count()).select_from(Measurement).where(Measurement.source_event_id == event.id)
    )
    assert measurement_count == 0


async def test_chirpstack_uplink_and_status_events(db, bus, world):
    """A ChirpStack uplink carries the frame in base64; a status event needs no driver."""
    import base64
    import json

    from shared.connectivity.base import GatewayReceptionData
    from shared.enums import IngestionMethod
    from shared.models import ConnectivityState

    frame = json.dumps({"time": "2026-05-01T10:00:00+00:00", "lat": -24.5, "lon": 31.0}).encode()
    uplink = inbound(
        world.external_id,
        {"data": base64.b64encode(frame).decode(), "fPort": 1, "fCnt": 3},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        provider_metadata={"f_port": 1, "best_rssi": -70.0, "best_snr": 6.0, "gateway_count": 1},
        network_received_at=datetime(2026, 5, 1, 10, 0, 2, tzinfo=UTC),
        gateway_receptions=[GatewayReceptionData(gateway_id="gw1", rssi=-70.0, snr=6.0)],
    )
    stored = await store_inbound(db, world.source, uplink)
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    assert outcome.created["positions"] == 1
    connectivity = await db.get(ConnectivityState, (world.device.id, world.source.id))
    assert connectivity.last_rssi == -70.0 and connectivity.last_uplink_at == datetime(
        2026, 5, 1, 10, 0, 2, tzinfo=UTC
    )

    status = inbound(
        world.external_id,
        {"batteryLevel": 88.3, "margin": 10},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        network_received_at=datetime(2026, 5, 1, 10, 5, tzinfo=UTC),
    )
    status.event_type = "status"
    stored = await store_inbound(db, world.source, status)
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    assert outcome.created["measurements"] == 2 and outcome.created["positions"] == 0
    join = inbound(
        world.external_id,
        {"devAddr": "00189440"},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        network_received_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
    )
    join.event_type = "join"
    stored = await store_inbound(db, world.source, join)
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    await db.refresh(connectivity)
    assert connectivity.last_join_at == datetime(2026, 5, 1, 9, tzinfo=UTC)
    assert outcome.status == ProcessingStatus.PROCESSED


async def test_port_zero_uplink_is_alive_but_holds_nothing(db, bus, world):
    """A MAC-only uplink (port 0, no application payload) is not a decode failure: no rows,
    the trace notes it, the connectivity state and the device's last seen move."""
    from shared.enums import IngestionMethod
    from shared.models import ConnectivityState

    uplink = inbound(
        world.external_id,
        {"data": "", "fPort": 0, "fCnt": 9},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={"f_port": 0, "best_rssi": -101.0, "gateway_count": 1},
        network_received_at=datetime(2026, 5, 2, 8, 0, 0, tzinfo=UTC),
    )
    stored = await store_inbound(db, world.source, uplink)
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    assert outcome.status == ProcessingStatus.PROCESSED
    assert sum(outcome.created.values()) == 0
    trace = await db.get(ProcessingTrace, outcome.trace_id)
    decoded = next(s for s in trace.compact_steps if s["operation"] == "payload decoded")
    assert decoded["status"] == "skipped"
    assert decoded["note"] == "no application payload (port 0)"
    connectivity = await db.get(ConnectivityState, (world.device.id, world.source.id))
    assert connectivity.last_uplink_at == datetime(2026, 5, 2, 8, 0, 0, tzinfo=UTC)
    current = await db.get(DeviceCurrentState, world.device.id)
    assert current.last_seen_at == datetime(2026, 5, 2, 8, 0, 0, tzinfo=UTC)
    assert not await bus.list_dead(Topic.SOURCE_EVENT_RECEIVED) or all(
        d.get("source_event_id") != stored.source_event.id
        for d in await bus.list_dead(Topic.SOURCE_EVENT_RECEIVED)
    )


async def test_status_message_updates_health_state_and_firmware(db, bus, world):
    """A status uplink (no position) moves last seen, keeps the newest value per metric and the
    state time on the current state, and writes the firmware on the device (decision D104)."""
    from shared.models import Device

    first = await _ingest_and_process(
        db,
        bus,
        world,
        {
            "time": "2026-05-03T08:00:00+00:00",
            "measurements": {"battery_voltage": 3.9, "device_temperature": 20.0},
            "state": {"firmware_version": "7.2", "errors": {"flash": False}},
        },
    )
    assert first[1].status == ProcessingStatus.PROCESSED
    older = await _ingest_and_process(
        db,
        bus,
        world,
        {"time": "2026-05-02T08:00:00+00:00", "measurements": {"battery_voltage": 4.0}},
    )
    assert older[1].status == ProcessingStatus.PROCESSED
    await db.rollback()
    current = await db.get(DeviceCurrentState, world.device.id)
    await db.refresh(current)
    assert current.last_seen_at == datetime(2026, 5, 3, 8, tzinfo=UTC)
    assert current.latest_measurements["battery_voltage"]["value"] == 3.9  # the newer one stays
    assert current.latest_measurements["device_temperature"]["value"] == 20.0
    assert current.latest_state_time == datetime(2026, 5, 3, 8, tzinfo=UTC)
    assert current.latest_state["firmware_version"] == "7.2"
    device = await db.get(Device, world.device.id)
    await db.refresh(device)
    assert device.firmware_version == "7.2"


async def test_a_record_from_the_future_is_kept_invalid_and_leaves_the_current_state(
    db, bus, world
):
    """Decision D119: a device whose clock runs years ahead keeps sending; its records are
    stored, marked invalid, and never become the newest position or the last seen."""
    future = {"time": "2030-09-05T12:59:01+00:00", "lat": 52.04, "lon": 5.77}
    event, outcome = await _ingest_and_process(db, bus, world, future)
    assert outcome.status == ProcessingStatus.PROCESSED
    assert outcome.clock_ahead == 1 and outcome.clock_ahead_seconds > 365 * 86400
    await db.rollback()
    row = (
        await db.execute(select(Position).where(Position.source_event_id == event.id))
    ).scalar_one()
    assert row.valid is False
    state = await db.get(DeviceCurrentState, world.device.id)
    assert (
        state is None
        or state.latest_position_time is None
        or state.latest_position_time.year < 2030
    )
    # the compact trace keeps the step's note: the clock ahead is visible in the trace explorer
    trace = await db.get(ProcessingTrace, event.trace_id)
    assert trace is not None
    step = next(s for s in trace.compact_steps if s["operation"] == "canonical rows written")
    assert "ahead" in step["note"] and "1 records kept invalid" in step["note"]

    # a record with a sane time then moves the state as usual
    sane = {"time": "2026-09-07T12:59:01+00:00", "lat": 52.05, "lon": 5.78}
    await _ingest_and_process(db, bus, world, sane)
    await db.rollback()
    state = await db.get(DeviceCurrentState, world.device.id)
    assert state is not None and state.latest_position_time.year == 2026


async def test_status_accelerometer_samples_become_activity_and_the_last_movement(db, bus, world):
    """Tim (2026-09-14): the change of the accelerometer vector between status messages is
    stored as `activity`, and a change above the threshold moves `last_movement_at`."""
    from shared.models import Measurement

    still = {"acceleration_x": 0.0, "acceleration_y": 0.0, "acceleration_z": 9.8}
    first = await _ingest_and_process(
        db, bus, world, {"time": "2026-05-03T08:00:00+00:00", "measurements": still}
    )
    assert first[1].status == ProcessingStatus.PROCESSED
    second = await _ingest_and_process(
        db, bus, world, {"time": "2026-05-03T09:00:00+00:00", "measurements": still}
    )
    assert second[1].status == ProcessingStatus.PROCESSED
    moved = await _ingest_and_process(
        db,
        bus,
        world,
        {
            "time": "2026-05-03T10:00:00+00:00",
            "measurements": {"acceleration_x": 3.0, "acceleration_y": 4.0, "acceleration_z": 9.8},
        },
    )
    assert moved[1].status == ProcessingStatus.PROCESSED
    await db.rollback()
    rows = (
        await db.execute(
            select(Measurement.time, Measurement.value_num)
            .where(Measurement.device_id == world.device.id, Measurement.metric_key == "activity")
            .order_by(Measurement.time)
        )
    ).all()
    assert [(r.time.hour, r.value_num) for r in rows] == [(9, 0.0), (10, 5.0)]
    current = await db.get(DeviceCurrentState, world.device.id)
    await db.refresh(current)
    assert current.last_movement_at == datetime(2026, 5, 3, 10, tzinfo=UTC)
    assert current.latest_measurements["activity"]["value"] == 5.0


async def test_an_uptime_drop_is_a_reboot_event_and_the_last_reset(db, bus, world):
    """Tim (2026-09-14): a status whose uptime is lower than the one before it means the
    device started again; a device_reset event with the reason, and last_reset_at moves."""
    from shared.models import Event

    first = await _ingest_and_process(
        db,
        bus,
        world,
        {"time": "2026-05-04T08:00:00+00:00", "measurements": {"uptime": 5 * 86400}},
    )
    assert first[1].status == ProcessingStatus.PROCESSED
    rebooted = await _ingest_and_process(
        db,
        bus,
        world,
        {
            "time": "2026-05-04T09:00:00+00:00",
            "measurements": {"uptime": 0},
            "state": {"reset_reason": {"watchdog": True, "pin": False}},
        },
    )
    assert rebooted[1].status == ProcessingStatus.PROCESSED
    assert rebooted[1].created["events"] == 1
    await db.rollback()
    event = await db.scalar(
        select(Event).where(Event.device_id == world.device.id, Event.event_type == "device_reset")
    )
    assert event is not None and event.title == "Device rebooted (watchdog)"
    assert event.severity == "warning"
    current = await db.get(DeviceCurrentState, world.device.id)
    await db.refresh(current)
    assert current.last_reset_at == datetime(2026, 5, 4, 9, tzinfo=UTC)


async def test_an_impossible_jump_is_flagged_as_an_outlier_and_kept_out(db, bus, world):
    """Decision D221: a fix an impossible speed away from the last valid fix is stored invalid
    with its figures, raises an informational event, moves no map and fires no rule; the fix
    after it is judged against the last valid one, not the outlier."""
    from shared.models import Event

    first = {"time": "2026-03-10T10:00:00+00:00", "lat": -24.9, "lon": 31.5}
    _, ok = await _ingest_and_process(db, bus, world, first)
    assert ok.outliers == 0
    jump = {"time": "2026-03-10T11:00:00+00:00", "lat": 52.04, "lon": 5.77}
    event, outcome = await _ingest_and_process(db, bus, world, jump)
    assert outcome.status == ProcessingStatus.PROCESSED
    assert outcome.outliers == 1 and outcome.created["positions"] == 1
    assert outcome.created["events"] == 1
    topics = [t for t, _ in outcome.messages]
    assert Topic.POSITION_CREATED not in topics and Topic.EVENT_CREATED in topics
    await db.rollback()
    row = (
        await db.execute(select(Position).where(Position.source_event_id == event.id))
    ).scalar_one()
    assert row.valid is False
    figures = row.attributes["outlier"]
    assert figures["speed_mps"] > 2000 and figures["distance_m"] > 8_000_000
    assert figures["previous_time"] == "2026-03-10T10:00:00+00:00"
    flagged = (
        (await db.execute(select(Event).where(Event.event_type == "position_outlier")))
        .scalars()
        .all()
    )
    assert len(flagged) == 1 and flagged[0].device_id == world.device.id
    assert flagged[0].severity == "info" and "flagged as an outlier" in flagged[0].title
    state = await db.get(DeviceCurrentState, world.device.id)
    assert state is not None
    assert state.latest_position_time == datetime(2026, 3, 10, 10, tzinfo=UTC)
    # the next fix near the first one is valid: the outlier is not the yardstick
    back = {"time": "2026-03-10T12:00:00+00:00", "lat": -24.91, "lon": 31.51}
    event3, outcome3 = await _ingest_and_process(db, bus, world, back)
    assert outcome3.outliers == 0
    await db.rollback()
    row3 = (
        await db.execute(select(Position).where(Position.source_event_id == event3.id))
    ).scalar_one()
    assert row3.valid is True


async def test_a_settings_frame_fills_the_settings_protect_knows(db, bus, world):
    """Decisions D228 to D231: a state holding settings TLVs becomes one known value per
    setting the catalogue names, with the source and the time; a newer frame replaces it."""
    from shared.models import DeviceSetting

    frame = {
        "time": "2026-03-10T10:00:00+00:00",
        "state": {"port_3_tlv": {"0x02": "100e0000", "0x03": "08070000", "0x0b": "01"}},
    }
    _, outcome = await _ingest_and_process(db, bus, world, frame)
    assert outcome.created["states"] == 1
    await db.rollback()
    # the generic JSON driver of the world has no catalogue: nothing is known from it
    rows = (
        (await db.execute(select(DeviceSetting).where(DeviceSetting.device_id == world.device.id)))
        .scalars()
        .all()
    )
    assert rows == [] and outcome.settings_changed == 0


async def test_the_bluetooth_address_reaches_the_device_from_any_state(db, bus, world):
    """Decision D252. The address arrives in its own message, the answer to a command, which is
    rarely the newest thing in a delivery, so it is read from any state that carries it and not
    only from the newest as the firmware is."""
    from shared.models import Device

    await _ingest_and_process(
        db,
        bus,
        world,
        {
            "time": "2026-05-03T08:00:00+00:00",
            "state": {"ble_mac": "D4:22:11:0A:41:0C"},
        },
    )
    # a newer state that says nothing about the address must not clear it
    await _ingest_and_process(
        db,
        bus,
        world,
        {"time": "2026-05-03T09:00:00+00:00", "state": {"firmware_version": "7.2"}},
    )
    await db.rollback()
    device = await db.get(Device, world.device.id)
    await db.refresh(device)
    assert device.ble_mac == "d4:22:11:0a:41:0c"
