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

from shared.enums import DeliveryOrigin, DeliveryStatus, SubjectState
from shared.integrations.base import (
    PartlyRegistered,
    PermanentFailure,
    Subject,
    SubjectRegistrar,
    TransientFailure,
)
from shared.integrations.deliveries import backfill_entity, integration_context
from shared.integrations.registry import CONNECTORS
from shared.models import (
    Device,
    DeviceEntityAssignment,
    Entity,
    EntityType,
    ExternalIdentity,
    Integration,
    IntegrationDelivery,
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
    session: AsyncSession, project_id: uuid.UUID, entity_ids: list[uuid.UUID]
) -> list[Subject]:
    """The entities, by name, each with the device on it now and the identity that device
    was heard under last, as a delivery names it."""
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
    assignments = {
        a.entity_id: a
        for a in await session.scalars(
            select(DeviceEntityAssignment)
            .where(
                DeviceEntityAssignment.entity_id.in_(entity_ids),
                DeviceEntityAssignment.validity.op("@>")(now),
            )
            .order_by(func.lower(DeviceEntityAssignment.validity))
        )
    }
    device_ids = {a.device_id for a in assignments.values()}
    devices = (
        {d.id: d for d in await session.scalars(select(Device).where(Device.id.in_(device_ids)))}
        if device_ids
        else {}
    )
    identities: dict[uuid.UUID, str] = {}
    if device_ids:
        for identity in await session.scalars(
            select(ExternalIdentity)
            .where(ExternalIdentity.device_id.in_(device_ids), ExternalIdentity.ignored.is_(False))
            .order_by(ExternalIdentity.last_seen_at.desc().nulls_last())
        ):
            if identity.device_id is not None:
                identities.setdefault(identity.device_id, identity.external_id)
    subjects: list[Subject] = []
    for entity, entity_type in rows:
        assignment = assignments.get(entity.id)
        device = devices.get(assignment.device_id) if assignment is not None else None
        subjects.append(
            Subject(
                entity_id=entity.id,
                entity_name=entity.name,
                entity_type_key=entity_type.key,
                entity_type_label=entity_type.label,
                entity_type_parent_key=parents.get(entity_type.parent_id),
                attributes=dict(entity.attributes or {}),
                device_id=device.id if device is not None else None,
                device_name=device.name if device is not None else None,
                device_serial=device.serial_number if device is not None else None,
                device_identity=identities.get(device.id) if device is not None else None,
                assigned_from=assignment.validity.lower if assignment is not None else None,
            )
        )
    return subjects


async def load_subject(
    session: AsyncSession, integration: Integration, entity_id: uuid.UUID
) -> Subject:
    subjects = await load_subjects(session, integration.project_id, [entity_id])
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


async def register_subject(
    session: AsyncSession, integration: Integration, row: IntegrationSubject
) -> None:
    """Register one entity on the target as its row says and write the outcome on the row.
    A target that cannot be reached leaves the row as it is and raises, so the caller tries
    again; a refusal is written down and not repeated."""
    registrar = registrar_of(integration)
    subject = await load_subject(session, integration, row.entity_id)
    try:
        status = await registrar.register(
            integration_context(integration), subject, dict(row.settings or {}), row.external_id
        )
    except PartlyRegistered as exc:
        row.external_id = exc.external_id
        row.state, row.detail = SubjectState.FAILED, str(exc)
        return
    except PermanentFailure as exc:
        row.state, row.detail = SubjectState.FAILED, str(exc)
        return
    row.state, row.detail = SubjectState.REGISTERED, None
    row.external_id = status.external_id or row.external_id
    row.registered_at = utc_now()


async def integrate(
    session: AsyncSession,
    integration: Integration,
    entity_id: uuid.UUID,
    settings: dict[str, Any],
    history_from: datetime | None,
    user_id: uuid.UUID | None,
) -> IntegrationSubject:
    """Integrate one entity (decision D412): keep what the user chose, start forwarding its
    data, and either ask for its history (the caller publishes the request, and the
    registration follows the last reading, decision D409) or register it at once. The caller
    commits."""
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
    row.settings = settings
    row.history_from = history_from
    row.detail = None
    _forwarded(integration, entity_id, True)
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
    nothing on a target. The caller commits."""
    row = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == integration.id,
            IntegrationSubject.entity_id == entity_id,
        )
    )
    _forwarded(integration, entity_id, False)
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
