"""The devices on an integrated entity as deployments of their sensors on the target's
animal (decisions D416 to D419, Tim, 2026-11-22).

Protect's assignments say which device was on which entity when. A target such as WildlifeNL
links a reading to an animal through a deployment of the sensor, and its own rule is that a
new deployment of a sensor ends the one before it at the new start. It has no call to end or
remove a deployment. So:

- `compare` (the integration worker, every half minute) makes a `pending` row for every
  device on an integrated entity that the target does not have on that animal yet: a device
  moved from one integrated entity to another, a second device, the first device of an
  entity integrated without one. A device that stays on the same animal, such as an
  assignment cut in two, continues the deployment it has and needs nothing.
- `Holds` keeps the device's readings for such an entity queued until a person confirms,
  since a reading sent before the new deployment lands on the animal the sensor was on.
- `confirm` makes the deployment and lets the readings go, oldest first; `decline` skips the
  readings of the period instead.

Which animal a reading lands on is read from Protect's sent rows the way the target reads its
deployments: a sent row covers its device's readings from its start to the start of the
device's next sent row.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import DeliveryStatus, DeploymentState, SubjectState
from shared.integrations.base import (
    PermanentFailure,
    Subject,
    SubjectDevice,
    SubjectRegistrar,
)
from shared.integrations.deliveries import integration_context, primary_identities
from shared.integrations.registry import CONNECTORS
from shared.models import (
    Device,
    DeviceEntityAssignment,
    Integration,
    IntegrationDelivery,
    IntegrationDeployment,
    IntegrationSubject,
)
from shared.timeutil import utc_now

HOLD_SECONDS = 60
COMPARE_SECONDS = 30
OUTDATED = "The assignment in Protect changed after this was sent"


def registrar_or_none(integration: Integration) -> SubjectRegistrar | None:
    connector = CONNECTORS.get(integration.connector_key)
    return connector if isinstance(connector, SubjectRegistrar) else None


@dataclass(frozen=True, slots=True)
class Span:
    """A sent deployment as the target holds it: from its start to the next one's."""

    animal_id: str | None
    entity_id: uuid.UUID
    start: datetime
    end: datetime | None


def target_spans(rows: list[IntegrationDeployment]) -> list[Span]:
    """One device's sent rows as spans on the target, oldest first."""
    sent = sorted((r for r in rows if r.state == DeploymentState.SENT), key=lambda r: r.starts_at)
    return [
        Span(
            animal_id=r.animal_id,
            entity_id=r.entity_id,
            start=r.starts_at,
            end=sent[i + 1].starts_at if i + 1 < len(sent) else None,
        )
        for i, r in enumerate(sent)
    ]


def animal_at(spans: list[Span], moment: datetime) -> str | None:
    """The animal a reading of the device at `moment` lands on, as far as Protect sent it."""
    found = None
    for span in spans:
        if span.start <= moment and (span.end is None or moment < span.end):
            found = span.animal_id
    return found


def covers(row: IntegrationDeployment, moment: datetime) -> bool:
    return row.starts_at <= moment and (row.ends_at is None or moment < row.ends_at)


def _lower(validity: Any) -> datetime:
    lower: datetime = validity.lower
    return lower


def _upper(validity: Any) -> datetime | None:
    return None if validity.upper_inf else validity.upper


def tracked(validity: Any, subject: IntegrationSubject) -> bool:
    """An assignment Protect follows for an integrated entity: one still on when the entity
    was registered, or one that started after. A device that left before is history."""
    end = _upper(validity)
    return subject.registered_at is not None and (end is None or end > subject.registered_at)


async def device_rows(
    session: AsyncSession, integration_id: uuid.UUID, device_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[IntegrationDeployment]]:
    out: dict[uuid.UUID, list[IntegrationDeployment]] = {d: [] for d in device_ids}
    if not device_ids:
        return out
    for row in await session.scalars(
        select(IntegrationDeployment).where(
            IntegrationDeployment.integration_id == integration_id,
            IntegrationDeployment.device_id.in_(device_ids),
        )
    ):
        out.setdefault(row.device_id, []).append(row)
    return out


