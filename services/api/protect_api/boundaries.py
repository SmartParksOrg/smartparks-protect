"""The API's side of a boundary move (decisions D355 to D358): the timeline read, the
permission rule, the audit rows, and one function that runs a plan, shared by the device
endpoints and the AI action endpoint so both paths do the same thing."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.attribution import job_read
from protect_api.audit import record_audit
from protect_api.deps import accessible_project_ids, is_project_admin, membership_access
from protect_api.routers.devices import project_assignment_read
from protect_api.routers.entities import assignment_read
from protect_api.schemas.domain import (
    AssignmentChangeRead,
    BoundaryResult,
    DeviceAssignmentsRead,
    EdgeChangeRead,
    EntityTimelineRow,
    LastMessageRead,
    ProjectTimelineRow,
)
from shared.bus import RedisStreamsBus
from shared.domain.attribution import active_job, publish_job, recent_jobs
from shared.domain.boundaries import (
    BoundaryPlan,
    CorrectionPlan,
    EdgeChange,
    Kind,
    apply_plan,
)
from shared.enums import AcquisitionChannel, ActorType
from shared.i18n import translate
from shared.models import (
    AuditLog,
    DataSource,
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    Entity,
    Project,
    SourceEvent,
    User,
)
from shared.permissions import Permission
from shared.timeutil import utc_now

ASSIGNMENT_TYPES = ("device_project_assignment", "device_entity_assignment")
# The channels a device speaks over live; an upload or a sync carries old records and says
# nothing about when the device changed hands.
LIVE_CHANNELS = (
    AcquisitionChannel.LORAWAN,
    AcquisitionChannel.IRIDIUM,
    AcquisitionChannel.CELLULAR,
    AcquisitionChannel.API,
)
SNAP_AFTER = timedelta(seconds=1)


async def _last_changes(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, AssignmentChangeRead]:
    """The newest audit row per assignment, with the person's name."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AuditLog, User.full_name, User.email)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(
                AuditLog.object_type.in_(ASSIGNMENT_TYPES),
                AuditLog.object_id.in_({str(i) for i in ids}),
            )
            .order_by(AuditLog.time.desc())
        )
    ).all()
    out: dict[uuid.UUID, AssignmentChangeRead] = {}
    for entry, full_name, email in rows:
        key = uuid.UUID(str(entry.object_id))
        if key in out:
            continue
        details: dict[str, Any] = dict(entry.details or {})
        out[key] = AssignmentChangeRead(
            time=entry.time,
            action=entry.action,
            user_name=full_name or email,
            reason=details.get("reason"),
            details=details,
        )
    return out


async def _may_edit(
    session: AsyncSession,
    user: User,
    project_ids: set[uuid.UUID],
    entity_projects: set[uuid.UUID],
) -> tuple[bool, bool]:
    """(project boundaries, entity boundaries) for the caller: the move rule for project rows,
    devices:write in every entity's project for entity rows (decision D355)."""
    if user.is_superuser:
        return True, True
    project_ok = bool(project_ids) and all(
        [await is_project_admin(session, user, p) for p in project_ids]
    )
    entity_ok = bool(entity_projects)
    for project_id in entity_projects:
        _role, permissions, _visibility = await membership_access(session, user, project_id)
        if Permission.DEVICES_WRITE not in permissions:
            entity_ok = False
            break
    return project_ok, entity_ok


async def read_timeline(session: AsyncSession, user: User, device: Device) -> DeviceAssignmentsRead:
    """The device's assignments in time order within the caller's projects, each with the
    newest attribution job touching it and its last change."""
    projects = await accessible_project_ids(user, session)
    pa_statement = select(DeviceProjectAssignment).where(
        DeviceProjectAssignment.device_id == device.id
    )
    ea_statement = (
        select(DeviceEntityAssignment, Entity.name, Entity.project_id)
        .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
        .where(DeviceEntityAssignment.device_id == device.id)
    )
    if projects is not None:
        pa_statement = pa_statement.where(DeviceProjectAssignment.project_id.in_(projects))
        ea_statement = ea_statement.where(Entity.project_id.in_(projects))
    project_rows = (
        await session.scalars(pa_statement.order_by(DeviceProjectAssignment.validity))
    ).all()
    entity_rows = (
        await session.execute(ea_statement.order_by(DeviceEntityAssignment.validity))
    ).all()
    names: dict[uuid.UUID, str] = {
        project_id: name
        for project_id, name in (
            await session.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_({a.project_id for a in project_rows})
                )
            )
        ).all()
    }
    jobs = await recent_jobs(session, device.id, limit=20)
    changes = await _last_changes(
        session, {a.id for a in project_rows} | {a.id for a, _, _ in entity_rows}
    )
    now = utc_now()

    def job_for(start: datetime, end: datetime | None) -> Any:
        # the newest job whose window overlaps or touches the row: a boundary moved to the
        # row's edge queues a job that starts exactly there
        upper = end or now
        for job in jobs:  # newest first
            if job.time_from <= upper and job.time_to >= start:
                return job_read(job)
        return None

    project_reads = []
    for a in project_rows:
        read = project_assignment_read(a, project_name=names.get(a.project_id))
        read.attribution_job = job_for(read.valid_from, read.valid_to)
        project_reads.append(ProjectTimelineRow(**read.model_dump(), last_change=changes.get(a.id)))
    entity_reads = []
    for a, entity_name, _project_id in entity_rows:
        entity_read = assignment_read(a, entity_name=entity_name)
        entity_read.attribution_job = job_for(entity_read.valid_from, entity_read.valid_to)
        entity_reads.append(
            EntityTimelineRow(**entity_read.model_dump(), last_change=changes.get(a.id))
        )
    can_project, can_entity = await _may_edit(
        session,
        user,
        {a.project_id for a in project_rows},
        {project_id for _, _, project_id in entity_rows},
    )
    active = await active_job(session, device.id)
    return DeviceAssignmentsRead(
        device_id=device.id,
        now=now,
        project_assignments=project_reads,
        entity_assignments=entity_reads,
        active_job=job_read(active),
        can_edit_project=can_project,
        can_edit_entity=can_entity,
    )


