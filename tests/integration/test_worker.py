"""The service: bus messages to rows, the delivery cycle, backfill requests, and the
registration that follows a backfill."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from protect_integration.worker import (
    IntegrationCache,
    deliver_due,
    handle_backfill,
    handle_message,
    register_pending,
)
from shared.bus import Message, Topic
from shared.enums import DeliveryStatus
from shared.integrations.base import PermanentFailure, SubjectStatus
from shared.integrations.deliveries import _position_ref as position_ref
from shared.integrations.deliveries import backfill, enqueue, event_ref
from shared.integrations.registry import CONNECTORS
from shared.integrations.subjects import load_subjects, register_after_backfill
from shared.models import Integration, IntegrationDelivery
from tests.integration.conftest import T0, FakeConnector

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


class Registrar(FakeConnector):
    """A fake target that keeps a register of the entities (decision D408)."""

    def __init__(self) -> None:
        super().__init__()
        self.registered: set[uuid.UUID] = set()
        self.fail = False

    def _statuses(self, subjects):
        return [
            SubjectStatus(
                entity_id=s.entity_id,
                state="registered" if s.entity_id in self.registered else "not_registered",
                sensor_id=s.device_name,
            )
            for s in subjects
        ]

    async def subjects(self, integration, subjects, state):
        return self._statuses(subjects)

    async def register(self, integration, subjects, state):
        if self.fail:
            raise PermanentFailure("the target refused")
        self.registered |= {s.entity_id for s in subjects}
        return self._statuses(subjects), {**state, "made": sorted(str(i) for i in self.registered)}


async def test_subjects_are_the_ticked_entities_with_their_device(db, world):
    """Decision D408: nothing is registered for an integration that names no entity."""
    with pytest.raises(PermanentFailure, match="Choose the entities"):
        await load_subjects(db, world.integration)
    world.integration.entity_ids = [str(world.entity.id), str(uuid.uuid4())]
    subjects = await load_subjects(db, world.integration)
    assert [s.entity_name for s in subjects] == ["Rhino 14"]  # the stranger's id finds nothing
    assert subjects[0].device_name == world.device.name
    assert subjects[0].assigned_from == T0 - timedelta(days=30)
    assert subjects[0].entity_type_label == "Rhino"
    await db.rollback()


async def test_registration_follows_the_backfill_when_its_readings_are_delivered(db, world):
    """Decision D409: history first, then the deployment; a history with a hole holds it."""
    await _isolate(db, world)
    registrar = Registrar()
    CONNECTORS["fake"] = registrar
    integration = world.integration
    integration.entity_ids = [str(world.entity.id)]
    assert await register_after_backfill(db, integration) is None  # nobody asked

    integration.backfill = {"then_register": True, "status": "running"}
    assert await register_after_backfill(db, integration) is None  # still scanning
    queued = await backfill(db, integration, T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert queued == 2 and integration.backfill["then_register"] is True
    assert await register_after_backfill(db, integration) == "waiting"
    assert not registrar.registered
    assert (await register_pending(db)) == {}  # the worker's cycle waits as well

    await deliver_due(db)
    assert (await register_pending(db)) == {integration.name: "done"}
    assert registrar.registered == {world.entity.id}
    await db.refresh(integration)
    assert integration.backfill["then_register"] is False
    assert integration.backfill["registration"]["status"] == "done"
    assert integration.backfill["registration"]["registered"] == 1
    assert integration.connector_state == {"made": [str(world.entity.id)]}
    assert await register_after_backfill(db, integration) is None  # once

    # a reading of the history failed: no deployment until somebody has looked
    delivery = await db.scalar(
        select(IntegrationDelivery).where(IntegrationDelivery.integration_id == integration.id)
    )
    delivery.status = DeliveryStatus.FAILED
    registrar.registered.clear()
    integration.backfill = {**integration.backfill, "then_register": True}
    await db.commit()
    assert await register_after_backfill(db, integration) == "held"
    assert integration.backfill["registration"]["failed"] == 1 and not registrar.registered

    # the target refuses the registration: said on the integration, not retried forever
    delivery.status = DeliveryStatus.SENT
    registrar.fail = True
    integration.backfill = {**integration.backfill, "then_register": True}
    await db.commit()
    assert await register_after_backfill(db, integration) == "failed"
    assert "the target refused" in integration.backfill["registration"]["error"]
    assert integration.backfill["then_register"] is False