async def compare(session: AsyncSession) -> dict[str, int]:
    """Every registered entity of every enabled integration whose target keeps a register,
    against its assignments (decision D416): a row per assignment Protect follows, `pending`
    unless the device's sensor is on the entity's animal already. A pending row whose
    assignment is gone is removed; a sent one is marked outdated. Commits."""
    outcome: dict[str, int] = {}
    integrations = [
        i
        for i in await session.scalars(select(Integration).where(Integration.enabled.is_(True)))
        if registrar_or_none(i) is not None
    ]
    for integration in integrations:
        registrar = registrar_or_none(integration)
        assert registrar is not None
        subjects = {
            s.entity_id: s
            for s in await session.scalars(
                select(IntegrationSubject).where(
                    IntegrationSubject.integration_id == integration.id,
                    IntegrationSubject.state == SubjectState.REGISTERED,
                    IntegrationSubject.external_id.is_not(None),
                )
            )
        }
        if not subjects:
            continue
        rows = list(
            await session.scalars(
                select(IntegrationDeployment).where(
                    IntegrationDeployment.integration_id == integration.id,
                    IntegrationDeployment.entity_id.in_(subjects),
                )
            )
        )
        by_key = {(r.entity_id, r.device_id, r.starts_at): r for r in rows}
        # an assignment with a row is followed whatever its end says now
        assignments = [
            a
            for a in await session.scalars(
                select(DeviceEntityAssignment).where(DeviceEntityAssignment.entity_id.in_(subjects))
            )
            if (a.entity_id, a.device_id, _lower(a.validity)) in by_key
            or tracked(a.validity, subjects[a.entity_id])
        ]
        devices = {a.device_id for a in assignments}
        by_device = await device_rows(session, integration.id, devices)
        identities = await primary_identities(session, list(devices))
        names = (
            {d.id: d for d in await session.scalars(select(Device).where(Device.id.in_(devices)))}
            if devices
            else {}
        )
        context = integration_context(integration)
        seen: set[tuple[uuid.UUID, uuid.UUID, datetime]] = set()
        for a in sorted(assignments, key=lambda a: _lower(a.validity)):
            key = (a.entity_id, a.device_id, _lower(a.validity))
            seen.add(key)
            row = by_key.get(key)
            if row is not None:
                if row.ends_at != _upper(a.validity):
                    row.ends_at = _upper(a.validity)
                continue
            subject = subjects[a.entity_id]
            device = names.get(a.device_id)
            sensor = registrar.sensor(
                context,
                Subject(
                    entity_id=a.entity_id,
                    entity_name="",
                    device_id=a.device_id,
                    device_name=device.name if device else None,
                    device_serial=device.serial_number if device else None,
                    device_identity=identities.get(a.device_id),
                ),
            )
            row = IntegrationDeployment(
                integration_id=integration.id,
                entity_id=a.entity_id,
                device_id=a.device_id,
                sensor_id=sensor,
                starts_at=_lower(a.validity),
                ends_at=_upper(a.validity),
                state=DeploymentState.PENDING,
            )
            if animal_at(target_spans(by_device.get(a.device_id, [])), row.starts_at) == (
                subject.external_id
            ):
                # the sensor is on this animal already: the deployment goes on as it is
                row.state = DeploymentState.SENT
                row.animal_id = subject.external_id
                row.detail = "Continues the deployment the device had on this animal"
            session.add(row)
            by_device.setdefault(a.device_id, []).append(row)
            outcome[row.state] = outcome.get(row.state, 0) + 1
        for key, row in by_key.items():
            if key in seen:
                continue
            if row.state == DeploymentState.SENT:
                if row.detail != OUTDATED:
                    row.detail = OUTDATED
                    outcome["outdated"] = outcome.get("outdated", 0) + 1
            else:
                await session.delete(row)
                outcome["removed"] = outcome.get("removed", 0) + 1
        await session.commit()
    return outcome


