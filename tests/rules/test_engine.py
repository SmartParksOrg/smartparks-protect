"""Rules through the real database and bus: measurement thresholds, geofence exits, schedule
rules, failure isolation, and the bus wiring of the worker."""

from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from protect_rules.engine import RuleCache, Scheduler, handle_measurements, handle_position
from protect_rules.main import build_worker
from shared.bus import Topic
from shared.enums import AlertStatus
from shared.models import (
    Alert,
    EntityCurrentState,
    Event,
    Measurement,
    Position,
    ProcessingTrace,
    RuleState,
)
from shared.rules.schema import TriggerKind
from tests.rules.conftest import create_rule, measurement_doc

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def _measurement(db, world, value: float, minutes: int, metric="battery_voltage"):
    when = T0 + timedelta(minutes=minutes)
    row = Measurement(
        time=when,
        ingested_at=when + timedelta(seconds=30),
        device_id=world.device.id,
        project_id=world.project.id,
        entity_id=world.entity.id,
        metric_key=metric,
        canonical_key=f"{world.device.id}|{metric}|{minutes}",
        value_num=value,
    )
    db.add(row)
    await db.commit()
    return row


async def _position(db, world, lon: float, lat: float, minutes: int, speed: float | None = None):
    when = T0 + timedelta(minutes=minutes)
    row = Position(
        time=when,
        device_id=world.device.id,
        project_id=world.project.id,
        entity_id=world.entity.id,
        canonical_key=f"{world.device.id}|gnss|{minutes}",
        geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
        speed_mps=speed,
    )
    db.add(row)
    await db.commit()
    return row


async def _events(db, world):
    return (
        await db.scalars(
            select(Event).where(Event.project_id == world.project.id).order_by(Event.time)
        )
    ).all()


async def test_battery_rule_creates_event_alert_trace_and_messages(db, bus, world):
    rule = await create_rule(db, world.project, measurement_doc(cooldown_seconds=0))
    cache = RuleCache()
    await cache.reload()
    ok = await _measurement(db, world, 3.6, 0)
    await handle_measurements(
        bus, cache, {"measurement_ids": [ok.id], "device_id": str(world.device.id)}
    )
    assert await _events(db, world) == []

    low = await _measurement(db, world, 3.1, 1)
    await handle_measurements(
        bus, cache, {"measurement_ids": [low.id], "device_id": str(world.device.id)}
    )
    events = await _events(db, world)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "BATTERY_LOW" and event.title == "Rhino 14 battery at 3.1 V"
    assert event.entity_id == world.entity.id and event.time == low.time
    assert event.context["rule_id"] == str(rule.id) and event.context["value"] == 3.1
    alert = await db.scalar(select(Alert).where(Alert.event_id == event.id))
    assert alert is not None and alert.status == AlertStatus.OPEN
    state = await db.get(EntityCurrentState, world.entity.id)
    await db.refresh(state)
    assert state.active_alert_count == 1
    trace = await db.get(ProcessingTrace, event.trace_id)
    assert trace is not None and trace.status == "success" and trace.compact
    assert [s["operation"] for s in trace.compact_steps] == [
        "rule matched",
        "conditions evaluated",
        "event created",
    ]
    await db.refresh(rule)
    assert rule.last_fired_at is not None and rule.last_error is None
    row = await db.get(RuleState, (rule.id, f"entity:{world.entity.id}"))
    assert row is not None and row.state["active"] is True

    # still low: no second event
    low2 = await _measurement(db, world, 3.0, 2)
    await handle_measurements(
        bus, cache, {"measurement_ids": [low2.id], "device_id": str(world.device.id)}
    )
    assert len(await _events(db, world)) == 1

    # the messages went out
    dead = await bus.list_dead(Topic.EVENT_CREATED)
    assert dead == []
    entries = await bus.redis.xrevrange(Topic.EVENT_CREATED, count=5)
    payloads = [e[1] for e in entries]
    assert any(str(event.id) in p["data"] for p in payloads)
    alerts = await bus.redis.xrevrange(Topic.ALERT_CREATED, count=5)
    assert any(str(alert.id) in e[1]["data"] for e in alerts)


async def test_geofence_exit_from_positions(db, bus, world):
    await create_rule(
        db,
        world.project,
        {
            "trigger": {"kind": "position"},
            "conditions": {"type": "spatial", "relation": "exit", "feature_type": "geofence"},
            "event": {"event_type": "GEOFENCE_EXIT", "title": "{entity} left {feature}"},
        },
    )
    cache = RuleCache()
    await cache.reload()
    inside = await _position(db, world, 31.5, -24.5, 0)
    outside = await _position(db, world, 33.0, -24.5, 1)
    for row in (inside, outside):
        await handle_position(
            bus,
            cache,
            {
                "position_id": row.id,
                "time": row.time.isoformat(),
                "project_id": str(world.project.id),
                "entity_id": str(world.entity.id),
                "device_id": str(world.device.id),
            },
        )
    events = await _events(db, world)
    assert [e.title for e in events] == ["Rhino 14 left Core area"]
    assert events[0].geom is not None


async def test_schedule_rule_no_data(db, bus, world):
    await create_rule(
        db,
        world.project,
        {
            "trigger": {"kind": "schedule", "every_seconds": 300},
            "conditions": {"type": "no_data", "for_seconds": 3600},
            "event": {"event_type": "NO_DATA", "title": "{entity} silent"},
        },
    )
    state = await db.get(EntityCurrentState, world.entity.id)
    state.last_seen_at = datetime.now(UTC) - timedelta(hours=3)
    await db.commit()
    cache = RuleCache()
    await cache.reload()
    scheduler = Scheduler(bus, cache)
    assert await scheduler.tick() == 1
    assert await scheduler.tick() == 0  # not due again
    events = await _events(db, world)
    assert [e.event_type for e in events] == ["NO_DATA"]


async def test_broken_rule_is_isolated_and_recorded(db, bus, world):
    broken = await create_rule(
        db,
        world.project,
        {
            "trigger": {"kind": "measurement", "metric_key": "battery_voltage"},
            "conditions": {"type": "near", "meters": 5},
            "event": {"event_type": "NEAR", "title": "x"},
        },
        name="broken",
    )
    good = await create_rule(db, world.project, measurement_doc(), name="good")
    cache = RuleCache()
    await cache.reload()
    low = await _measurement(db, world, 3.0, 0)
    await handle_measurements(
        bus, cache, {"measurement_ids": [low.id], "device_id": str(world.device.id)}
    )
    assert [e.event_type for e in await _events(db, world)] == ["BATTERY_LOW"]
    await db.refresh(broken)
    await db.refresh(good)
    assert broken.last_error and "near" in broken.last_error
    assert good.last_error is None
    failed = await db.scalar(
        select(ProcessingTrace).where(
            ProcessingTrace.root_object_id == str(broken.id), ProcessingTrace.status == "failed"
        )
    )
    assert failed is not None


async def test_worker_subscribes_to_the_domain_topics():
    worker = build_worker()
    assert [t for t, _ in worker._subscriptions] == [
        Topic.POSITION_CREATED,
        Topic.MEASUREMENT_CREATED,
        Topic.DEVICE_STATE_CHANGED,
    ]
    assert isinstance(worker.cache, RuleCache)  # type: ignore[attr-defined]


async def test_disabled_rules_are_not_loaded(db, world):
    disabled = await create_rule(db, world.project, measurement_doc(), enabled=False)
    cache = RuleCache()
    await cache.reload()
    loaded = await cache.rules(world.project.id, TriggerKind.MEASUREMENT)
    assert disabled.id not in {r.rule_id for r in loaded}
