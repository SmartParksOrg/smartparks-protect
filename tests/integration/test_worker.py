"""The service: bus messages to rows, the delivery cycle, backfill requests, and the
registration that follows a backfill."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import Range

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
from shared.integrations.deployments import compare, confirm, decline, rewritten_by
from shared.integrations.registry import CONNECTORS
from shared.integrations.subjects import finish_histories, integrate, load_subjects, stop
from shared.models import (
    DeviceEntityAssignment,
    Entity,
    Integration,
    IntegrationDelivery,
    IntegrationDeployment,
    Position,
)
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
    """A fake target that keeps a register of the entities (decisions D408, D412 and D416):
    an animal per entity, and the deployments sent, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.animals: dict[uuid.UUID, dict] = {}
        self.deployed: list[tuple[str, str, datetime]] = []
        self.fail = False
        self.refuse_deploy = False

    def sensor(self, integration, subject):
        return subject.device_name

    async def options(self, integration, subject):
        return SubjectOptions(sensor_id=subject.device_name, status=SubjectStatus(False))

    async def statuses(self, integration, subjects):
        return {s.entity_id: SubjectStatus(s.entity_id in self.animals) for s in subjects}

    async def register_animal(self, integration, subject, settings):
        if self.fail:
            raise PermanentFailure("the target refused")
        self.animals[subject.entity_id] = settings
        return f"animal-{len(self.animals)}"

    async def deploy(self, integration, animal_id, sensor_id, start):
        if self.refuse_deploy:
            raise PermanentFailure("the target refused the sensor")
        self.deployed.append((animal_id, sensor_id, start))


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
    assert row.state == SubjectState.HISTORY_REQUESTED and not registrar.animals
    assert integration.entity_ids == [str(world.entity.id)]  # forwarded from now on
    assert await finish_histories(db) == {}  # nothing is queued yet, so nothing is finished
    with pytest.raises(PermanentFailure, match="history is being sent"):
        await integrate(db, integration, world.entity.id, chosen, None, None)

    # the worker's part: the request from the bus queues the entity's two objects
    assert await handle_backfill(db, {"subject_id": str(row.id)}) == 2
    await db.refresh(row)
    assert row.state == SubjectState.SENDING_HISTORY and row.history_queued == 2
    assert await finish_histories(db) == {} and not registrar.animals  # still waiting

    await deliver_due(db)
    assert await finish_histories(db) == {"registered": 1}
    await db.refresh(row)
    assert row.state == SubjectState.REGISTERED and row.external_id == "animal-1"
    assert registrar.animals == {world.entity.id: chosen}
    # the device on it now, from the start of its assignment (decision D418)
    assert registrar.deployed == [("animal-1", world.device.name, T0 - timedelta(days=30))]
    assert await finish_histories(db) == {}  # once

    # a second time, and one object of the history fails: held, not registered
    await db.execute(delete(IntegrationDelivery))
    row = await integrate(db, integration, world.entity.id, chosen, T0 - timedelta(hours=1), None)
    await db.commit()
    await handle_backfill(db, {"subject_id": str(row.id)})
    await db.execute(update(IntegrationDelivery).values(status=DeliveryStatus.FAILED))
    await db.commit()
    assert await finish_histories(db) == {"held": 1}
    await db.refresh(row)
    assert row.state == SubjectState.HELD and "2 objects" in row.detail
    assert len(registrar.deployed) == 1  # nothing sent again

    # a fresh start, integrated without history: registered at once; a refusal is written
    await stop(db, integration, world.entity.id)
    await db.execute(delete(IntegrationDeployment))
    await db.commit()
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


async def _entity(db, world, name):
    entity = Entity(
        project_id=world.project.id, entity_type_id=world.entity.entity_type_id, name=name
    )
    db.add(entity)
    await db.flush()
    return entity


async def _move(db, device_id, to_entity_id, at):
    """The device's open assignment ends at `at` and one on the other entity starts there."""
    current = await db.scalar(
        select(DeviceEntityAssignment).where(
            DeviceEntityAssignment.device_id == device_id,
            DeviceEntityAssignment.validity.op("@>")(at),
        )
    )
    current.validity = Range(current.validity.lower, at, bounds="[)")
    await db.flush()
    db.add(
        DeviceEntityAssignment(
            device_id=device_id, entity_id=to_entity_id, validity=Range(at, None, bounds="[)")
        )
    )
    await db.commit()