class Holds:
    """Whether a reading may go to a target that keeps a register (decision D416), with what
    it reads cached for one delivery cycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._subjects: dict[tuple[uuid.UUID, uuid.UUID], IntegrationSubject | None] = {}
        self._rows: dict[tuple[uuid.UUID, uuid.UUID], list[IntegrationDeployment]] = {}
        self._assignments: dict[tuple[uuid.UUID, uuid.UUID], list[Any]] = {}

    async def _subject(
        self, integration_id: uuid.UUID, entity_id: uuid.UUID
    ) -> IntegrationSubject | None:
        key = (integration_id, entity_id)
        if key not in self._subjects:
            self._subjects[key] = await self.session.scalar(
                select(IntegrationSubject).where(
                    IntegrationSubject.integration_id == integration_id,
                    IntegrationSubject.entity_id == entity_id,
                )
            )
        return self._subjects[key]

    async def _device_rows(
        self, integration_id: uuid.UUID, device_id: uuid.UUID
    ) -> list[IntegrationDeployment]:
        key = (integration_id, device_id)
        if key not in self._rows:
            self._rows[key] = (await device_rows(self.session, integration_id, {device_id}))[
                device_id
            ]
        return self._rows[key]

    async def _validities(self, entity_id: uuid.UUID, device_id: uuid.UUID) -> list[Any]:
        key = (entity_id, device_id)
        if key not in self._assignments:
            self._assignments[key] = list(
                await self.session.scalars(
                    select(DeviceEntityAssignment.validity).where(
                        DeviceEntityAssignment.entity_id == entity_id,
                        DeviceEntityAssignment.device_id == device_id,
                    )
                )
            )
        return self._assignments[key]

    async def verdict(
        self, integration: Integration, delivery: IntegrationDelivery
    ) -> tuple[str, str] | None:
        """None when the delivery may go; ("hold", why) to keep it queued; ("skip", why) when
        it is not to be sent at all."""
        if registrar_or_none(integration) is None:
            return None
        if delivery.entity_id is None or delivery.device_id is None:
            return None
        subject = await self._subject(integration.id, delivery.entity_id)
        if subject is None:
            return ("skip", "The entity is no longer integrated")
        if subject.state != SubjectState.REGISTERED or not subject.external_id:
            return None  # its history goes before its registration (decision D409)
        moment = delivery.object_time
        rows = await self._device_rows(integration.id, delivery.device_id)
        own = next(
            (r for r in rows if r.entity_id == delivery.entity_id and covers(r, moment)), None
        )
        if own is not None and own.state == DeploymentState.DECLINED:
            return ("skip", "The deployment of this device on the animal was declined")
        if animal_at(target_spans(rows), moment) == subject.external_id:
            return None
        if own is None:
            followed = any(
                v.lower <= moment and (v.upper_inf or moment < v.upper) and tracked(v, subject)
                for v in await self._validities(delivery.entity_id, delivery.device_id)
            )
            if not followed:
                return None  # the entity's history from before it was integrated
            return ("hold", "Waits until Protect compared the device with the target")
        if own.state == DeploymentState.PENDING:
            return ("hold", "Waits until a person confirms the deployment of this device")
        if own.state == DeploymentState.REFUSED:
            return ("hold", f"The target refused the deployment of this device: {own.detail}")
        return None


async def subject_device(
    session: AsyncSession, row: IntegrationDeployment
) -> tuple[Subject, IntegrationSubject]:
    """The entity's registration and the device as a subject, for the target."""
    subject = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == row.integration_id,
            IntegrationSubject.entity_id == row.entity_id,
        )
    )
    if subject is None or subject.state != SubjectState.REGISTERED or not subject.external_id:
        raise PermanentFailure("Integrate the entity first; then its devices can be deployed")
    device = await session.get(Device, row.device_id)
    identity = (await primary_identities(session, [row.device_id])).get(row.device_id)
    return (
        Subject(
            entity_id=row.entity_id,
            entity_name="",
            external_id=subject.external_id,
            device_id=row.device_id,
            device_name=device.name if device else None,
            device_serial=device.serial_number if device else None,
            device_identity=identity,
        ),
        subject,
    )


