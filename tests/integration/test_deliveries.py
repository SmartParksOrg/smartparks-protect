"""Delivery rows: filters, idempotent enqueue, attempts on the retry schedule, backfill."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from shared.enums import DeliveryOrigin, DeliveryStatus, TraceStatus
from shared.integrations.deliveries import (
    MAX_ATTEMPTS,
    attempt,
    backfill,
    backoff_seconds,
    delivery_counts,
    enqueue,
    event_ref,
    load_item,
    matches,
    measurement_ref,
    requeue,
)
from shared.integrations.deliveries import _position_ref as position_ref
from shared.models import IntegrationDelivery, ProcessingTrace
from tests.integration.conftest import T0

pytestmark = pytest.mark.asyncio


def test_backoff_grows_and_caps():
    assert backoff_seconds(1) == 30
    assert backoff_seconds(2) == 60
    assert backoff_seconds(5) == 480
    assert backoff_seconds(30) == 6 * 3600
    assert sum(backoff_seconds(n) for n in range(1, MAX_ATTEMPTS + 1)) > 2 * 86_400


async def test_filters(db, world):
    integration = world.integration
    assert matches(integration, position_ref(world.position))
    assert matches(integration, event_ref(world.event))
    assert not matches(integration, measurement_ref(world.measurement))  # not in object_types
    integration.object_types = ["measurement"]
    assert not matches(integration, measurement_ref(world.measurement))  # fake cannot receive it
    integration.object_types = ["position", "event"]
    integration.entity_ids = ["00000000-0000-0000-0000-000000000000"]
    assert not matches(integration, position_ref(world.position))
    integration.entity_ids = [str(world.entity.id)]
    assert matches(integration, position_ref(world.position))
    integration.event_types = ["BATTERY_LOW"]
    assert not matches(integration, event_ref(world.event))
    integration.event_types = []
    integration.min_severity = "critical"
    assert not matches(integration, event_ref(world.event))
    integration.min_severity = "info"
    await db.rollback()


async def test_enqueue_is_idempotent_and_honours_age(db, world):
    refs = [position_ref(world.position), event_ref(world.event)]
    first = await enqueue(db, [world.integration], refs)
    second = await enqueue(db, [world.integration], refs)
    await db.commit()
    assert first == 2 and second == 0
    rows = (
        await db.scalars(
            select(IntegrationDelivery).where(
                IntegrationDelivery.integration_id == world.integration.id
            )
        )
    ).all()
    assert {(r.object_type, r.status) for r in rows} == {
        ("position", "queued"),
        ("event", "queued"),
    }
    assert all(r.next_attempt_at is not None and r.origin == "live" for r in rows)

    # a tight freshness bound: the stale position is not queued, the stale event is recorded
    # as skipped so the log says why
    world.integration.max_object_age_seconds = 60
    await db.execute(
        IntegrationDelivery.__table__.delete().where(
            IntegrationDelivery.integration_id == world.integration.id
        )
    )
    queued = await enqueue(db, [world.integration], refs, now=T0 + timedelta(days=2))
    await db.commit()
    rows = (
        await db.scalars(
            select(IntegrationDelivery).where(
                IntegrationDelivery.integration_id == world.integration.id
            )
        )
    ).all()
    assert queued == 1 and [(r.object_type, r.status) for r in rows] == [("event", "skipped")]
    assert "freshness bound" in (rows[0].error_message or "")


async def _one(db, world, ref, **extra):
    await enqueue(db, [world.integration], [ref], **extra)
    await db.commit()
    return await db.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.integration_id == world.integration.id,
            IntegrationDelivery.object_id == ref.object_id,
        )
    )


async def test_attempt_sends_and_records(db, world, fake_connector):
    delivery = await _one(db, world, position_ref(world.position))
    status = await attempt(db, delivery, world.integration)
    await db.commit()
    assert status == DeliveryStatus.SENT
    assert delivery.attempts == 1 and delivery.delivered_at is not None
    assert delivery.next_attempt_at is None and delivery.external_id == "ext-1"
    assert delivery.request == {
        "type": "position",
        "id": str(world.position.id),
        "entity": "Rhino 14",
    }
    assert delivery.response == {"ok": True}
    assert fake_connector.delivered[0]["token"] == "secret"
    assert fake_connector.delivered[0]["delivery_id"] == str(delivery.id)
    assert world.integration.last_delivery_at is not None
    trace = await db.get(ProcessingTrace, delivery.trace_id)
    assert trace is not None and trace.status == TraceStatus.SUCCESS
    assert [s["operation"] for s in trace.compact_steps] == [
        "object loaded",
        "rendered for Fake target",
        "delivered to Fake target",
    ]


async def test_attempt_transient_then_permanent(db, world, fake_connector):
    delivery = await _one(db, world, event_ref(world.event))
    now = datetime.now(UTC)
    fake_connector.mode = "transient"
    assert await attempt(db, delivery, world.integration, now=now) == DeliveryStatus.QUEUED
    assert delivery.attempts == 1
    assert delivery.next_attempt_at == now + timedelta(seconds=30)
    assert "retry in 30 s" in (delivery.error_message or "")
    assert world.integration.last_error == "target down"
    fake_connector.mode = "transient"
    assert await attempt(db, delivery, world.integration, now=now) == DeliveryStatus.QUEUED
    assert delivery.next_attempt_at == now + timedelta(seconds=60)
    fake_connector.mode = "permanent"
    assert await attempt(db, delivery, world.integration, now=now) == DeliveryStatus.FAILED
    assert delivery.next_attempt_at is None and delivery.error_message == "target refused"
    await db.commit()
    trace = await db.get(ProcessingTrace, delivery.trace_id)
    assert trace is not None and trace.status == TraceStatus.FAILED
    # manual retry puts it back for an immediate attempt and the attempt count stays
    requeue(delivery, now)
    fake_connector.mode = "ok"
    assert delivery.status == DeliveryStatus.QUEUED and delivery.origin == DeliveryOrigin.RETRY
    assert await attempt(db, delivery, world.integration, now=now) == DeliveryStatus.SENT
    assert delivery.attempts == 4
    await db.commit()


async def test_attempt_gives_up_after_max_attempts(db, world, fake_connector):
    delivery = await _one(db, world, position_ref(world.position))
    delivery.attempts = MAX_ATTEMPTS - 1
    fake_connector.mode = "crash"
    assert await attempt(db, delivery, world.integration) == DeliveryStatus.FAILED
    assert delivery.attempts == MAX_ATTEMPTS and "gave up" in (delivery.error_message or "")
    await db.commit()


async def test_attempt_skipped_and_missing_object(db, world, fake_connector):
    delivery = await _one(db, world, position_ref(world.position))
    fake_connector.mode = "skip"
    assert await attempt(db, delivery, world.integration) == DeliveryStatus.SKIPPED
    assert delivery.error_message == "nothing to send"
    await db.commit()
    ref = event_ref(world.event)
    ref.object_id = "00000000-0000-0000-0000-000000000001"
    gone = await _one(db, world, ref)
    fake_connector.mode = "ok"
    assert await attempt(db, gone, world.integration) == DeliveryStatus.SKIPPED
    await db.commit()


async def test_load_item_names_and_fallback_location(db, world):
    delivery = await _one(db, world, event_ref(world.event))
    item = await load_item(db, delivery)
    assert item is not None
    assert item.entity_name == "Rhino 14" and item.entity_type_label == "Rhino"
    assert item.device_name == world.device.name and item.project_name == world.project.name
    assert item.data["event_type"] == "GEOFENCE_EXIT" and item.data["severity"] == "warning"
    # the event has no point of its own: the entity's latest position stands in
    assert item.location == (-24.9, 31.5) and item.location_is_fallback
    assert item.link and item.link.endswith(f"/rules/events?event={world.event.id}")
    position = await _one(db, world, position_ref(world.position))
    item = await load_item(db, position)
    assert item is not None and item.location == (-24.9, 31.5) and not item.location_is_fallback
    assert item.data["speed_mps"] == 1.5 and item.data_source_name == world.source.name


async def test_backfill_queues_range_once(db, world):
    queued = await backfill(db, world.integration, T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert queued == 2
    assert world.integration.backfill["status"] == "done"
    assert world.integration.backfill["queued"] == 2 and world.integration.backfill["scanned"] == 2
    again = await backfill(db, world.integration, T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert again == 0
    rows = (
        await db.scalars(
            select(IntegrationDelivery).where(
                IntegrationDelivery.integration_id == world.integration.id
            )
        )
    ).all()
    assert len(rows) == 2 and all(r.origin == "backfill" for r in rows)
    outside = await backfill(db, world.integration, T0 + timedelta(days=1), T0 + timedelta(days=2))
    assert outside == 0
    counts = await delivery_counts(db, world.integration.id)
    assert counts["queued"] == 2 and counts["sent"] == 0
    total = await db.scalar(
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(IntegrationDelivery.integration_id == world.integration.id)
    )
    assert total == 2
