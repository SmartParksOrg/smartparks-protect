"""An entity integrated with a target that keeps a register of its own (decisions D408, D409
and D412): the choices a user made for it, its history sent first, then its registration.

The row in `integration_subjects` is Protect's own account of it; what the target has is read
from the target when somebody asks.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import DeliveryOrigin, DeliveryStatus, DeploymentState, SubjectState
from shared.integrations.base import (
    PermanentFailure,
    Subject,
    SubjectDevice,
    SubjectRegistrar,
    TransientFailure,
)
from shared.integrations.deliveries import (
    backfill_entity,
    integration_context,
    primary_identities,
)
from shared.integrations.deployments import (
    animal_at,
    as_device,
    device_rows,
    forget_undecided,
    target_spans,
)
from shared.integrations.registry import CONNECTORS
from shared.models import (
    Device,
    DeviceEntityAssignment,
    Entity,
    EntityType,
    Integration,
    IntegrationDelivery,
    IntegrationDeployment,
    IntegrationSubject,
)
from shared.timeutil import utc_now

MAX_SUBJECTS = 200


def registrar_of(integration: Integration) -> SubjectRegistrar:
    connector = CONNECTORS.get(integration.connector_key)
    if not isinstance(connector, SubjectRegistrar):
        raise PermanentFailure(f"{integration.connector_key} keeps no register of entities")
    return connector


async def load_subjects(
    session: AsyncSession,
    project_id: uuid.UUID,
    entity_ids: list[uuid.UUID],
    external_ids: dict[uuid.UUID, str] | None = None,
) -> list[Subject]:
    """The entities, by name, each with the devices on it now (the oldest assignment first
    is the one the target is told about first) and the identity each device is known by
    (decision D417). `external_ids` is what the target calls each entity, where known."""
    if not entity_ids:
        return []
    rows = (
        await session.execute(
            select(Entity, EntityType)
            .join(EntityType, EntityType.id == Entity.entity_type_id)
            .where(Entity.id.in_(entity_ids), Entity.project_id == project_id)
            .order_by(Entity.name)
        )
    ).all()
    parent_ids = {t.parent_id for _, t in rows if t.parent_id is not None}
    parents = (
        {
            p.id: p.key
            for p in await session.scalars(select(EntityType).where(EntityType.id.in_(parent_ids)))
        }
        if parent_ids
        else {}
    )
    now = utc_now()
    on: dict[uuid.UUID, list[DeviceEntityAssignment]] = {}
    for a in await session.scalars(
        select(DeviceEntityAssignment)
        .where(
            DeviceEntityAssignment.entity_id.in_(entity_ids),
            DeviceEntityAssignment.validity.op("@>")(now),
        )
        .order_by(func.lower(DeviceEntityAssignment.validity))
    ):
        on.setdefault(a.entity_id, []).append(a)
    device_ids = {a.device_id for found in on.values() for a in found}
    devices = (
        {d.id: d for d in await session.scalars(select(Device).where(Device.id.in_(device_ids)))}
        if device_ids
        else {}
    )
    identities = await primary_identities(session, list(device_ids))
    subjects: list[Subject] = []
    for entity, entity_type in rows:
        found = tuple(
            SubjectDevice(
                device_id=a.device_id,
                device_name=devices[a.device_id].name,
                device_serial=devices[a.device_id].serial_number,
                device_identity=identities.get(a.device_id),
                assigned_from=a.validity.lower,
            )
            for a in on.get(entity.id, [])
            if a.device_id in devices
        )
        subject = Subject(
            entity_id=entity.id,
            entity_name=entity.name,
            entity_type_key=entity_type.key,
            entity_type_label=entity_type.label,
            entity_type_parent_key=parents.get(entity_type.parent_id),
            attributes=dict(entity.attributes or {}),
            external_id=(external_ids or {}).get(entity.id),
            devices=found,
        )
        subjects.append(as_device(subject, found[0]) if found else subject)
    return subjects


async def load_subject(
    session: AsyncSession, integration: Integration, entity_id: uuid.UUID
) -> Subject:
    row = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == integration.id,
            IntegrationSubject.entity_id == entity_id,
        )
    )
    known = {entity_id: row.external_id} if row is not None and row.external_id else {}
    subjects = await load_subjects(session, integration.project_id, [entity_id], known)
    if not subjects:
        raise PermanentFailure("The entity is not in this integration's project")
    return subjects[0]


def _forwarded(integration: Integration, entity_id: uuid.UUID, wanted: bool) -> None:
    """Keep the integration's entity filter in step: it is what every delivery passes."""
    ids = [str(value) for value in integration.entity_ids or []]
    key = str(entity_id)
    if wanted and key not in ids:
        integration.entity_ids = [*ids, key]
    elif not wanted and key in ids:
        integration.entity_ids = [value for value in ids if value != key]


