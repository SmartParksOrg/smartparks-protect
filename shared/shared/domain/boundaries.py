"""Assignment boundaries moved after the fact (decisions D355 to D358).

A transfer stamps the moment it was made, and the moment a device really changed hands is
often known later: the last uplink before the handover, the day the collar went on the next
animal. A boundary of an assignment is moved here as one thing: the edge named and the
matching edge of the neighbour that touches it, so the device's timeline stays as contiguous
as it was. The rows' validity changes; the records change hands through an attribution job
over the span between the old and the new instant, as every assignment change does (decision
D206); raw messages are never touched. `move_edge` and `plan_row` are pure and say what a
move would do, `plan_boundary` and `plan_correction` read the rows, `apply_plan` writes
them, so the preview a page shows is what happens.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.attribution import QueueResult, queue_reattribution
from shared.models import DeviceEntityAssignment, DeviceProjectAssignment, Entity
from shared.timeutil import require_aware

Kind = Literal["project", "entity"]
Edge = Literal["start", "end"]
Gap = Literal["opens", "closes"]

# The refusals, fixed texts the reader's language translates (shared/i18n).
FUTURE = "the new instant lies in the future"
EMPTY = "the new instant would leave the assignment empty"
PREVIOUS_EMPTY = "the new instant would leave the previous assignment empty"
NEXT_EMPTY = "the new instant would leave the next assignment empty"
CROSSES = "the new instant crosses another assignment"
OUTSIDE_PROJECT = "the device is not in the entity's project over the new period"
REFUSALS = (FUTURE, EMPTY, PREVIOUS_EMPTY, NEXT_EMPTY, CROSSES, OUTSIDE_PROJECT)

# The reason on the attribution job the move queues
JOB_REASON = "assignment.boundary_moved"


@dataclass(frozen=True, slots=True)
class Bounds:
    """One assignment as the planner sees it: `end` None while current."""

    id: uuid.UUID
    target_id: uuid.UUID
    start: datetime
    end: datetime | None

    def overlaps(self, start: datetime, end: datetime) -> bool:
        """Whether the row holds any instant of `[start, end)`."""
        return self.start < end and (self.end is None or self.end > start)

    def covers(self, other: "Bounds") -> bool:
        """Whether `other`'s whole range lies inside this row."""
        if self.start > other.start:
            return False
        if self.end is None:
            return True
        return other.end is not None and other.end <= self.end


@dataclass(frozen=True, slots=True)
class EdgeChange:
    """One edge of one row moved from `old` to `new` (`old` None for an open end)."""

    assignment_id: uuid.UUID
    target_id: uuid.UUID
    edge: Edge
    old: datetime | None
    new: datetime

    @property
    def shrinks(self) -> bool:
        """Whether the row loses time: a start moved later, an end moved earlier or set."""
        if self.edge == "start":
            return self.old is not None and self.new > self.old
        return self.old is None or self.new < self.old


@dataclass(slots=True)
class BoundaryPlan:
    """What a boundary move does: the edges that change, the window the records are
    attributed again over, whether unassigned time opens or closes where no neighbour
    touches the boundary, or why it is refused."""

    kind: Kind
    changes: list[EdgeChange] = field(default_factory=list)
    window: tuple[datetime, datetime] | None = None
    gap: Gap | None = None
    refused: str | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None


def _refused(kind: Kind, why: str) -> BoundaryPlan:
    return BoundaryPlan(kind, refused=why)


def move_edge(
    kind: Kind,
    rows: Sequence[Bounds],
    assignment_id: uuid.UUID,
    edge: Edge,
    new: datetime,
    now: datetime,
) -> BoundaryPlan:
    """Move one edge of one row to `new` and the touching edge of its neighbour with it. The
    neighbour is the row whose edge equals the boundary exactly; a boundary nothing touches
    moves alone and the plan says whether unassigned time opens or closes. Refused when the
    instant lies in the future, would leave this row or the neighbour empty, or would cross a
    row that is not the neighbour."""
    require_aware(new)
    require_aware(now)
    row = next(r for r in rows if r.id == assignment_id)
    if new > now:
        return _refused(kind, FUTURE)
    others = [r for r in rows if r.id != row.id]
    gap: Gap | None = None
    if edge == "start":
        old = row.start
        if new == old:
            return BoundaryPlan(kind)
        if row.end is not None and new >= row.end:
            return _refused(kind, EMPTY)
        changes = [EdgeChange(row.id, row.target_id, "start", old, new)]
        neighbour = next((r for r in others if r.end == old), None)
        if neighbour is not None:
            if new <= neighbour.start:
                return _refused(kind, PREVIOUS_EMPTY)
            changes.append(EdgeChange(neighbour.id, neighbour.target_id, "end", old, new))
        elif new < old:
            if any(r.overlaps(new, old) for r in others):
                return _refused(kind, CROSSES)
            gap = "closes"
        else:
            gap = "opens"
        return BoundaryPlan(kind, changes, (min(old, new), max(old, new)), gap)
    old_end = row.end
    old_effective = old_end if old_end is not None else now
    if new == old_end:
        return BoundaryPlan(kind)
    if new <= row.start:
        return _refused(kind, EMPTY)
    changes = [EdgeChange(row.id, row.target_id, "end", old_end, new)]
    neighbour = (
        next((r for r in others if r.start == old_end), None) if old_end is not None else None
    )
    if neighbour is not None:
        if neighbour.end is not None and new >= neighbour.end:
            return _refused(kind, NEXT_EMPTY)
        changes.append(EdgeChange(neighbour.id, neighbour.target_id, "start", old_end, new))
    elif new > old_effective:
        if any(r.overlaps(old_effective, new) for r in others):
            return _refused(kind, CROSSES)
        gap = "closes"
    else:
        gap = "opens"
    return BoundaryPlan(kind, changes, (min(old_effective, new), max(old_effective, new)), gap)


