"""Moves of devices and entities between projects, with their history (decisions D292 and
D293, ADR 0038).

A device moves from a moment: its project assignments from that moment are cut, split or
removed, a new open assignment starts there, and an attribution job rewrites the records from
that moment on. An entity whose whole history lies inside the move goes along, with its
current state and the events nothing but a rule wrote for it; an entity that keeps history
in the old project stays, and the moving device's assignment to it is cut at the moment. A
moved entity takes its devices over the spans they tracked it, so a device reused on another
animal of the old project keeps that history there. `plan_*` say what a move would do and
`apply_plan` does it; the API answers the plan as a preview and runs it on request, so what
the dialog says is what happens.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from shared.curation.effective import effective_time
from shared.domain.attribution import queue_reattribution
from shared.models import (
    Alert,
    AttributionJob,
    Device,
    DeviceEntityAssignment,
    DeviceLogFile,
    DeviceProjectAssignment,
    Entity,
    EntityCurrentState,
    Event,
    ExternalIdentity,
    Measurement,
    Position,
    Project,
)
from shared.timeutil import require_aware, utc_now

StartChoice = Literal["first_data", "joined", "now"] | datetime
NAME_TAKEN = "the target project has an entity of that name"


async def first_data_at(session: AsyncSession, device_id: uuid.UUID) -> datetime | None:
    """The earliest the device produced anything: a record, an identity seen, a log file."""
    candidates: list[datetime] = []
    for model in (Position, Measurement):
        first = await session.scalar(
            select(func.min(effective_time(model))).where(model.device_id == device_id)
        )
        if first is not None:
            candidates.append(first)
    for value in (
        await session.scalar(
            select(func.min(ExternalIdentity.first_seen_at)).where(
                ExternalIdentity.device_id == device_id
            )
        ),
        await session.scalar(
            select(func.min(DeviceLogFile.period_start)).where(DeviceLogFile.device_id == device_id)
        ),
    ):
        if value is not None:
            candidates.append(value)
    return min(candidates, default=None)


@dataclass(slots=True)
class Span:
    """A period over which a device's project becomes the target; `end` None means open."""

    start: datetime
    end: datetime | None


@dataclass(slots=True)
class EntityOutcome:
    entity_id: uuid.UUID
    name: str
    project_id: uuid.UUID
    moves: bool
    reason: str | None = None


@dataclass(slots=True)
class DeviceOutcome:
    device_id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    """The device's project at the start of its first span; None when it has none."""
    spans: list[Span] = field(default_factory=list)
    entities_along: list[uuid.UUID] = field(default_factory=list)
    entities_staying: list[uuid.UUID] = field(default_factory=list)
    skipped: str | None = None
    attribution_job_id: uuid.UUID | None = None


@dataclass(slots=True)
class MovePlan:
    project_id: uuid.UUID
    group_id: uuid.UUID | None
    devices: list[DeviceOutcome]
    entities: dict[uuid.UUID, EntityOutcome]


def _bounds(validity: Range[datetime]) -> tuple[datetime, datetime | None]:
    return validity.lower, validity.upper  # type: ignore[return-value]


async def start_moment(
    session: AsyncSession, device_id: uuid.UUID, start: StartChoice, now: datetime
) -> tuple[datetime | None, str | None]:
    """The moment an assignment or a move starts for a device, from the choice (decision
    D103): its first data (now when it has none), the start of its current project
    assignment, now, or a given moment; or why there is none."""
    if isinstance(start, datetime):
        return require_aware(start), None
    if start == "now":
        return now, None
    if start == "first_data":
        return await first_data_at(session, device_id) or now, None
    joined = await session.scalar(
        select(func.lower(DeviceProjectAssignment.validity)).where(
            DeviceProjectAssignment.device_id == device_id,
            DeviceProjectAssignment.validity.op("@>")(now),
        )
    )
    if joined is None:
        return None, "not in a project; assign it instead"
    return joined, None