async def _reading(db, world, entity_id, at):
    position = Position(
        time=at,
        device_id=world.device.id,
        project_id=world.project.id,
        entity_id=entity_id,
        data_source_id=world.source.id,
        canonical_key=f"{world.device.id}|{at.isoformat()}|gnss",
        geom=WKTElement("POINT(31.5 -24.9)", srid=4326),
    )
    db.add(position)
    await db.flush()
    await enqueue(db, [world.integration], [position_ref(position)], honour_age=False)
    await db.commit()
    return await db.scalar(
        select(IntegrationDelivery).where(IntegrationDelivery.object_id == str(position.id))
    )


async def _rows(db, integration_id):
    return list(
        await db.scalars(
            select(IntegrationDeployment)
            .where(IntegrationDeployment.integration_id == integration_id)
            .order_by(IntegrationDeployment.starts_at, IntegrationDeployment.created_at)
        )
    )


async def test_a_device_moved_to_another_entity_waits_for_a_person(db, world):
    """Decisions D416 to D419, Tim's case: a device goes from one integrated entity to another.
    Protect sees it, asks, holds the device's readings for the new entity until a person said
    yes, then makes the deployment and lets them go. A device that stays on its animal needs
    nothing; a sensor deployed for the third time warns; a period declined is not sent."""
    await _isolate(db, world)
    registrar = Registrar()
    CONNECTORS["fake"] = registrar
    integration = world.integration
    chosen = {"species_id": "s1", "species_name": "Diceros bicornis"}
    sensor = world.device.name
    a = world.entity
    b = await _entity(db, world, "Rhino 15")
    await db.commit()

    await integrate(db, integration, a.id, chosen, None, None)
    await integrate(db, integration, b.id, chosen, None, None)  # no device yet: it waits
    await db.commit()
    assert registrar.deployed == [("animal-1", sensor, T0 - timedelta(days=30))]
    assert await compare(db) == {}  # the device on A is on A's animal: nothing to ask

    # the device moves to B
    moved = T0 + timedelta(days=1)
    await _move(db, world.device.id, b.id, moved)
    assert await compare(db) == {"pending": 1}
    first, pending = await _rows(db, integration.id)
    assert (first.entity_id, first.state, first.ends_at) == (a.id, "sent", moved)
    assert (pending.entity_id, pending.state, pending.sensor_id) == (b.id, "pending", sensor)
    assert pending.starts_at == moved and await rewritten_by(db, pending) == 0
    assert await compare(db) == {}  # asked once

    # a reading of B's new device waits: sent now it would land on A's animal
    delivery = await _reading(db, world, b.id, moved + timedelta(hours=2))
    assert await deliver_due(db) == {"holds": 1}
    await db.refresh(delivery)
    assert delivery.status == "queued" and "confirms" in delivery.error_message
    assert not registrar.delivered

    await confirm(db, integration, pending, None)
    await db.commit()
    assert registrar.deployed[-1] == ("animal-2", sensor, moved)
    assert pending.state == "sent" and pending.animal_id == "animal-2"
    assert await deliver_due(db) == {"sent": 1}  # let go at once
    with pytest.raises(PermanentFailure, match="waits or was refused"):
        await confirm(db, integration, pending, None)

    # the assignment cut in two on the same entity: the deployment goes on as it is
    split = T0 + timedelta(days=2)
    await _move(db, world.device.id, b.id, split)
    assert await compare(db) == {"sent": 1}
    assert "Continues" in (await _rows(db, integration.id))[-1].detail
    assert len(registrar.deployed) == 2

    # back to A: the platform would rewrite the end of the finished one on A (D419)
    back = T0 + timedelta(days=3)
    await _move(db, world.device.id, a.id, back)
    assert await compare(db) == {"pending": 1}
    again = (await _rows(db, integration.id))[-1]
    assert (again.entity_id, again.state) == (a.id, "pending")
    assert await rewritten_by(db, again) == 1

    # declined: nothing made on the target, the readings of the period are not sent
    delivery = await _reading(db, world, a.id, back + timedelta(hours=1))
    await decline(db, again, None)
    await db.commit()
    await db.refresh(delivery)
    assert delivery.status == "skipped" and "declined" in delivery.error_message
    assert len(registrar.deployed) == 2
    late = await _reading(db, world, a.id, back + timedelta(hours=5))
    assert await deliver_due(db) == {"skips": 1}
    await db.refresh(late)
    assert late.status == "skipped"

    # declined, so the target still has the sensor on B: back to B needs nothing
    returned = T0 + timedelta(days=4)
    await _move(db, world.device.id, b.id, returned)
    assert await compare(db) == {"sent": 1}

    # a refused deployment is written down and holds the readings until it is confirmed again
    d = await _entity(db, world, "Rhino 17")
    await db.commit()
    await integrate(db, integration, d.id, chosen, None, None)
    await db.commit()
    registrar.refuse_deploy = True
    gone = T0 + timedelta(days=5)
    await _move(db, world.device.id, d.id, gone)
    assert await compare(db) == {"pending": 1}
    refused = (await _rows(db, integration.id))[-1]
    await confirm(db, integration, refused, None)
    await db.commit()
    assert refused.state == "refused" and "refused the sensor" in refused.detail
    held = await _reading(db, world, d.id, gone + timedelta(hours=1))
    assert await deliver_due(db) == {"holds": 1}
    await db.refresh(held)
    assert "refused" in held.error_message

    # stopping the entity drops what was never sent and keeps what was
    assert await stop(db, integration, d.id)
    await db.commit()
    assert not [r for r in await _rows(db, integration.id) if r.entity_id == d.id]
    assert [r.state for r in await _rows(db, integration.id) if r.entity_id == b.id] == [
        "sent",
        "sent",
        "sent",
    ]


