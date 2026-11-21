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
)
from shared.bus import Message, Topic
from shared.enums import DeliveryStatus, SubjectState
from shared.integrations.base import PermanentFailure, SubjectOptions, SubjectStatus
from shared.integrations.deliveries import _position_ref as position_ref
from shared.integrations.deliveries import enqueue, event_ref, matches
from shared.integrations.registry import CONNECTORS
from shared.integrations.subjects import finish_histories, integrate, load_subjects, stop
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
    """A fake target that keeps a register of the entities (decisions D408 and D412)."""

    def __init__(self) -> None:
        super().__init__()
        self.registered: dict[uuid.UUID, dict] = {}
        self.fail = False

    async def options(self, integration, subject):
        return SubjectOptions(sensor_id=subject.device_name, status=SubjectStatus(False))

    async def statuses(self, integration, subjects):
        return {s.entity_id: SubjectStatus(s.entity_id in self.registered) for s in subjects}

    async def register(self, integration, subject, settings, external_id):
        if self.fail:
            raise PermanentFailure("the target refused")
        self.registered[subject.entity_id] = settings
        return SubjectStatus(True, external_id="animal-1")


async def test_a_subject_is_an_entity_with_the_device_on_it(db, world):
    subjects = await load_subjects(db, world.project.id, [world.entity.id, uuid.uuid4()])
    assert [s.entity_name for s in subjects] == ["Rhino 14"]  # the stranger's id finds nothing
    assert subjects[0].device_name == world.device.name
    assert subjects[0].assigned_from == T0 - timedelta(days=30)
    assert subjects[0].entity_type_label == "Rhino"
    await db.rollback()


async def test_a_registering_target_gets_the_integrated_entities_and_no_others(db, world):
    """Decision D412: an empty entity list means every entity for a webhook and none for a
    target that registers its entities."""
    ref = position_ref(world.position)
    assert matches(world.integration, ref)  # the plain fake target takes everything
    CONNECTORS["fake"] = Registrar()
    assert not matches(world.integration, ref)
    world.integration.entity_ids = [str(world.entity.id)]
    assert matches(world.integration, ref)
    await db.rollback()


async def test_an_entity_is_integrated_with_its_history_first(db, world):
    """Decisions D409 and D412: the history is queued for this entity alone, the registration
    follows its last object, a history with a hole holds it, a refusal is written down."""
    await _isolate(db, world)
    registrar = Registrar()
    CONNECTORS["fake"] = registrar
    integration = world.integration
    chosen = {"species_id": "s1", "species_name": "Diceros bicornis"}

    row = await integrate(db, integration, world.entity.id, chosen, T0 - timedelta(hours=1), None)
    await db.commit()
    assert row.state == SubjectState.HISTORY_REQUESTED and not registrar.registered
    assert integration.entity_ids == [str(world.entity.id)]  # forwarded from now on
    assert await finish_histories(db) == {}  # nothing is queued yet, so nothing is finished
    with pytest.raises(PermanentFailure, match="history is being sent"):
        await integrate(db, integration, world.entity.id, chosen, None, None)

    # the worker's part: the request from the bus queues the entity's two objects
    assert await handle_backfill(db, {"subject_id": str(row.id)}) == 2
    await db.refresh(row)
    assert row.state == SubjectState.SENDING_HISTORY and row.history_queued == 2
    assert await finish_histories(db) == {} and not registrar.registered  # still waiting

    await deliver_due(db)
    assert await finish_histories(db) == {"registered": 1}
    await db.refresh(row)
    assert row.state == SubjectState.REGISTERED and row.external_id == "animal-1"
    assert registrar.registered == {world.entity.id: chosen}
    assert await finish_histories(db) == {}  # once

    # a second time, and one object of the history fails: held, not registered
    registrar.registered.clear()
    await db.execute(delete(IntegrationDelivery))
    row = await integrate(db, integration, world.entity.id, chosen, T0 - timedelta(hours=1), None)
    await db.commit()
    await handle_backfill(db, {"subject_id": str(row.id)})
    await db.execute(update(IntegrationDelivery).values(status=DeliveryStatus.FAILED))
    await db.commit()
    assert await finish_histories(db) == {"held": 1}
    await db.refresh(row)
    assert row.state == SubjectState.HELD and "2 objects" in row.detail
    assert not registrar.registered

    # integrated again without history: registered at once; a refusal is written on the row
    registrar.fail = True
    row = await integrate(db, integration, world.entity.id, chosen, None, None)
    await db.commit()
    assert row.state == SubjectState.FAILED and row.detail == "the target refused"
    registrar.fail = False
    row = await integrate(db, integration, world.entity.id, chosen, None, None)
    await db.commit()
    assert row.state == SubjectState.REGISTERED and row.detail is None

    # stopping ends the forwarding and leaves the target alone
    assert await stop(db, integration, world.entity.id) is True
    await db.commit()
    assert integration.entity_ids == [] and not matches(integration, position_ref(world.position))
    assert await stop(db, integration, world.entity.id) is False