async def plan_device_moves(
    session: AsyncSession,
    *,
    device_ids: list[uuid.UUID],
    project_id: uuid.UUID,
    start: StartChoice,
    group_id: uuid.UUID | None,
) -> MovePlan:
    """What moving the devices to `project_id` from `start` would do (decision D292): the
    moment per device, the entities that come along and the ones that stay (decision D293).
    A device already in the target project from that moment on is skipped, as is one in no
    project (that is an assignment, not a move) and one carrying an entity whose name the
    target project already has."""
    now = utc_now()
    devices = {
        d.id: d
        for d in (await session.scalars(select(Device).where(Device.id.in_(set(device_ids))))).all()
    }
    plan = MovePlan(project_id=project_id, group_id=group_id, devices=[], entities={})
    moments: dict[uuid.UUID, datetime] = {}
    for device_id in dict.fromkeys(device_ids):
        device = devices.get(device_id)
        if device is None:
            plan.devices.append(
                DeviceOutcome(device_id=device_id, name="", project_id=None, skipped="not found")
            )
            continue
        moment, why = await start_moment(session, device_id, start, now)
        outcome = DeviceOutcome(device_id=device_id, name=device.name, project_id=None)
        plan.devices.append(outcome)
        if moment is None:
            outcome.skipped = why
            continue
        current = await session.scalar(
            select(DeviceProjectAssignment).where(
                DeviceProjectAssignment.device_id == device_id,
                DeviceProjectAssignment.validity.op("@>")(moment),
            )
        )
        outcome.project_id = current.project_id if current else None
        if current is None:
            outcome.skipped = "not in a project at that moment; assign it instead"
            continue
        later = await session.scalar(
            select(func.count())
            .select_from(DeviceProjectAssignment)
            .where(
                DeviceProjectAssignment.device_id == device_id,
                func.lower(DeviceProjectAssignment.validity) > moment,
            )
        )
        if current.project_id == project_id and _bounds(current.validity)[1] is None and not later:
            outcome.skipped = "already in this project"
            continue
        outcome.spans = [Span(moment, None)]
        moments[device_id] = moment
    # the entities: every assignment of a moving device from its moment on names one
    for outcome in plan.devices:
        if outcome.skipped:
            continue
        moment = moments[outcome.device_id]
        assignments = (
            await session.scalars(
                select(DeviceEntityAssignment).where(
                    DeviceEntityAssignment.device_id == outcome.device_id,
                    DeviceEntityAssignment.validity.op("&&")(Range(moment, None, bounds="[)")),
                )
            )
        ).all()
        for assignment in assignments:
            entity_outcome = await _entity_outcome(
                session, plan, assignment.entity_id, moments, project_id
            )
            if entity_outcome.moves:
                if assignment.entity_id not in outcome.entities_along:
                    outcome.entities_along.append(assignment.entity_id)
            elif assignment.entity_id not in outcome.entities_staying:
                outcome.entities_staying.append(assignment.entity_id)
    # a name the target already has blocks the entity, and with it the devices carrying it
    for outcome in plan.devices:
        blocked = [
            plan.entities[e]
            for e in outcome.entities_staying
            if plan.entities[e].reason == NAME_TAKEN
        ]
        if blocked and not outcome.skipped:
            outcome.skipped = (
                f"the entity {blocked[0].name} cannot move: {NAME_TAKEN}"  # one template
            )
    return plan


async def _entity_outcome(
    session: AsyncSession,
    plan: MovePlan,
    entity_id: uuid.UUID,
    moments: dict[uuid.UUID, datetime],
    project_id: uuid.UUID,
) -> EntityOutcome:
    """Whether an entity goes along with a device move (decision D293): only when every
    assignment it ever had belongs to a moving device and starts at or after that device's
    moment, so no history of it stays behind."""
    known = plan.entities.get(entity_id)
    if known is not None:
        return known
    entity = await session.get(Entity, entity_id)
    assert entity is not None
    outcome = EntityOutcome(
        entity_id=entity_id, name=entity.name, project_id=entity.project_id, moves=False
    )
    plan.entities[entity_id] = outcome
    if entity.project_id == project_id:
        outcome.moves = True  # already there: the assignment stays as it is
        outcome.reason = "already in the target project"
        return outcome
    assignments = (
        await session.scalars(
            select(DeviceEntityAssignment).where(DeviceEntityAssignment.entity_id == entity_id)
        )
    ).all()
    for assignment in assignments:
        moment = moments.get(assignment.device_id)
        lower, _ = _bounds(assignment.validity)
        if moment is None:
            other = await session.get(Device, assignment.device_id)
            outcome.reason = (
                f"another device, {other.name if other else '?'}, tracked it"
                if assignment.device_id not in {d.device_id for d in plan.devices}
                else f"{other.name if other else '?'} is not moving"
            )
            return outcome
        if lower < moment:
            other = await session.get(Device, assignment.device_id)
            outcome.reason = (
                f"{other.name if other else '?'} tracked it before {moment:%Y-%m-%d %H:%M} UTC"
            )
            return outcome
    if await _name_taken(session, project_id, entity.name):
        outcome.reason = NAME_TAKEN
        return outcome
    outcome.moves = True
    return outcome