async def release(
    session: AsyncSession, row: IntegrationDeployment, now: datetime | None = None
) -> int:
    """The device's held readings for the entity go now, oldest first."""
    result = await session.execute(
        update(IntegrationDelivery)
        .where(
            IntegrationDelivery.integration_id == row.integration_id,
            IntegrationDelivery.entity_id == row.entity_id,
            IntegrationDelivery.device_id == row.device_id,
            IntegrationDelivery.status == DeliveryStatus.QUEUED,
        )
        .values(next_attempt_at=now or utc_now(), error_message=None)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def confirm(
    session: AsyncSession,
    integration: Integration,
    row: IntegrationDeployment,
    user_id: uuid.UUID | None,
) -> IntegrationDeployment:
    """A person said yes (decision D416): the deployment is made on the target and the held
    readings go. A refusal is written on the row; a target that cannot be reached raises
    `TransientFailure` and leaves the row as it was. The caller commits."""
    registrar = registrar_or_none(integration)
    if registrar is None:
        raise PermanentFailure(f"{integration.connector_key} keeps no register of entities")
    if row.state not in (DeploymentState.PENDING, DeploymentState.REFUSED):
        raise PermanentFailure("Only a deployment that waits or was refused can be confirmed")
    device, subject = await subject_device(session, row)
    sensor = row.sensor_id or registrar.sensor(integration_context(integration), device)
    if sensor is None:
        raise PermanentFailure("The device has no identity the target could know it by")
    row.sensor_id = sensor
    row.decided_by_user_id = user_id
    try:
        await registrar.deploy(
            integration_context(integration), str(subject.external_id), sensor, row.starts_at
        )
    except PermanentFailure as exc:
        row.state, row.detail = DeploymentState.REFUSED, str(exc)
        return row
    row.state, row.detail = DeploymentState.SENT, None
    row.animal_id = subject.external_id
    row.sent_at = utc_now()
    await release(session, row)
    return row


async def decline(
    session: AsyncSession, row: IntegrationDeployment, user_id: uuid.UUID | None
) -> IntegrationDeployment:
    """A person said no (decision D416): nothing is made on the target, and the device's
    readings of this entity in the period are skipped. The caller commits."""
    if row.state not in (DeploymentState.PENDING, DeploymentState.REFUSED):
        raise PermanentFailure("Only a deployment that waits or was refused can be declined")
    row.state = DeploymentState.DECLINED
    row.detail = None
    row.decided_by_user_id = user_id
    period = [IntegrationDelivery.object_time >= row.starts_at]
    if row.ends_at is not None:
        period.append(IntegrationDelivery.object_time < row.ends_at)
    await session.execute(
        update(IntegrationDelivery)
        .where(
            IntegrationDelivery.integration_id == row.integration_id,
            IntegrationDelivery.entity_id == row.entity_id,
            IntegrationDelivery.device_id == row.device_id,
            IntegrationDelivery.status == DeliveryStatus.QUEUED,
            *period,
        )
        .values(
            status=DeliveryStatus.SKIPPED,
            next_attempt_at=None,
            error_message="The deployment of this device on the animal was declined",
        )
    )
    return row


async def rewritten_by(session: AsyncSession, row: IntegrationDeployment) -> int:
    """How many finished deployments of the sensor the target would give a wrong end when
    this one is sent (decision D419): its rule ends every deployment of the sensor at the new
    start, not only the open one. Counted from what Protect sent in this integration."""
    if row.sensor_id is None:
        return 0
    sent = await session.scalar(
        select(func.count())
        .select_from(IntegrationDeployment)
        .where(
            IntegrationDeployment.integration_id == row.integration_id,
            IntegrationDeployment.sensor_id == row.sensor_id,
            IntegrationDeployment.state == DeploymentState.SENT,
            # made by a request: a row that continues one is no deployment of its own there
            IntegrationDeployment.sent_at.is_not(None),
        )
    )
    return max(0, int(sent or 0) - 1)


async def forget_undecided(
    session: AsyncSession, integration_id: uuid.UUID, entity_id: uuid.UUID
) -> None:
    """An entity no longer integrated: what was never sent is dropped; what was sent stays,
    since the target still has it."""
    await session.execute(
        delete(IntegrationDeployment).where(
            IntegrationDeployment.integration_id == integration_id,
            IntegrationDeployment.entity_id == entity_id,
            IntegrationDeployment.state != DeploymentState.SENT,
        )
    )


def as_device(subject: Subject, device: SubjectDevice) -> Subject:
    """The subject with one of its devices as the device the target knows it by."""
    return replace(
        subject,
        device_id=device.device_id,
        device_name=device.device_name,
        device_serial=device.device_serial,
        device_identity=device.device_identity,
        assigned_from=device.assigned_from,
    )
