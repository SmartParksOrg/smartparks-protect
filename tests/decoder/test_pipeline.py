"""Source event to canonical rows, through the real bus and database."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from protect_decoder.main import build_worker
from protect_decoder.pipeline import process_source_event, publish_outcome
from shared.bus import RedisStreamsBus, Topic
from shared.enums import ErrorCode, ProcessingStatus, TraceStatus
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
    assert outcome.created == {"positions": 1, "measurements": 3, "states": 1, "events": 1}

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