def apply_changes(rows: Sequence[Bounds], changes: Sequence[EdgeChange]) -> list[Bounds]:
    """The rows as they stand after `changes`."""
    out: list[Bounds] = []
    for row in rows:
        start, end = row.start, row.end
        for change in changes:
            if change.assignment_id != row.id:
                continue
            if change.edge == "start":
                start = change.new
            else:
                end = change.new
        out.append(Bounds(row.id, row.target_id, start, end))
    return out


def merge(first: BoundaryPlan, second: BoundaryPlan) -> BoundaryPlan:
    """Two plans as one: the changes of both, one window over both, refused when either is."""
    if not first.ok:
        return first
    if not second.ok:
        return second
    window = first.window
    if second.window is not None:
        window = (
            (min(window[0], second.window[0]), max(window[1], second.window[1]))
            if window is not None
            else second.window
        )
    return BoundaryPlan(
        first.kind, [*first.changes, *second.changes], window, second.gap or first.gap
    )


def plan_row(
    kind: Kind,
    rows: Sequence[Bounds],
    assignment_id: uuid.UUID,
    *,
    new_from: datetime | None,
    new_to: datetime | None,
    now: datetime,
) -> BoundaryPlan:
    """Move the start, the end, or both edges of one row, each with its neighbour."""
    plan = BoundaryPlan(kind)
    current = list(rows)
    if new_from is not None:
        plan = move_edge(kind, current, assignment_id, "start", new_from, now)
        if not plan.ok:
            return plan
        current = apply_changes(current, plan.changes)
    if new_to is not None:
        plan = merge(plan, move_edge(kind, current, assignment_id, "end", new_to, now))
    return plan


def nearest_edge(row: Bounds, instant: datetime, now: datetime) -> Edge:
    """The edge of `row` closest to `instant`, an open end counting as now."""
    end = row.end if row.end is not None else now
    return "start" if abs(row.start - instant) <= abs(end - instant) else "end"


def entity_rows_covered(
    project_rows: Sequence[Bounds],
    entity_rows: Sequence[Bounds],
    entity_projects: dict[uuid.UUID, uuid.UUID],
) -> bool:
    """Whether every entity row lies whole inside one project row of its entity's project:
    the rule every entity assignment change keeps (the device belongs to the project over
    the period), judged against the project rows as they will stand."""
    for row in entity_rows:
        project_id = entity_projects.get(row.target_id)
        if project_id is None:
            return False
        if not any(p.target_id == project_id and p.covers(row) for p in project_rows):
            return False
    return True


def bounds_of(row: DeviceProjectAssignment | DeviceEntityAssignment) -> Bounds:
    target = row.project_id if isinstance(row, DeviceProjectAssignment) else row.entity_id
    return Bounds(row.id, target, row.validity.lower, row.validity.upper)


async def load_bounds(session: AsyncSession, device_id: uuid.UUID, kind: Kind) -> list[Bounds]:
    if kind == "project":
        projects = await session.scalars(
            select(DeviceProjectAssignment).where(DeviceProjectAssignment.device_id == device_id)
        )
        return sorted((bounds_of(r) for r in projects.all()), key=lambda b: b.start)
    entities = await session.scalars(
        select(DeviceEntityAssignment).where(DeviceEntityAssignment.device_id == device_id)
    )
    return sorted((bounds_of(r) for r in entities.all()), key=lambda b: b.start)


