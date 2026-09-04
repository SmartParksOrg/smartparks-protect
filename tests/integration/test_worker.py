"""The service: bus messages to rows, the delivery cycle, backfill requests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from protect_integration.worker import (
    IntegrationCache,
    deliver_due,
    handle_backfill,
    handle_message,
)
from shared.bus import Message, Topic
from shared.enums import DeliveryStatus
from shared.integrations.deliveries import _position_ref as position_ref
from shared.integrations.deliveries import enqueue, event_ref
from shared.models import Integration, IntegrationDelivery
from tests.integration.conftest import T0

pytestmark = pytest.mark.asyncio


def _message(topic, payload):
    return Message(topic=topic, payload=payload)


async def _isolate(db, world):
    """Only this test's integration is live: other tests leave queued rows behind."""
    await db.execute(delete(IntegrationDelivery))
    await db.execute(
        update(Integration).where(Integration.id != world.integration.id).values(enabled=False)
    )
    await db.commit()


async def test_messages_become_rows(db, world):
    cache = IntegrationCache()
    position = _message(
        Topic.POSITION_CREATED,
        {
            "position_id": world.position.id,
            "time": world.position.time.isoformat(),
            "device_id": str(world.device.id),
            "project_id": str(world.project.id),
            "entity_id": str(world.entity.id),
            "latitude": -24.9,
            "longitude": 31.5,
        },
    )
    assert await handle_message(db, cache, position) == 1
    assert await handle_message(db, cache, position) == 0  # idempotent
    event = _message(
        Topic.EVENT_CREATED, {"event_id": str(world.event.id), "project_id": str(world.project.id)}
    )
    assert await handle_message(db, cache, event) == 1
    measurement = _message(
        Topic.MEASUREMENT_CREATED,
        {"measurement_ids": [world.measurement.id], "device_id": str(world.device.id)},
    )
    assert await handle_message(db, cache, measurement) == 0  # not forwarded by this integration
    other = _message(
        Topic.POSITION_CREATED,
        {
            "position_id": 999,
            "time": T0.isoformat(),
            "device_id": str(world.device.id),
            "project_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert await handle_message(db, cache, other) == 0
    rows = (
        await db.scalars(
            select(IntegrationDelivery).where(
                IntegrationDelivery.integration_id == world.integration.id
            )
        )
    ).all()
    assert {r.object_type for r in rows} == {"position", "event"}


async def test_delivery_cycle_halts_an_unreachable_target(db, world, fake_connector):
    await _isolate(db, world)
    await enqueue(
        db,
        [world.integration],
        [position_ref(world.position), event_ref(world.event)],
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    await db.commit()
    fake_connector.mode = "transient"
    outcome = await deliver_due(db)
    assert outcome == {"queued": 1}  # one request, then the integration waits for its backoff
    fake_connector.mode = "ok"
    assert await deliver_due(db) == {"sent": 1}  # the other row goes; the failed one waits
    later = datetime.now(UTC) + timedelta(minutes=2)
    assert await deliver_due(db, now=later) == {"sent": 1}
    assert len(fake_connector.delivered) == 2
    world.integration.enabled = False
    await enqueue(
        db,
        [world.integration],
        [position_ref(world.position)],
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    await db.commit()


async def test_disabled_integration_skips(db, world, fake_connector):
    await _isolate(db, world)
    await enqueue(
        db,
        [world.integration],
        [position_ref(world.position)],
        now=datetime.now(UTC) - timedelta(seconds=1),
    )
    world.integration.enabled = False
    await db.commit()
    assert await deliver_due(db) == {"skipped": 1}
    row = await db.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.integration_id == world.integration.id
        )
    )
    assert row is not None and row.status == DeliveryStatus.SKIPPED
    assert row.error_message == "integration disabled"


async def test_backfill_request(db, world):
    queued = await handle_backfill(
        db,
        {
            "integration_id": str(world.integration.id),
            "from": (T0 - timedelta(hours=1)).isoformat(),
            "to": (T0 + timedelta(hours=1)).isoformat(),
        },
    )
    assert queued == 2
    assert await handle_backfill(db, {"integration_id": "not-a-uuid", "from": "x", "to": "y"}) == 0
