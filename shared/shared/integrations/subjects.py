"""The entities an integration forwards, as a target with a register of its own sees them
(decision D408): each with the device it has now. And the step that follows a backfill:
registering them once their history is on the target (decision D409).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import BackfillStatus, DeliveryOrigin, DeliveryStatus
from shared.integrations.base import (
    PermanentFailure,
    Subject,
    SubjectRegistrar,
    SubjectStatus,
)
from shared.integrations.deliveries import integration_context
from shared.integrations.registry import CONNECTORS
from shared.models import (
    Device,
    DeviceEntityAssignment,
    Entity,
    EntityType,
    ExternalIdentity,
    Integration,
    IntegrationDelivery,
)
from shared.timeutil import utc_now

MAX_SUBJECTS = 200


def registrar_of(integration: Integration) -> SubjectRegistrar:
    connector = CONNECTORS.get(integration.connector_key)
    if not isinstance(connector, SubjectRegistrar):
        raise PermanentFailure(f"{integration.connector_key} keeps no register of entities")
    return connector


async def load_subjects(session: AsyncSession, integration: Integration) -> list[Subject]:
    """The entities ticked on the integration, by name, with the device on each now. An
    integration that forwards every entity names none, and nothing is registered for it: the
    register on the target is filled for entities somebody chose."""
    ids = [uuid.UUID(str(value)) for value in integration.entity_ids or []]
    if not ids:
        raise PermanentFailure("Choose the entities to forward on the integration first")
    if len(ids) > MAX_SUBJECTS:
        raise PermanentFailure(f"At most {MAX_SUBJECTS} entities are registered at a time")
    rows = (
        await session.execute(
            select(Entity, EntityType)
            .join(EntityType, EntityType.id == Entity.entity_type_id)
            .where(Entity.id.in_(ids), Entity.project_id == integration.project_id)
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
                DeviceEntityAssignment.entity_id.in_(ids),
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
        # the identity heard last, as a delivery names it (`load_item`)
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


async def subject_statuses(
    session: AsyncSession, integration: Integration
) -> list[tuple[Subject, SubjectStatus]]:
    """What the target has for each entity of the integration, read from the target."""
    registrar = registrar_of(integration)
    subjects = await load_subjects(session, integration)
    statuses = await registrar.subjects(
        integration_context(integration), subjects, dict(integration.connector_state or {})
    )
    return _paired(subjects, statuses)


async def register_subjects(
    session: AsyncSession, integration: Integration
) -> list[tuple[Subject, SubjectStatus]]:
    """Register the entities the target lacks and keep what the connector remembers. The
    caller commits."""
    registrar = registrar_of(integration)
    subjects = await load_subjects(session, integration)
    statuses, state = await registrar.register(
        integration_context(integration), subjects, dict(integration.connector_state or {})
    )
    integration.connector_state = state
    return _paired(subjects, statuses)


def _paired(
    subjects: list[Subject], statuses: list[SubjectStatus]
) -> list[tuple[Subject, SubjectStatus]]:
    by_entity = {status.entity_id: status for status in statuses}
    return [(s, by_entity[s.entity_id]) for s in subjects if s.entity_id in by_entity]


async def register_after_backfill(session: AsyncSession, integration: Integration) -> str | None:
    """The step after a backfill that asked for it (decision D409): once every reading the
    backfill queued is delivered, register the entities. Returns what happened (`waiting`,
    `held`, `done`, `failed`) or None when nothing was asked. Commits."""
    progress: dict[str, Any] = dict(integration.backfill or {})
    if not progress.get("then_register") or progress.get("status") != BackfillStatus.DONE:
        return None
    backfilled = (
        IntegrationDelivery.integration_id == integration.id,
        IntegrationDelivery.origin == DeliveryOrigin.BACKFILL,
    )
    waiting = await session.scalar(
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(*backfilled, IntegrationDelivery.status == DeliveryStatus.QUEUED)
    )
    if waiting:
        return "waiting"
    registration: dict[str, Any] = {"at": utc_now().isoformat()}
    started = datetime.fromisoformat(str(progress.get("started_at") or "1970-01-01T00:00:00+00:00"))
    failed = await session.scalar(
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(
            *backfilled,
            IntegrationDelivery.status == DeliveryStatus.FAILED,
            IntegrationDelivery.created_at >= started,
        )
    )
    if failed:
        # a history with holes is not followed by a deployment: somebody looks first
        registration.update(status="held", failed=int(failed))
    else:
        try:
            pairs = await register_subjects(session, integration)
        except Exception as exc:
            registration.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        else:
            registration.update(
                status="done",
                registered=sum(1 for _, s in pairs if s.state == "registered"),
                blocked=sum(1 for _, s in pairs if s.state == "blocked"),
            )
    integration.backfill = {**progress, "then_register": False, "registration": registration}
    await session.commit()
    return str(registration["status"])