async def _known_animal(
    session: AsyncSession, integration: Integration, entity_id: uuid.UUID
) -> str | None:
    """The animal Protect made for the entity before, kept on its sent deployments when the
    entity was stopped and integrated again: the target keeps it, so no second one."""
    return await session.scalar(
        select(IntegrationDeployment.animal_id)
        .where(
            IntegrationDeployment.integration_id == integration.id,
            IntegrationDeployment.entity_id == entity_id,
            IntegrationDeployment.state == DeploymentState.SENT,
            IntegrationDeployment.animal_id.is_not(None),
        )
        .order_by(IntegrationDeployment.starts_at.desc())
        .limit(1)
    )


LOCKED = (
    "WildlifeNL cannot change an animal. Choose Make a new animal to correct the species or "
    "the ear tag number"
)


async def register_subject(
    session: AsyncSession,
    integration: Integration,
    row: IntegrationSubject,
    *,
    reuse: bool = True,
) -> None:
    """Register one entity on the target as its row says and write the outcome on the row:
    its animal, then a deployment of every device on it now (decisions D408 and D418), which
    the person integrating it confirmed by doing so. Later changes of its devices wait for a
    person (decision D416), so an entity registered before is not deployed again here.
    A target that cannot be reached leaves the rows as they are and raises, so the caller
    tries again; a refusal is written down and not repeated. `reuse=False` makes a new
    animal even where Protect made one for the entity before (decision D423)."""
    registrar = registrar_of(integration)
    subject = await load_subject(session, integration, row.entity_id)
    context = integration_context(integration)
    first = row.registered_at is None
    try:
        if row.external_id is None:
            known = await _known_animal(session, integration, row.entity_id) if reuse else None
            row.external_id = known or await registrar.register_animal(
                context, subject, dict(row.settings or {})
            )
    except PermanentFailure as exc:
        row.state, row.detail = SubjectState.FAILED, str(exc)
        return
    refused: list[str] = []
    if first:
        made = {
            (d.device_id, d.starts_at): d
            for d in await session.scalars(
                select(IntegrationDeployment).where(
                    IntegrationDeployment.integration_id == integration.id,
                    IntegrationDeployment.entity_id == row.entity_id,
                )
            )
        }
        for device in subject.devices:
            deployment = made.get((device.device_id, device.assigned_from))
            if deployment is None:
                deployment = IntegrationDeployment(
                    integration_id=integration.id,
                    entity_id=row.entity_id,
                    device_id=device.device_id,
                    starts_at=device.assigned_from,
                    state=DeploymentState.PENDING,
                )
                session.add(deployment)
            if deployment.state == DeploymentState.SENT and deployment.animal_id == row.external_id:
                continue
            sensor = registrar.sensor(context, as_device(subject, device))
            deployment.sensor_id = sensor
            if sensor is None:
                deployment.state = DeploymentState.REFUSED
                deployment.detail = "The device has no identity the target could know it by"
                refused.append(f"{device.device_name}: {deployment.detail}")
                continue
            try:
                await registrar.deploy(context, row.external_id, sensor, device.assigned_from)
            except PermanentFailure as exc:
                deployment.state, deployment.detail = DeploymentState.REFUSED, str(exc)
                refused.append(f"{device.device_name}: {exc}")
                continue
            deployment.state, deployment.detail = DeploymentState.SENT, None
            deployment.animal_id = row.external_id
            deployment.sent_at = utc_now()
    if refused:
        row.state = SubjectState.FAILED
        row.detail = "The target made the animal and refused its sensor. " + "; ".join(refused)
        return
    row.state, row.detail = SubjectState.REGISTERED, None
    row.registered_at = row.registered_at or utc_now()


async def _sensor_elsewhere(
    session: AsyncSession, integration: Integration, subject: Subject
) -> bool:
    """Whether a device on the entity has its sensor on another animal on the target now,
    as Protect sent it or as the target says."""
    registrar = registrar_of(integration)
    context = integration_context(integration)
    rows = await device_rows(session, integration.id, {d.device_id for d in subject.devices})
    now = utc_now()
    for device in subject.devices:
        on = animal_at(target_spans(rows.get(device.device_id, [])), now)
        if on is not None and on != subject.external_id:
            return True
    if not subject.devices:
        return False
    statuses = await registrar.statuses(
        context, [as_device(subject, d) for d in subject.devices[:1]]
    )
    status = statuses.get(subject.entity_id)
    return status is not None and status.elsewhere is not None