async def _entity_projects(
    session: AsyncSession, entity_ids: set[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    if not entity_ids:
        return {}
    rows = await session.execute(
        select(Entity.id, Entity.project_id).where(Entity.id.in_(entity_ids))
    )
    return {entity_id: project_id for entity_id, project_id in rows.all()}


async def _check_entity_plan(
    session: AsyncSession,
    project_rows: Sequence[Bounds],
    entity_rows: Sequence[Bounds],
    plan: BoundaryPlan,
) -> BoundaryPlan:
    if not plan.ok or not plan.changes:
        return plan
    after = apply_changes(entity_rows, plan.changes)
    changed = {c.assignment_id for c in plan.changes}
    rows = [r for r in after if r.id in changed]
    projects = await _entity_projects(session, {r.target_id for r in rows})
    if not entity_rows_covered(project_rows, rows, projects):
        return _refused("entity", OUTSIDE_PROJECT)
    return plan


async def plan_boundary(
    session: AsyncSession,
    kind: Kind,
    device_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    new_from: datetime | None,
    new_to: datetime | None,
    now: datetime,
) -> BoundaryPlan:
    """The plan for one row of the device, with the entity rule checked for entity rows."""
    rows = await load_bounds(session, device_id, kind)
    plan = plan_row(kind, rows, assignment_id, new_from=new_from, new_to=new_to, now=now)
    if kind == "entity":
        project_rows = await load_bounds(session, device_id, "project")
        plan = await _check_entity_plan(session, project_rows, rows, plan)
    return plan


@dataclass(slots=True)
class CorrectionPlan:
    """A project boundary and an entity boundary moved to one instant (the brief's chained
    correction): both plans, one window, refused when either is."""

    project: BoundaryPlan | None
    entity: BoundaryPlan | None

    @property
    def refused(self) -> str | None:
        for plan in (self.project, self.entity):
            if plan is not None and plan.refused:
                return plan.refused
        return None

    @property
    def ok(self) -> bool:
        return self.refused is None

    @property
    def window(self) -> tuple[datetime, datetime] | None:
        windows = [p.window for p in (self.project, self.entity) if p is not None and p.window]
        if not windows:
            return None
        return min(w[0] for w in windows), max(w[1] for w in windows)

    @property
    def changes(self) -> list[EdgeChange]:
        return [c for p in (self.project, self.entity) if p is not None for c in p.changes]

    @property
    def kinds(self) -> dict[uuid.UUID, Kind]:
        out: dict[uuid.UUID, Kind] = {}
        for plan in (self.project, self.entity):
            if plan is not None:
                for change in plan.changes:
                    out[change.assignment_id] = plan.kind
        return out


async def plan_correction(
    session: AsyncSession,
    device_id: uuid.UUID,
    *,
    project_assignment_id: uuid.UUID | None,
    entity_assignment_id: uuid.UUID | None,
    instant: datetime,
    now: datetime,
    project_edge: Edge | None = None,
    entity_edge: Edge | None = None,
) -> CorrectionPlan:
    """Both boundaries to `instant`. The edge of each row is the one nearest the instant
    unless named. The entity plan is judged against the project rows as they will stand, so
    a boundary moved on both sides at once stays consistent."""
    project_plan: BoundaryPlan | None = None
    project_rows = await load_bounds(session, device_id, "project")
    if project_assignment_id is not None:
        row = next(r for r in project_rows if r.id == project_assignment_id)
        edge = project_edge or nearest_edge(row, instant, now)
        project_plan = move_edge("project", project_rows, row.id, edge, instant, now)
        if project_plan.ok:
            project_rows = apply_changes(project_rows, project_plan.changes)
    entity_plan: BoundaryPlan | None = None
    if entity_assignment_id is not None:
        entity_rows = await load_bounds(session, device_id, "entity")
        row = next(r for r in entity_rows if r.id == entity_assignment_id)
        edge = entity_edge or nearest_edge(row, instant, now)
        entity_plan = move_edge("entity", entity_rows, row.id, edge, instant, now)
        if project_plan is None or project_plan.ok:
            entity_plan = await _check_entity_plan(session, project_rows, entity_rows, entity_plan)
    return CorrectionPlan(project_plan, entity_plan)


async def apply_plan(
    session: AsyncSession,
    device_id: uuid.UUID,
    changes: Sequence[EdgeChange],
    kinds: dict[uuid.UUID, Kind],
    window: tuple[datetime, datetime] | None,
    *,
    user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> QueueResult:
    """Write the changed edges and queue the attribution job over the window. The rows that
    lose time are written first and each change is flushed on its own: the exclusion
    constraint is checked per statement, so the neighbour must give the instants up before
    the row takes them. The caller writes the audit rows, commits and publishes a created
    job."""
    for change in sorted(changes, key=lambda c: not c.shrinks):
        row: DeviceProjectAssignment | DeviceEntityAssignment | None
        if kinds[change.assignment_id] == "project":
            row = await session.get(DeviceProjectAssignment, change.assignment_id)
        else:
            row = await session.get(DeviceEntityAssignment, change.assignment_id)
        assert row is not None
        lower, upper = row.validity.lower, row.validity.upper
        if change.edge == "start":
            lower = change.new
        else:
            upper = change.new
        row.validity = Range(lower, upper, bounds="[)")
        await session.flush()
    if window is None or window[1] <= window[0]:
        return QueueResult(None, created=False)
    return await queue_reattribution(
        session,
        device_id=device_id,
        start=window[0],
        end=window[1],
        reason=JOB_REASON,
        user_id=user_id,
        project_id=project_id,
    )