async def _name_taken(session: AsyncSession, project_id: uuid.UUID, name: str) -> bool:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Entity)
            .where(Entity.project_id == project_id, Entity.name == name)
        )
        or 0
    ) > 0


async def plan_entity_moves(
    session: AsyncSession,
    *,
    source_project_id: uuid.UUID,
    entity_ids: list[uuid.UUID],
    project_id: uuid.UUID,
    group_id: uuid.UUID | None,
) -> MovePlan:
    """What moving the entities of one project to `project_id` would do (decision D293): each
    goes whole, and every device follows it over the spans it tracked the entity. An entity
    of another project, or one whose name the target already has, is skipped."""
    plan = MovePlan(project_id=project_id, group_id=group_id, devices=[], entities={})
    by_device: dict[uuid.UUID, DeviceOutcome] = {}
    for entity_id in dict.fromkeys(entity_ids):
        entity = await session.get(Entity, entity_id)
        if entity is None or entity.project_id != source_project_id:
            plan.entities[entity_id] = EntityOutcome(
                entity_id=entity_id,
                name="",
                project_id=source_project_id,
                moves=False,
                reason="not found in this project",
            )
            continue
        outcome = EntityOutcome(
            entity_id=entity_id, name=entity.name, project_id=entity.project_id, moves=True
        )
        plan.entities[entity_id] = outcome
        if entity.project_id == project_id:
            outcome.moves = False
            outcome.reason = "already in this project"
            continue
        if await _name_taken(session, project_id, entity.name):
            outcome.moves = False
            outcome.reason = NAME_TAKEN
            continue
        assignments = (
            await session.scalars(
                select(DeviceEntityAssignment)
                .where(DeviceEntityAssignment.entity_id == entity_id)
                .order_by(func.lower(DeviceEntityAssignment.validity))
            )
        ).all()
        for assignment in assignments:
            device_outcome = by_device.get(assignment.device_id)
            if device_outcome is None:
                device = await session.get(Device, assignment.device_id)
                lower, _ = _bounds(assignment.validity)
                current = await session.scalar(
                    select(DeviceProjectAssignment.project_id).where(
                        DeviceProjectAssignment.device_id == assignment.device_id,
                        DeviceProjectAssignment.validity.op("@>")(lower),
                    )
                )
                device_outcome = DeviceOutcome(
                    device_id=assignment.device_id,
                    name=device.name if device else "",
                    project_id=current,
                )
                by_device[assignment.device_id] = device_outcome
                plan.devices.append(device_outcome)
            lower, upper = _bounds(assignment.validity)
            device_outcome.spans.append(Span(lower, upper))
            device_outcome.entities_along.append(entity_id)
    return plan