async def integrate(
    session: AsyncSession,
    integration: Integration,
    entity_id: uuid.UUID,
    settings: dict[str, Any],
    history_from: datetime | None,
    user_id: uuid.UUID | None,
    *,
    new_animal: bool = False,
) -> IntegrationSubject:
    """Integrate one entity (decision D412): keep what the user chose, start forwarding its
    data, and either ask for its history (the caller publishes the request, and the
    registration follows the last reading, decision D409) or register it at once. The caller
    commits.

    Once the target has the entity's animal its species is locked, since the target cannot
    change an animal; `new_animal` makes a new one as now chosen and moves the entity's
    devices to it from their assignments' start, at once and without history, since the
    readings are on the target already under the sensor (decision D423)."""
    registrar_of(integration)
    await load_subject(session, integration, entity_id)
    row = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == integration.id,
            IntegrationSubject.entity_id == entity_id,
        )
    )
    if row is None:
        count = await session.scalar(
            select(func.count())
            .select_from(IntegrationSubject)
            .where(IntegrationSubject.integration_id == integration.id)
        )
        if (count or 0) >= MAX_SUBJECTS:
            raise PermanentFailure(f"An integration holds at most {MAX_SUBJECTS} entities")
        row = IntegrationSubject(
            integration_id=integration.id,
            entity_id=entity_id,
            created_by_user_id=user_id,
            state=SubjectState.HISTORY_REQUESTED,
        )
        session.add(row)
    elif row.state in (SubjectState.HISTORY_REQUESTED, SubjectState.SENDING_HISTORY):
        raise PermanentFailure("The entity's history is being sent; wait until it is done")
    made = row.external_id is not None
    chosen = str(settings.get("species_id"))
    if made and not new_animal and chosen != str((row.settings or {}).get("species_id")):
        raise PermanentFailure(LOCKED)
    if new_animal:
        if not made:
            raise PermanentFailure("The entity has no animal on the target yet")
        row.settings = settings
        row.history_from = None
        row.detail = None
        row.external_id = None
        row.registered_at = None
        _forwarded(integration, entity_id, True)
        await register_subject(session, integration, row, reuse=False)
        await session.flush()
        return row
    row.settings = settings
    row.history_from = history_from
    row.detail = None
    _forwarded(integration, entity_id, True)
    if history_from is not None and row.registered_at is None:
        subject = await load_subject(session, integration, entity_id)
        if await _sensor_elsewhere(session, integration, subject):
            # its history would land on the other animal: the deployment goes first here
            # and the history follows it (decision D416)
            await register_subject(session, integration, row)
            if row.state != SubjectState.REGISTERED:
                await session.flush()
                return row
    if history_from is not None:
        row.state = SubjectState.HISTORY_REQUESTED
        row.history_queued = 0
        row.history_started_at = None
    else:
        await register_subject(session, integration, row)
    await session.flush()
    return row


async def stop(session: AsyncSession, integration: Integration, entity_id: uuid.UUID) -> bool:
    """Stop forwarding an entity. What the target holds stays there: Protect ends and deletes
    nothing on a target, and keeps its sent deployments, so the entity integrated again gets
    its animal back. The caller commits."""
    row = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == integration.id,
            IntegrationSubject.entity_id == entity_id,
        )
    )
    _forwarded(integration, entity_id, False)
    await forget_undecided(session, integration.id, entity_id)
    if row is None:
        return False
    await session.delete(row)
    return True


async def send_history(session: AsyncSession, subject_id: uuid.UUID) -> int:
    """The worker's part of a history request: queue the entity's old objects, oldest first,
    and mark the row so the registration follows them. Commits."""
    row = await session.get(IntegrationSubject, subject_id)
    if row is None or row.state != SubjectState.HISTORY_REQUESTED or row.history_from is None:
        return 0
    integration = await session.get(Integration, row.integration_id)
    if integration is None:
        return 0
    row.history_started_at = utc_now()
    queued = await backfill_entity(
        session, integration, row.entity_id, row.history_from, row.history_started_at
    )
    row.history_queued = queued
    row.state = SubjectState.SENDING_HISTORY
    await session.commit()
    return queued


async def finish_histories(session: AsyncSession) -> dict[str, int]:
    """Every entity whose history was queued (decision D409): once none of its objects waits,
    it is registered; when one of them failed it is held, since a history with holes is not
    followed by a registration until somebody looked. Commits per entity."""
    rows = (
        await session.scalars(
            select(IntegrationSubject).where(
                IntegrationSubject.state == SubjectState.SENDING_HISTORY
            )
        )
    ).all()
    outcome: dict[str, int] = {}
    for row in rows:
        integration = await session.get(Integration, row.integration_id)
        if integration is None or not integration.enabled:
            continue
        mine = (
            IntegrationDelivery.integration_id == row.integration_id,
            IntegrationDelivery.entity_id == row.entity_id,
            IntegrationDelivery.origin == DeliveryOrigin.BACKFILL,
        )
        waiting = await session.scalar(
            select(func.count())
            .select_from(IntegrationDelivery)
            .where(*mine, IntegrationDelivery.status == DeliveryStatus.QUEUED)
        )
        if waiting:
            continue
        failed = await session.scalar(
            select(func.count())
            .select_from(IntegrationDelivery)
            .where(
                *mine,
                IntegrationDelivery.status == DeliveryStatus.FAILED,
                IntegrationDelivery.created_at >= (row.history_started_at or row.created_at),
            )
        )
        if failed:
            row.state = SubjectState.HELD
            row.detail = (
                f"{failed} objects of its history failed. Look at the deliveries, retry them, "
                "then integrate the entity again without history."
            )
        else:
            try:
                await register_subject(session, integration, row)
            except TransientFailure:
                continue  # the target is away; the next cycle asks again
        await session.commit()
        outcome[str(row.state)] = outcome.get(str(row.state), 0) + 1
    return outcome