async def last_message_before(
    session: AsyncSession, device: Device, before: datetime
) -> LastMessageRead:
    """The device's newest live message before `before`, by the network's time when it has
    one, and the instant one second after it. The read is bounded to the 90 days before the
    instant, since the table is a hypertable keyed by arrival."""
    when = func.coalesce(SourceEvent.network_received_at, SourceEvent.ingested_at)
    row = (
        await session.execute(
            select(when, SourceEvent.acquisition_channel, DataSource.name)
            .join(DataSource, DataSource.id == SourceEvent.data_source_id)
            .where(
                SourceEvent.device_id == device.id,
                SourceEvent.acquisition_channel.in_([c.value for c in LIVE_CHANNELS]),
                SourceEvent.ingested_at < before + timedelta(days=1),
                SourceEvent.ingested_at > before - timedelta(days=90),
                when < before,
            )
            .order_by(when.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return LastMessageRead(time=None, snap_to=None)
    time, channel, source_name = row
    return LastMessageRead(
        time=time,
        snap_to=time + SNAP_AFTER,
        acquisition_channel=channel,
        data_source_name=source_name,
    )


async def _names(
    session: AsyncSession, changes: list[tuple[Kind, EdgeChange]]
) -> dict[uuid.UUID, str]:
    project_ids = {c.target_id for k, c in changes if k == "project"}
    entity_ids = {c.target_id for k, c in changes if k == "entity"}
    out: dict[uuid.UUID, str] = {}
    if project_ids:
        for project_id, name in (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all():
            out[project_id] = name
    if entity_ids:
        for entity_id, name in (
            await session.execute(select(Entity.id, Entity.name).where(Entity.id.in_(entity_ids)))
        ).all():
            out[entity_id] = name
    return out


def _kinded(plan: BoundaryPlan | CorrectionPlan) -> list[tuple[Kind, EdgeChange]]:
    if isinstance(plan, BoundaryPlan):
        return [(plan.kind, c) for c in plan.changes]
    return [(p.kind, c) for p in (plan.project, plan.entity) if p is not None for c in p.changes]


def _window(plan: BoundaryPlan | CorrectionPlan) -> tuple[datetime, datetime] | None:
    return plan.window


def _gap(plan: BoundaryPlan | CorrectionPlan) -> Any:
    if isinstance(plan, BoundaryPlan):
        return plan.gap
    for p in (plan.entity, plan.project):
        if p is not None and p.gap:
            return p.gap
    return None


def refuse(plan: BoundaryPlan | CorrectionPlan, language: str) -> None:
    """A refused plan is a 422 in the reader's language."""
    if plan.refused:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, translate(plan.refused, language)
        )


async def require_edit_rights(
    session: AsyncSession, user: User, targets: list[tuple[Kind, uuid.UUID]]
) -> None:
    """Decision D355: a project edge needs server admin or project admin of every project
    whose row changes; an entity edge needs devices:write in every such entity's project.
    `targets` are the projects and entities of the rows concerned."""
    if user.is_superuser:
        return
    project_ids = {target for k, target in targets if k == "project"}
    entity_ids = {target for k, target in targets if k == "entity"}
    entity_projects: set[uuid.UUID] = set()
    if entity_ids:
        entity_projects = {
            p
            for (p,) in (
                await session.execute(select(Entity.project_id).where(Entity.id.in_(entity_ids)))
            ).all()
        }
    can_project, can_entity = await _may_edit(session, user, project_ids, entity_projects)
    if project_ids and not can_project:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Project admin access to every project involved required"
        )
    if entity_ids and not can_entity:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "devices:write in the entity's project required"
        )


async def describe(
    session: AsyncSession, plan: BoundaryPlan | CorrectionPlan
) -> list[EdgeChangeRead]:
    changes = _kinded(plan)
    names = await _names(session, changes)
    return [
        EdgeChangeRead(
            kind=kind,
            assignment_id=c.assignment_id,
            target_id=c.target_id,
            target_name=names.get(c.target_id),
            edge=c.edge,
            old=c.old,
            new=c.new,
        )
        for kind, c in changes
    ]


def summary_text(
    device: Device, changes: list[EdgeChangeRead], window: tuple[datetime, datetime] | None
) -> str:
    """The words a person confirms (the AI action's summary): every row that changes with its
    old and new instant, and the window the records are attributed again over."""
    lines = [f"Move assignment boundaries of device {device.name}:"]
    for c in changes:
        old = c.old.isoformat() if c.old else "open"
        lines.append(
            f"- {c.kind} assignment {c.assignment_id} ({c.target_name or c.target_id}): "
            f"{c.edge} {old} -> {c.new.isoformat()}"
        )
    if window:
        lines.append(
            f"Records between {window[0].isoformat()} and {window[1].isoformat()} are "
            "attributed again to the project and entity of that time."
        )
    else:
        lines.append("No record changes hands.")
    return "\n".join(lines)


async def run_plan(
    session: AsyncSession,
    bus: RedisStreamsBus,
    *,
    user: User,
    device: Device,
    plan: BoundaryPlan | CorrectionPlan,
    reason: str,
    preview: bool,
    language: str,
    named: list[tuple[Kind, uuid.UUID]],
    actor_type: ActorType = ActorType.USER,
    client_id: str | None = None,
) -> BoundaryResult:
    """Check the rights on the rows named, refuse, check the rights on every row the plan
    touches, then either answer the preview or write the rows, the audit rows and the job,
    commit and publish."""
    await require_edit_rights(session, user, named)
    refuse(plan, language)
    changes = _kinded(plan)
    await require_edit_rights(session, user, [(k, c.target_id) for k, c in changes])
    described = await describe(session, plan)
    window = _window(plan)
    if preview or not changes:
        timeline = await read_timeline(session, user, device)
        return BoundaryResult(
            preview=True,
            changes=described,
            window_from=window[0] if window else None,
            window_to=window[1] if window else None,
            gap=_gap(plan),
            timeline=timeline,
        )
    kinds: dict[uuid.UUID, Kind] = {c.assignment_id: kind for kind, c in changes}
    # the job is filed under the project that holds the device at the new instant of the
    # first change, for the audit and the pages
    project_for_job = next(
        (c.target_id for kind, c in changes if kind == "project" and c.edge == "start"), None
    )
    queued = await apply_plan(
        session,
        device.id,
        [c for _, c in changes],
        kinds,
        window,
        user_id=user.id,
        project_id=project_for_job,
    )
    entity_projects: dict[uuid.UUID, uuid.UUID] = {}
    entity_ids = {c.target_id for k, c in changes if k == "entity"}
    if entity_ids:
        entity_projects = {
            entity_id: project_id
            for entity_id, project_id in (
                await session.execute(
                    select(Entity.id, Entity.project_id).where(Entity.id.in_(entity_ids))
                )
            ).all()
        }
    by_id = {c.assignment_id: c for c in described}
    for kind, change in changes:
        others = [
            str(c.assignment_id) for k, c in changes if c.assignment_id != change.assignment_id
        ]
        await record_audit(
            session,
            user=user,
            action=f"{kind}_assignment.boundary_moved",
            object_type=f"device_{kind}_assignment",
            object_id=str(change.assignment_id),
            project_id=change.target_id
            if kind == "project"
            else entity_projects.get(change.target_id),
            details={
                "device_id": str(device.id),
                "edge": change.edge,
                "from": change.old.isoformat() if change.old else None,
                "to": change.new.isoformat(),
                "reason": reason,
                "target_name": by_id[change.assignment_id].target_name,
                "with": others,
                "window": [window[0].isoformat(), window[1].isoformat()] if window else None,
                "attribution_job_id": str(queued.job.id) if queued.job else None,
                "client_id": client_id,
            },
            actor_type=actor_type,
        )
    await session.commit()
    if queued.created and queued.job is not None:
        await publish_job(bus, queued.job)
    timeline = await read_timeline(session, user, device)
    return BoundaryResult(
        preview=False,
        changes=described,
        window_from=window[0] if window else None,
        window_to=window[1] if window else None,
        gap=_gap(plan),
        attribution_job=job_read(queued.job),
        timeline=timeline,
    )