async def apply_plan(
    session: AsyncSession,
    plan: MovePlan,
    *,
    user_id: uuid.UUID | None,
    reason: str | None,
) -> list[AttributionJob]:
    """Do what the plan says: the project assignments cut, split and created per span, the
    staying entities' assignments cut at the moment, the moving entities' project changed,
    and one attribution job per device over its spans. Returns the jobs the caller publishes
    after the commit."""
    now = utc_now()
    jobs: list[AttributionJob] = []
    moving = {e.entity_id for e in plan.entities.values() if e.moves}
    for outcome in plan.devices:
        if outcome.skipped or not outcome.spans:
            continue
        for span in outcome.spans:
            await _replace_project_over(
                session, outcome.device_id, span, plan.project_id, user_id, reason
            )
            # an entity that stays loses the device from the moment on (decision D293)
            for assignment in (
                await session.scalars(
                    select(DeviceEntityAssignment).where(
                        DeviceEntityAssignment.device_id == outcome.device_id,
                        DeviceEntityAssignment.validity.op("&&")(
                            Range(span.start, span.end, bounds="[)")
                        ),
                    )
                )
            ).all():
                if assignment.entity_id in moving:
                    continue
                lower, _ = _bounds(assignment.validity)
                if lower < span.start:
                    assignment.validity = Range(lower, span.start, bounds="[)")
                else:
                    await session.delete(assignment)
        await session.flush()
        first = min(s.start for s in outcome.spans)
        last = max((s.end or now) for s in outcome.spans)
        queued = await queue_reattribution(
            session,
            device_id=outcome.device_id,
            start=first,
            end=max(last, first),
            reason="device.moved",
            user_id=user_id,
            project_id=plan.project_id,
        )
        if queued.job is not None:
            outcome.attribution_job_id = queued.job.id
        if queued.created and queued.job is not None:
            jobs.append(queued.job)
    for entity_outcome in plan.entities.values():
        if not entity_outcome.moves or entity_outcome.project_id == plan.project_id:
            continue
        entity = await session.get(Entity, entity_outcome.entity_id)
        assert entity is not None
        entity.project_id = plan.project_id
        entity.group_id = plan.group_id
        state = await session.get(EntityCurrentState, entity.id)
        if state is not None:
            state.project_id = plan.project_id
        # what a rule wrote for the entity without a device rides with it; the device's own
        # records get their project through the job
        await session.execute(
            update(Event)
            .where(Event.entity_id == entity.id, Event.device_id.is_(None))
            .values(project_id=plan.project_id),
            execution_options={"synchronize_session": False},
        )
        await session.execute(
            update(Alert)
            .where(Alert.event_id == Event.id, Event.entity_id == entity.id)
            .where(Event.device_id.is_(None))
            .values(project_id=plan.project_id),
            execution_options={"synchronize_session": False},
        )
    await session.flush()
    return jobs


async def _replace_project_over(
    session: AsyncSession,
    device_id: uuid.UUID,
    span: Span,
    project_id: uuid.UUID,
    user_id: uuid.UUID | None,
    reason: str | None,
) -> None:
    """Over `span` the device belongs to `project_id`: every assignment overlapping it is cut
    at the span's edges, split around it, or removed, and a new one fills the span."""
    overlapping = (
        await session.scalars(
            select(DeviceProjectAssignment).where(
                DeviceProjectAssignment.device_id == device_id,
                DeviceProjectAssignment.validity.op("&&")(Range(span.start, span.end, bounds="[)")),
            )
        )
    ).all()
    for assignment in overlapping:
        lower, upper = _bounds(assignment.validity)
        before = lower < span.start
        after = span.end is not None and (upper is None or upper > span.end)
        if before and after:
            assignment.validity = Range(lower, span.start, bounds="[)")
            session.add(
                DeviceProjectAssignment(
                    device_id=device_id,
                    project_id=assignment.project_id,
                    validity=Range(span.end, upper, bounds="[)"),
                    reason=assignment.reason,
                    created_by_user_id=assignment.created_by_user_id,
                )
            )
        elif before:
            assignment.validity = Range(lower, span.start, bounds="[)")
        elif after:
            assignment.validity = Range(span.end, upper, bounds="[)")
        else:
            await session.delete(assignment)
    await session.flush()
    session.add(
        DeviceProjectAssignment(
            device_id=device_id,
            project_id=project_id,
            validity=Range(span.start, span.end, bounds="[)"),
            reason=reason,
            created_by_user_id=user_id,
        )
    )
    await session.flush()


async def project_names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        await session.execute(select(Project.id, Project.name).where(Project.id.in_(wanted)))
    ).all()
    return {row[0]: row[1] for row in rows}