async def test_an_entity_whose_sensor_is_on_another_animal_is_deployed_before_its_history(
    db, world
):
    """Decision D416: the device left an integrated entity for one that is not integrated.
    The target keeps the sensor on the first animal. Integrating the second with its history
    makes the deployment first, since the history would otherwise land on the first one."""
    await _isolate(db, world)
    registrar = Registrar()
    CONNECTORS["fake"] = registrar
    integration = world.integration
    chosen = {"species_id": "s1", "species_name": "Diceros bicornis"}
    a = world.entity
    c = await _entity(db, world, "Rhino 16")
    await db.commit()
    await integrate(db, integration, a.id, chosen, None, None)
    await db.commit()

    moved = T0 + timedelta(days=1)
    await _move(db, world.device.id, c.id, moved)
    assert await compare(db) == {}  # C is not integrated: nothing to ask, nothing sent
    (first,) = await _rows(db, integration.id)
    assert first.ends_at == moved  # still the device's open deployment on the target

    row = await integrate(db, integration, c.id, chosen, moved, None)
    await db.commit()
    assert registrar.deployed[-1] == ("animal-2", world.device.name, moved)
    assert row.state == SubjectState.HISTORY_REQUESTED and row.registered_at is not None
    await handle_backfill(db, {"subject_id": str(row.id)})
    await deliver_due(db)
    assert await finish_histories(db) == {"registered": 1}
    assert len(registrar.deployed) == 2  # not a second time


async def test_a_measurement_carries_the_other_numbers_of_its_moment(db, world):
    """Decision D421: a target that sends a status message as one reading gets the device's
    other numbers of the same moment with the measurement it forwards."""
    from shared.integrations.deliveries import load_item, measurement_ref
    from shared.models import Measurement

    await _isolate(db, world)
    for key, value in (("device_temperature", 2.75), ("acceleration_x", 1.96)):
        db.add(
            Measurement(
                time=T0,
                device_id=world.device.id,
                project_id=world.project.id,
                entity_id=world.entity.id,
                data_source_id=world.source.id,
                metric_key=key,
                canonical_key=f"{world.device.id}|{key}|{T0.isoformat()}",
                value_num=value,
            )
        )
    await db.commit()
    world.integration.object_types = ["measurement"]
    CONNECTORS["fake"].supports = frozenset({"position", "event", "measurement"})
    await enqueue(db, [world.integration], [measurement_ref(world.measurement)], honour_age=False)
    await db.commit()
    delivery = await db.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.object_id == str(world.measurement.id)
        )
    )
    item = await load_item(db, delivery)
    assert item.data["moment"] == {
        "battery_voltage": 3.7,
        "device_temperature": 2.75,
        "acceleration_x": 1.96,
    }
