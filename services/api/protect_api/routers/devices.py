"""Devices are server-level objects. Project membership is a time-bounded assignment; moving a
device is a handover that closes one assignment and opens the next (architecture 28)."""

import csv
import io
import uuid
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.crud import apply_patch, flush_or_409, get_or_404, range_bounds
from protect_api.deps import accessible_project_ids, require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.pictures import drop_picture, picture_response, store_picture
from protect_api.routers.entities import assignment_read, group_and_subgroups
from protect_api.schemas.domain import (
    AssignmentEnd,
    AssignmentStart,
    DeviceCreate,
    DeviceDataSpan,
    DeviceRead,
    DeviceUpdate,
    DeviceWithAssignments,
    ExternalIdentityCreate,
    ExternalIdentityRead,
    HandoverRequest,
    ImportResult,
    ImportRowResult,
    ProjectAssignmentCreate,
    ProjectAssignmentExtended,
    ProjectAssignmentRead,
    ReattributeRequest,
    ReattributeResult,
    RecordCounts,
)
from protect_api.serial import fill_serial_from_identity
from shared.config import get_settings
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.satellite import SatelliteSession
from shared.curation.effective import effective_time
from shared.database import get_session
from shared.device_drivers.registry import DRIVERS
from shared.domain.assignments import reattribute, resolve_attribution
from shared.domain.health import device_health
from shared.domain.links import resolve_links
from shared.enums import AcquisitionChannel, DeviceStatus, Role
from shared.models import (
    ConnectivityState,
    DataSource,
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    DeviceLogFile,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityType,
    ExternalIdentity,
    Gateway,
    GatewayReception,
    Group,
    Measurement,
    Position,
    Project,
    ProjectMembership,
    SourceEvent,
    User,
)
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/devices", tags=["devices"])


def project_assignment_read(
    assignment: DeviceProjectAssignment, *, project_name: str | None = None
) -> ProjectAssignmentRead:
    valid_from, valid_to = range_bounds(assignment.validity)
    return ProjectAssignmentRead(
        id=assignment.id,
        device_id=assignment.device_id,
        project_id=assignment.project_id,
        project_name=project_name,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=assignment.reason,
        created_at=assignment.created_at,
    )


async def _is_project_admin(session: AsyncSession, user: User, project_id: uuid.UUID) -> bool:
    if user.is_superuser:
        return True
    role = await session.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.user_id == user.id, ProjectMembership.project_id == project_id
        )
    )
    return role == Role.PROJECT_ADMIN


async def _require_project_admin(session: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    if not await _is_project_admin(session, user, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Project admin access required")


async def _visible_device(session: AsyncSession, user: User, device_id: uuid.UUID) -> Device:
    """A device is visible to server admins and to members of any project it was ever assigned
    to (architecture 28.12: access follows historical attribution)."""
    device = await get_or_404(session, Device, device_id, "Device")
    if user.is_superuser:
        return device
    projects = await accessible_project_ids(user, session)
    assigned = await session.scalar(
        select(func.count())
        .select_from(DeviceProjectAssignment)
        .where(
            DeviceProjectAssignment.device_id == device_id,
            DeviceProjectAssignment.project_id.in_(projects or []),
        )
    )
    if not assigned:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    return device


async def with_state(session: AsyncSession, devices: list[Device]) -> list[DeviceRead]:
    """Device reads with last seen and health from the current state, one query for all."""
    reads = [DeviceRead.model_validate(d) for d in devices]
    if not devices:
        return reads
    ids = [d.id for d in devices]
    states = {
        s.device_id: s
        for s in (
            await session.scalars(
                select(DeviceCurrentState).where(DeviceCurrentState.device_id.in_(ids))
            )
        ).all()
    }
    types = {
        t.id: t
        for t in (
            await session.scalars(
                select(DeviceType).where(DeviceType.id.in_({d.device_type_id for d in devices}))
            )
        ).all()
    }
    now = utc_now()
    tracking = {
        device_id: (entity_id, name, group_id)
        for device_id, entity_id, name, group_id in (
            await session.execute(
                select(DeviceEntityAssignment.device_id, Entity.id, Entity.name, Entity.group_id)
                .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
                .where(
                    DeviceEntityAssignment.device_id.in_(ids),
                    DeviceEntityAssignment.validity.op("@>")(now),
                )
            )
        ).all()
    }
    current_projects = {
        device_id: project_id
        for device_id, project_id in (
            await session.execute(
                select(DeviceProjectAssignment.device_id, DeviceProjectAssignment.project_id).where(
                    DeviceProjectAssignment.device_id.in_(ids),
                    DeviceProjectAssignment.validity.op("@>")(now),
                )
            )
        ).all()
    }
    source_names: dict[uuid.UUID, list[str]] = {}
    for device_id, name in (
        await session.execute(
            select(ExternalIdentity.device_id, DataSource.name)
            .join(DataSource, DataSource.id == ExternalIdentity.data_source_id)
            .where(ExternalIdentity.device_id.in_(ids), ExternalIdentity.ignored.is_(False))
            .distinct()
            .order_by(DataSource.name)
        )
    ).all():
        source_names.setdefault(device_id, []).append(name)
    for device, read in zip(devices, reads, strict=True):
        read.project_id = current_projects.get(device.id)
        read.data_source_names = source_names.get(device.id, [])
        if device.id in tracking:
            read.entity_id, read.entity_name, read.group_id = tracking[device.id]
        state = states.get(device.id)
        if state is None:
            continue
        device_type = types.get(device.device_type_id)
        driver = DRIVERS.get(device_type.driver_key) if device_type else None
        read.last_seen_at = state.last_seen_at
        read.health = device_health(
            getattr(driver, "health", None),
            latest_measurements=state.latest_measurements,
            latest_state=state.latest_state,
            latest_state_time=state.latest_state_time,
            last_seen_at=state.last_seen_at,
        )
    return reads


@router.get("", response_model=PageResponse[DeviceRead])
async def list_devices(
    page: Page = Depends(page),
    project_id: uuid.UUID | None = None,
    status_filter: DeviceStatus | None = None,
    q: str | None = Query(None, description="Matches the name, the serial and any identity"),
    data_source_id: uuid.UUID | None = Query(
        None, description="Only devices with an identity (not ignored) on this data source"
    ),
    device_type_id: uuid.UUID | None = None,
    has_entity: bool | None = Query(
        None, description="True: tracks an entity today; false: tracks none (any project)"
    ),
    unassigned: bool = Query(
        False, description="Only devices that track no entity right now (needs project_id)"
    ),
    group_id: uuid.UUID | None = Query(
        None,
        description="Only devices whose entity today is in this group or its subgroups "
        "(needs project_id, decision D98)",
    ),
    in_no_project: bool = Query(
        False,
        description="Only devices assigned to no project today: inventory, workshop, freshly "
        "onboarded (server admins, decision D120)",
    ),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[DeviceRead]:
    """Server admins see every device. Others see devices currently assigned to their projects.
    `project_id` narrows to devices currently assigned to that project; `unassigned` to those
    of them without an entity today, the candidates of an entity's "Assign device"
    (decision D106)."""
    statement = select(Device)
    now = utc_now()
    if (unassigned or group_id is not None) and project_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unassigned and group_id need project_id"
        )
    if in_no_project:
        if not user.is_superuser:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Server admin access required")
        if project_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "in_no_project excludes project_id"
            )
        statement = statement.where(
            ~exists().where(
                DeviceProjectAssignment.device_id == Device.id,
                DeviceProjectAssignment.validity.op("@>")(now),
            )
        )
    if group_id is not None:
        statement = statement.where(
            exists().where(
                DeviceEntityAssignment.device_id == Device.id,
                DeviceEntityAssignment.validity.op("@>")(now),
                DeviceEntityAssignment.entity_id == Entity.id,
                Entity.group_id.in_(group_and_subgroups(group_id)),
            )
        )
    if unassigned:
        statement = statement.where(
            ~exists().where(
                DeviceEntityAssignment.device_id == Device.id,
                DeviceEntityAssignment.validity.op("@>")(now),
            )
        )
    if project_id is not None:
        if not user.is_superuser and project_id not in (
            await accessible_project_ids(user, session) or []
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this project")
        statement = statement.join(
            DeviceProjectAssignment, DeviceProjectAssignment.device_id == Device.id
        ).where(
            DeviceProjectAssignment.project_id == project_id,
            DeviceProjectAssignment.validity.op("@>")(now),
        )
    elif not user.is_superuser:
        projects = await accessible_project_ids(user, session) or []
        statement = (
            statement.join(DeviceProjectAssignment, DeviceProjectAssignment.device_id == Device.id)
            .where(
                DeviceProjectAssignment.project_id.in_(projects),
                DeviceProjectAssignment.validity.op("@>")(now),
            )
            .distinct()
        )
    if status_filter is not None:
        statement = statement.where(Device.status == status_filter)
    if device_type_id is not None:
        statement = statement.where(Device.device_type_id == device_type_id)
    if data_source_id is not None:
        statement = statement.where(
            exists().where(
                ExternalIdentity.device_id == Device.id,
                ExternalIdentity.data_source_id == data_source_id,
                ExternalIdentity.ignored.is_(False),
            )
        )
    if has_entity is not None:
        tracks = exists().where(
            DeviceEntityAssignment.device_id == Device.id,
            DeviceEntityAssignment.validity.op("@>")(now),
        )
        statement = statement.where(tracks if has_entity else ~tracks)
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(
                Device.name.ilike(pattern),
                Device.serial_number.ilike(pattern),
                exists().where(
                    ExternalIdentity.device_id == Device.id,
                    ExternalIdentity.external_id.ilike(pattern),
                ),
            )
        )
    rows, next_cursor = await paginate(session, Device.id, statement, page)
    return PageResponse(items=await with_state(session, list(rows)), next_cursor=next_cursor)


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Device:
    await get_or_404(session, DeviceType, body.device_type_id, "Device type")
    device = Device(**body.model_dump())
    session.add(device)
    await flush_or_409(session, "Device")
    await record_audit(
        session,
        user=user,
        action="device.created",
        object_type="device",
        object_id=str(device.id),
        details={"name": device.name},
    )
    await session.commit()
    return device


@router.get("/{device_id}/picture", response_class=Response)
async def get_device_picture(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The device's profile picture (decision D110), a WebP square, for whoever may see the
    device."""
    device = await _visible_device(session, user, device_id)
    return await picture_response(device.picture_key, device.picture_updated_at)


@router.put("/{device_id}/picture", response_model=DeviceRead)
async def set_device_picture(
    device_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    """Set the profile picture from a JPEG, PNG or WebP; the server keeps a small square."""
    device = await get_or_404(session, Device, device_id, "Device")
    device.picture_key, device.picture_updated_at = await store_picture("devices", device.id, file)
    await record_audit(
        session,
        user=user,
        action="device.picture_set",
        object_type="device",
        object_id=str(device.id),
        details={"name": device.name},
    )
    await session.commit()
    await session.refresh(device)
    return (await with_state(session, [device]))[0]


@router.delete("/{device_id}/picture", response_model=DeviceRead)
async def remove_device_picture(
    device_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceRead:
    device = await get_or_404(session, Device, device_id, "Device")
    await drop_picture(device.picture_key)
    device.picture_key, device.picture_updated_at = None, None
    await record_audit(
        session,
        user=user,
        action="device.picture_removed",
        object_type="device",
        object_id=str(device.id),
        details={"name": device.name},
    )
    await session.commit()
    await session.refresh(device)
    return (await with_state(session, [device]))[0]


@router.get("/{device_id}", response_model=DeviceWithAssignments)
async def get_device(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceWithAssignments:
    device = await _visible_device(session, user, device_id)
    projects = await accessible_project_ids(user, session)
    pa_statement = select(DeviceProjectAssignment).where(
        DeviceProjectAssignment.device_id == device.id
    )
    ea_statement = (
        select(DeviceEntityAssignment)
        .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
        .where(DeviceEntityAssignment.device_id == device.id)
    )
    if projects is not None:
        pa_statement = pa_statement.where(DeviceProjectAssignment.project_id.in_(projects))
        ea_statement = ea_statement.where(Entity.project_id.in_(projects))
    project_assignments = (
        await session.scalars(pa_statement.order_by(DeviceProjectAssignment.validity))
    ).all()
    entity_assignments = (
        await session.scalars(ea_statement.order_by(DeviceEntityAssignment.validity))
    ).all()
    entity_names = {
        entity_id: name
        for entity_id, name in (
            await session.execute(
                select(Entity.id, Entity.name).where(
                    Entity.id.in_({a.entity_id for a in entity_assignments})
                )
            )
        ).all()
    }
    project_names = {
        project_id: name
        for project_id, name in (
            await session.execute(
                select(Project.id, Project.name).where(
                    Project.id.in_({a.project_id for a in project_assignments})
                )
            )
        ).all()
    }
    identities = (
        await session.scalars(
            select(ExternalIdentity).where(ExternalIdentity.device_id == device.id)
        )
    ).all()
    sources = {
        s.id: s
        for s in (
            await session.scalars(
                select(DataSource).where(DataSource.id.in_({i.data_source_id for i in identities}))
            )
        ).all()
    }
    links = [
        link
        for identity in identities
        for link in resolve_links(sources[identity.data_source_id], identity)
    ]
    return DeviceWithAssignments(
        **(await with_state(session, [device]))[0].model_dump(),
        project_assignments=[
            project_assignment_read(a, project_name=project_names.get(a.project_id))
            for a in project_assignments
        ],
        entity_assignments=[
            assignment_read(a, entity_name=entity_names.get(a.entity_id))
            for a in entity_assignments
        ],
        external_identities=[ExternalIdentityRead.model_validate(i) for i in identities],
        links=links,
    )


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: uuid.UUID,
    body: DeviceUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Device:
    device = await get_or_404(session, Device, device_id, "Device")
    if body.device_type_id is not None:
        await get_or_404(session, DeviceType, body.device_type_id, "Device type")
    changed = apply_patch(device, body)
    await flush_or_409(session, "Device")
    await record_audit(
        session,
        user=user,
        action="device.updated",
        object_type="device",
        object_id=str(device.id),
        details=changed,
    )
    await session.commit()
    return device


# Project assignments


class BulkAssign(BaseModel):
    """Assign a selection of devices to one project at once (decision D122)."""

    device_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    project_id: uuid.UUID
    valid_from: datetime | None = Field(
        None,
        description="Start of every assignment; without it each device starts at its first data "
        "(records, identity first seen, log files), or now when it has none",
    )
    entity_type_id: uuid.UUID | None = Field(
        None, description="Also create an entity of this type per device, named as the device"
    )
    group_id: uuid.UUID | None = None


class BulkAssignSkipped(BaseModel):
    device_id: uuid.UUID
    name: str | None = None
    reason: str


class BulkAssignResult(BaseModel):
    assigned: int
    entities: int
    reattributed: RecordCounts
    skipped: list[BulkAssignSkipped]


async def _first_data_at(session: AsyncSession, device_id: uuid.UUID) -> datetime | None:
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


@router.post("/bulk-assign", response_model=BulkAssignResult, status_code=status.HTTP_201_CREATED)
async def bulk_assign(
    body: BulkAssign,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> BulkAssignResult:
    """Devices in no project, onboarded in bulk, join a project in one go (decision D122): each
    gets an assignment from its first data unless a start is given, optionally an entity of one
    type with the device's name, and the records inside the range get the project (D103). A
    device assigned anywhere in that range is skipped; an entity name already taken in the
    project leaves that device without one."""
    project = await get_or_404(session, Project, body.project_id, "Project")
    if body.valid_from is not None:
        body.valid_from = require_aware(body.valid_from)
    if body.entity_type_id is not None:
        await get_or_404(session, EntityType, body.entity_type_id, "Entity type")
    if body.group_id is not None:
        if body.entity_type_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A group needs entities: set entity_type_id"
            )
        group = await get_or_404(session, Group, body.group_id, "Group")
        if group.project_id != project.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found in this project")
    devices = {
        d.id: d
        for d in (
            await session.scalars(select(Device).where(Device.id.in_(set(body.device_ids))))
        ).all()
    }
    taken_entities: set[str] = set()
    if body.entity_type_id is not None:
        taken_entities = set(
            (
                await session.scalars(
                    select(Entity.name).where(
                        Entity.project_id == project.id,
                        Entity.name.in_([d.name for d in devices.values()]),
                    )
                )
            ).all()
        )
    projects_by_id = {
        p.id: p.name
        for p in (
            await session.scalars(
                select(Project).where(
                    Project.id.in_(
                        select(DeviceProjectAssignment.project_id).where(
                            DeviceProjectAssignment.device_id.in_(devices.keys())
                        )
                    )
                )
            )
        ).all()
    }
    now = utc_now()
    assigned = entities = 0
    reattributed = {"positions": 0, "measurements": 0}
    skipped: list[BulkAssignSkipped] = []
    for device_id in dict.fromkeys(body.device_ids):  # in the caller's order, once each
        device = devices.get(device_id)
        if device is None:
            skipped.append(BulkAssignSkipped(device_id=device_id, reason="not found"))
            continue
        start = body.valid_from or await _first_data_at(session, device.id) or now
        overlapping = await session.scalar(
            select(DeviceProjectAssignment)
            .where(
                DeviceProjectAssignment.device_id == device.id,
                DeviceProjectAssignment.validity.op("&&")(Range(start, None, bounds="[)")),
            )
            .order_by(func.lower(DeviceProjectAssignment.validity))
            .limit(1)
        )
        if overlapping is not None:
            where = projects_by_id.get(overlapping.project_id, "a project")
            reason = (
                "already in this project"
                if overlapping.project_id == project.id
                else f"assigned to {where} since {range_bounds(overlapping.validity)[0]:%Y-%m-%d}"
            )
            skipped.append(BulkAssignSkipped(device_id=device.id, name=device.name, reason=reason))
            continue
        session.add(
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project.id,
                validity=Range(start, None, bounds="[)"),
                reason="bulk assignment",
                created_by_user_id=user.id,
            )
        )
        details: dict[str, Any] = {"device_id": str(device.id), "valid_from": start.isoformat()}
        if body.entity_type_id is not None and device.name not in taken_entities:
            entity = Entity(
                project_id=project.id,
                entity_type_id=body.entity_type_id,
                group_id=body.group_id,
                name=device.name,
            )
            session.add(entity)
            await session.flush()
            session.add(
                DeviceEntityAssignment(
                    device_id=device.id,
                    entity_id=entity.id,
                    validity=Range(start, None, bounds="[)"),
                    reason="bulk assignment",
                    created_by_user_id=user.id,
                )
            )
            taken_entities.add(device.name)
            entities += 1
            details["entity_id"] = str(entity.id)
        await flush_or_409(session, "Bulk assignment")
        counts = await reattribute(session, device.id, start, now)
        for key in reattributed:
            reattributed[key] += int(counts.get(key, 0))
        details["reattributed"] = counts
        await record_audit(
            session,
            user=user,
            action="project_assignment.created",
            object_type="device",
            object_id=str(device.id),
            project_id=project.id,
            details={**details, "bulk": True},
        )
        assigned += 1
    await session.commit()
    return BulkAssignResult(
        assigned=assigned,
        entities=entities,
        reattributed=RecordCounts(**reattributed),
        skipped=skipped,
    )


@router.post(
    "/{device_id}/project-assignments",
    response_model=ProjectAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_to_project(
    device_id: uuid.UUID,
    body: ProjectAssignmentCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectAssignmentRead:
    """Server admins, or admins of the target project. Overlaps are rejected: use the handover
    endpoint to move a device that is assigned elsewhere."""
    await _require_project_admin(session, user, body.project_id)
    device = await get_or_404(session, Device, device_id, "Device")
    await get_or_404(session, Project, body.project_id, "Project")
    if body.valid_to is not None and body.valid_to <= body.valid_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    assignment = DeviceProjectAssignment(
        device_id=device.id,
        project_id=body.project_id,
        validity=Range(body.valid_from, body.valid_to, bounds="[)"),
        reason=body.reason,
        created_by_user_id=user.id,
    )
    session.add(assignment)
    await flush_or_409(session, "Project assignment")
    # Records already decoded inside the range (a raw log, data before onboarding) get the
    # project now (decision D103); nothing is fabricated for the future.
    counts = await reattribute(session, device.id, body.valid_from, body.valid_to or utc_now())
    await record_audit(
        session,
        user=user,
        action="project_assignment.created",
        object_type="device_project_assignment",
        object_id=str(assignment.id),
        project_id=body.project_id,
        details={
            "device_id": str(device.id),
            "valid_from": body.valid_from.isoformat(),
            "reattributed": counts,
        },
    )
    await session.commit()
    return project_assignment_read(assignment)


async def _record_counts(
    session: AsyncSession, device_id: uuid.UUID, before: datetime | None
) -> RecordCounts:
    if before is None:
        return RecordCounts()
    counts = {}
    for model, name in ((Position, "positions"), (Measurement, "measurements")):
        when = effective_time(model)
        counts[name] = int(
            await session.scalar(
                select(func.count()).where(model.device_id == device_id, when < before)
            )
            or 0
        )
    return RecordCounts(**counts)


@router.get("/{device_id}/data-span", response_model=DeviceDataSpan)
async def device_data_span(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceDataSpan:
    """When the device produced data and how many records sit before its assignments, so the
    dialogs can offer the right start and the device page can offer the repair (D103)."""
    device = await _visible_device(session, user, device_id)
    firsts: list[datetime] = []
    lasts: list[datetime] = []
    for model in (Position, Measurement):
        when = effective_time(model)
        row = (
            await session.execute(
                select(func.min(when), func.max(when)).where(model.device_id == device.id)
            )
        ).one()
        if row[0] is not None:
            firsts.append(row[0])
            lasts.append(row[1])
    first_seen = await session.scalar(
        select(func.min(ExternalIdentity.first_seen_at)).where(
            ExternalIdentity.device_id == device.id
        )
    )
    first_log = await session.scalar(
        select(func.min(DeviceLogFile.period_start)).where(DeviceLogFile.device_id == device.id)
    )
    candidates = [t for t in [min(firsts, default=None), first_seen, first_log] if t is not None]
    project_assignment = (
        await session.execute(
            select(DeviceProjectAssignment)
            .where(DeviceProjectAssignment.device_id == device.id)
            .order_by(func.lower(DeviceProjectAssignment.validity))
            .limit(1)
        )
    ).scalar_one_or_none()
    entity_assignment = (
        await session.execute(
            select(DeviceEntityAssignment)
            .where(DeviceEntityAssignment.device_id == device.id)
            .order_by(func.lower(DeviceEntityAssignment.validity))
            .limit(1)
        )
    ).scalar_one_or_none()
    project_from = range_bounds(project_assignment.validity)[0] if project_assignment else None
    entity_from = range_bounds(entity_assignment.validity)[0] if entity_assignment else None
    horizon = utc_now() + timedelta(seconds=get_settings().clock_ahead_tolerance_seconds)
    ahead = RecordCounts()
    ahead_until: datetime | None = None
    for model, attr in ((Position, "positions"), (Measurement, "measurements")):
        count, until = (
            await session.execute(
                select(func.count(), func.max(effective_time(model))).where(
                    model.device_id == device.id,
                    model.time > horizon,
                    or_(model.curated_time.is_(None), model.curated_time > horizon),
                )
            )
        ).one()
        setattr(ahead, attr, int(count or 0))
        if until is not None and (ahead_until is None or until > ahead_until):
            ahead_until = until
    return DeviceDataSpan(
        first_record_at=min(firsts, default=None),
        last_record_at=max(lasts, default=None),
        first_seen_at=first_seen,
        first_log_at=first_log,
        first_data_at=min(candidates, default=None),
        earliest_project_from=project_from,
        earliest_project_assignment_id=project_assignment.id if project_assignment else None,
        earliest_entity_from=entity_from,
        earliest_entity_assignment_id=entity_assignment.id if entity_assignment else None,
        before_project=await _record_counts(session, device.id, project_from),
        before_entity=await _record_counts(session, device.id, entity_from),
        clock_ahead=ahead,
        clock_ahead_until=ahead_until,
    )


@router.post("/{device_id}/reattribute", response_model=ReattributeResult)
async def reattribute_device(
    device_id: uuid.UUID,
    body: ReattributeRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ReattributeResult:
    """Recompute the project and entity of the device's records over a window from its
    assignments as they stand (decision D103): the repair for records that were decoded before
    an assignment existed and so carry none, found on the dev server on 2026-09-09. Project
    admins of the device's current project, or a server admin."""
    device = await get_or_404(session, Device, device_id, "Device")
    attribution = await resolve_attribution(session, device.id, utc_now())
    if not user.is_superuser:
        if attribution.project_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Server admin access required")
        await _require_project_admin(session, user, attribution.project_id)
    now = utc_now()
    start = body.valid_from or await _first_data_at(session, device.id)
    if start is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The device has no data yet")
    end = body.valid_to or now
    if end <= start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    counts = await reattribute(session, device.id, start, end)
    await record_audit(
        session,
        user=user,
        action="device.reattributed",
        object_type="device",
        object_id=str(device.id),
        project_id=attribution.project_id,
        details={"from": start.isoformat(), "to": end.isoformat(), "reattributed": counts},
    )
    await session.commit()
    return ReattributeResult(valid_from=start, valid_to=end, reattributed=counts)


@router.post(
    "/{device_id}/project-assignments/{assignment_id}/extend-start",
    response_model=ProjectAssignmentExtended,
)
async def extend_project_assignment_start(
    device_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssignmentStart,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectAssignmentExtended:
    """Move the start of a project assignment back and attribute the records in between
    (decision D103): the repair for data that arrived before the device was assigned."""
    assignment = await get_or_404(session, DeviceProjectAssignment, assignment_id, "Assignment")
    if assignment.device_id != device_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await _require_project_admin(session, user, assignment.project_id)
    old_from, valid_to = range_bounds(assignment.validity)
    if body.valid_from >= old_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_from must be before the current start"
        )
    assignment.validity = Range(body.valid_from, valid_to, bounds="[)")
    await flush_or_409(session, "Project assignment")
    counts = await reattribute(session, device_id, body.valid_from, old_from)
    await record_audit(
        session,
        user=user,
        action="project_assignment.start_moved",
        object_type="device_project_assignment",
        object_id=str(assignment.id),
        project_id=assignment.project_id,
        details={
            "from": old_from.isoformat(),
            "to": body.valid_from.isoformat(),
            "reattributed": counts,
        },
    )
    await session.commit()
    read = project_assignment_read(assignment)
    return ProjectAssignmentExtended(**read.model_dump(), reattributed=counts)


@router.patch(
    "/{device_id}/project-assignments/{assignment_id}", response_model=ProjectAssignmentRead
)
async def end_project_assignment(
    device_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssignmentEnd,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectAssignmentRead:
    assignment = await get_or_404(session, DeviceProjectAssignment, assignment_id, "Assignment")
    if assignment.device_id != device_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await _require_project_admin(session, user, assignment.project_id)
    valid_from, _ = range_bounds(assignment.validity)
    if body.valid_to <= valid_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "valid_to must be after valid_from"
        )
    assignment.validity = Range(valid_from, body.valid_to, bounds="[)")
    await flush_or_409(session, "Project assignment")
    await record_audit(
        session,
        user=user,
        action="project_assignment.ended",
        object_type="device_project_assignment",
        object_id=str(assignment.id),
        project_id=assignment.project_id,
        details={"valid_to": body.valid_to.isoformat()},
    )
    await session.commit()
    return project_assignment_read(assignment)


@router.post(
    "/{device_id}/handover",
    response_model=ProjectAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def handover(
    device_id: uuid.UUID,
    body: HandoverRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectAssignmentRead:
    """Move the device to another project from `effective_at`: the current project assignment and
    entity assignment close at that moment, a new project assignment opens. History is untouched.
    Allowed for server admins and for admins of both the current and the target project."""
    device = await get_or_404(session, Device, device_id, "Device")
    await get_or_404(session, Project, body.project_id, "Project")
    current = await session.scalar(
        select(DeviceProjectAssignment).where(
            DeviceProjectAssignment.device_id == device.id,
            DeviceProjectAssignment.validity.op("@>")(body.effective_at),
        )
    )
    if current is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Device has no project assignment at effective_at; assign it instead",
        )
    if current.project_id == body.project_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Device is already in that project")
    await _require_project_admin(session, user, current.project_id)
    await _require_project_admin(session, user, body.project_id)
    current_from, _ = range_bounds(current.validity)
    if body.effective_at <= current_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "effective_at must be after the current assignment started",
        )
    # A later assignment that overlaps the new open range is caught by the exclusion constraint.
    current.validity = Range(current_from, body.effective_at, bounds="[)")
    entity_assignment = await session.scalar(
        select(DeviceEntityAssignment).where(
            DeviceEntityAssignment.device_id == device.id,
            DeviceEntityAssignment.validity.op("@>")(body.effective_at),
        )
    )
    if entity_assignment is not None:
        ea_from, _ = range_bounds(entity_assignment.validity)
        entity_assignment.validity = Range(ea_from, body.effective_at, bounds="[)")
    new = DeviceProjectAssignment(
        device_id=device.id,
        project_id=body.project_id,
        validity=Range(body.effective_at, None, bounds="[)"),
        reason=body.reason,
        created_by_user_id=user.id,
    )
    session.add(new)
    await flush_or_409(session, "Handover")
    # Records already decoded after the handover moment move with the device (D103).
    counts = await reattribute(session, device.id, body.effective_at, utc_now())
    await record_audit(
        session,
        user=user,
        action="device.handover",
        object_type="device",
        object_id=str(device.id),
        project_id=body.project_id,
        details={
            "from_project_id": str(current.project_id),
            "to_project_id": str(body.project_id),
            "effective_at": body.effective_at.isoformat(),
            "entity_assignment_closed": str(entity_assignment.id) if entity_assignment else None,
            "reattributed": counts,
        },
    )
    await session.commit()
    return project_assignment_read(new)


# External identities


@router.post(
    "/{device_id}/identities",
    response_model=ExternalIdentityRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_identity(
    device_id: uuid.UUID,
    body: ExternalIdentityCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> ExternalIdentity:
    device = await get_or_404(session, Device, device_id, "Device")
    await get_or_404(session, DataSource, body.data_source_id, "Data source")
    identity = ExternalIdentity(device_id=device.id, **body.model_dump())
    session.add(identity)
    await flush_or_409(session, "External identity")
    await fill_serial_from_identity(session, device, identity)  # D101
    await record_audit(
        session,
        user=user,
        action="external_identity.created",
        object_type="external_identity",
        object_id=str(identity.id),
        details={"device_id": str(device.id), "external_id": identity.external_id},
    )
    await session.commit()
    return identity


# Bulk import (architecture 28.7)

IMPORT_COLUMNS = (
    "device_name",
    "external_identifier",
    "device_type",
    "datasource",
    "project",
    "effective_from",
    "entity",
)


@router.post("/import", response_model=ImportResult)
async def import_devices(
    file: UploadFile,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> ImportResult:
    """CSV with columns device_name, external_identifier, device_type, datasource, project,
    effective_from (ISO 8601 with offset), entity (optional). All rows or none."""
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in IMPORT_COLUMNS[:-1] if c not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Missing columns: {', '.join(missing)}"
        )
    results: list[ImportRowResult] = []
    errors = 0
    for number, row in enumerate(reader, start=2):
        name = (row.get("device_name") or "").strip()
        try:
            device = await _import_row(session, user, row)
            results.append(
                ImportRowResult(row=number, device_name=name, status="created", device_id=device.id)
            )
        except HTTPException as exc:
            errors += 1
            results.append(
                ImportRowResult(
                    row=number, device_name=name, status="error", message=str(exc.detail)
                )
            )
    if errors:
        await session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "message": f"{errors} rows failed, nothing imported",
                "rows": [r.model_dump(mode="json") for r in results],
            },
        )
    await record_audit(
        session,
        user=user,
        action="devices.imported",
        object_type="device",
        details={"count": len(results)},
    )
    await session.commit()
    return ImportResult(created=len(results), rows=results)


async def _import_row(session: AsyncSession, user: User, row: dict[str, str | None]) -> Device:
    def need(column: str) -> str:
        value = (row.get(column) or "").strip()
        if not value:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{column} is required")
        return value

    device_type = await session.scalar(
        select(DeviceType).where(DeviceType.key == need("device_type"))
    )
    if device_type is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown device_type")
    data_source = await session.scalar(
        select(DataSource).where(DataSource.name == need("datasource"))
    )
    if data_source is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown datasource")
    project = await session.scalar(select(Project).where(Project.name == need("project")))
    if project is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown project")
    try:
        effective_from = require_aware(datetime.fromisoformat(need("effective_from")))
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"effective_from: {exc}"
        ) from None
    device = Device(
        name=need("device_name"), device_type_id=device_type.id, status=DeviceStatus.ACTIVE
    )
    session.add(device)
    await flush_or_409(session, "Device")
    session.add(
        ExternalIdentity(
            data_source_id=data_source.id,
            device_id=device.id,
            external_id=need("external_identifier"),
        )
    )
    session.add(
        DeviceProjectAssignment(
            device_id=device.id,
            project_id=project.id,
            validity=Range(effective_from, None, bounds="[)"),
            reason="bulk import",
            created_by_user_id=user.id,
        )
    )
    entity_name = (row.get("entity") or "").strip()
    if entity_name:
        entity = await session.scalar(
            select(Entity).where(Entity.project_id == project.id, Entity.name == entity_name)
        )
        if entity is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown entity {entity_name!r} in project"
            )
        session.add(
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=entity.id,
                validity=Range(effective_from, None, bounds="[)"),
                reason="bulk import",
                created_by_user_id=user.id,
            )
        )
    await flush_or_409(session, "Import row")
    return device


# --- Connectivity per data source (architecture 20, decision D161) ---------------------------

MAX_CONNECTIVITY_HOURS = 24 * 90
# A source that carried nothing for this long is silent; a device's cadence is not known here.
SILENT_AFTER = timedelta(hours=24)
# Frame counters are read from this many uplinks at most, newest first (a collar sends about a
# hundred a day at the most).
MAX_COUNTER_ROWS = 20000


class LoRaWANLink(BaseModel):
    uplinks: int = Field(description="Uplinks with a reception in the period")
    receptions: int
    gateway_count: int
    best_gateway_id: uuid.UUID | None = None
    best_gateway_name: str | None = None
    best_gateway_share: float | None = None
    mean_rssi: float | None = None
    mean_snr: float | None = None
    missed_frames: int = Field(
        default=0, description="Gaps in the uplink frame counter over the period"
    )
    frames_seen: int = Field(default=0, description="Uplinks with a frame counter in the period")
    gateways: list[dict[str, Any]] = Field(default_factory=list)


class IridiumLink(BaseModel):
    last_session: dict[str, Any] | None = Field(
        default=None, description="The last satellite session as the ingest normalised it"
    )
    sessions: int = Field(description="Sessions in the period, redeliveries left out")
    bytes: int = Field(description="Bytes carried in the period")
    missed: int = Field(description="Sessions the counter skipped in the period")
    duplicates: int = Field(description="Redeliveries in the period")


class SourceConnectivity(BaseModel):
    data_source_id: uuid.UUID
    data_source_name: str
    adapter_key: str
    channel: str = Field(description="lorawan, iridium, webble, log_file, api or cellular")
    status: str = Field(description="online, silent or unknown")
    last_contact_at: datetime | None = None
    last_uplink_at: datetime | None = None
    last_join_at: datetime | None = None
    last_downlink_at: datetime | None = None
    last_rssi: float | None = None
    last_snr: float | None = None
    lorawan: LoRaWANLink | None = None
    iridium: IridiumLink | None = None


class DeviceConnectivityRead(BaseModel):
    device_id: uuid.UUID
    hours: int
    sources: list[SourceConnectivity]


@router.get("/{device_id}/connectivity", response_model=DeviceConnectivityRead)
async def device_connectivity(
    device_id: uuid.UUID,
    hours: int = Query(168, ge=1, le=MAX_CONNECTIVITY_HOURS),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceConnectivityRead:
    """How every network the device is reachable through performs (architecture 20, decision
    D161): per data source the connection state and the last contacts, then for a LoRaWAN
    source the gateways heard in the period with the best one and its share, the signal and
    the frame counter gaps, and for an Iridium source the last session, the sessions, bytes,
    missed sessions and redeliveries of the period. Apart from the device's own health."""
    device = await _visible_device(session, user, device_id)
    until = utc_now()
    since = until - timedelta(hours=hours)
    identities = (
        await session.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.device_id == device.id, ExternalIdentity.ignored.is_(False)
            )
        )
    ).all()
    source_ids = {i.data_source_id for i in identities}
    states = {
        c.data_source_id: c
        for c in (
            await session.scalars(
                select(ConnectivityState).where(ConnectivityState.device_id == device.id)
            )
        ).all()
    }
    source_ids |= set(states)
    if not source_ids:
        return DeviceConnectivityRead(device_id=device.id, hours=hours, sources=[])
    sources = {
        s.id: s
        for s in (
            await session.scalars(select(DataSource).where(DataSource.id.in_(source_ids)))
        ).all()
    }
    result: list[SourceConnectivity] = []
    for source_id in sorted(source_ids, key=lambda i: sources[i].name if i in sources else ""):
        source = sources.get(source_id)
        if source is None:
            continue
        adapter = ADAPTERS.get(source.adapter_key)
        channel = str(
            getattr(getattr(adapter, "acquisition_channel", None), "value", None)
            or getattr(adapter, "acquisition_channel", None)
            or "api"
        )
        state = states.get(source_id)
        contacts = [
            t
            for t in (
                state.last_uplink_at if state else None,
                state.last_join_at if state else None,
                state.last_downlink_at if state else None,
            )
            if t is not None
        ]
        last_contact = max(contacts) if contacts else None
        status = (
            "unknown"
            if last_contact is None
            else ("online" if until - last_contact <= SILENT_AFTER else "silent")
        )
        block = SourceConnectivity(
            data_source_id=source.id,
            data_source_name=source.name,
            adapter_key=source.adapter_key,
            channel=channel,
            status=status,
            last_contact_at=last_contact,
            last_uplink_at=state.last_uplink_at if state else None,
            last_join_at=state.last_join_at if state else None,
            last_downlink_at=state.last_downlink_at if state else None,
            last_rssi=state.last_rssi if state else None,
            last_snr=state.last_snr if state else None,
        )
        if channel == "lorawan":
            block.lorawan = await _lorawan_link(session, device.id, source.id, since, until)
        elif channel == "iridium":
            block.iridium = await _iridium_link(session, device.id, source.id, state, since, until)
        result.append(block)
    return DeviceConnectivityRead(device_id=device.id, hours=hours, sources=result)


async def _lorawan_link(
    session: AsyncSession,
    device_id: uuid.UUID,
    source_id: uuid.UUID,
    since: datetime,
    until: datetime,
) -> LoRaWANLink:
    rows = (
        await session.execute(
            select(
                GatewayReception.gateway_id,
                func.count().label("receptions"),
                func.count(func.distinct(GatewayReception.source_event_id)).label("uplinks"),
                func.avg(GatewayReception.rssi).label("mean_rssi"),
                func.avg(GatewayReception.snr).label("mean_snr"),
            )
            .where(
                GatewayReception.device_id == device_id,
                GatewayReception.data_source_id == source_id,
                GatewayReception.time >= since,
                GatewayReception.time < until,
            )
            .group_by(GatewayReception.gateway_id)
            .order_by(func.count().desc())
        )
    ).all()
    uplinks = int(
        await session.scalar(
            select(func.count(func.distinct(GatewayReception.source_event_id))).where(
                GatewayReception.device_id == device_id,
                GatewayReception.data_source_id == source_id,
                GatewayReception.time >= since,
                GatewayReception.time < until,
            )
        )
        or 0
    )
    registry = {
        g.external_id: g
        for g in (
            await session.scalars(
                select(Gateway).where(
                    Gateway.data_source_id == source_id,
                    Gateway.external_id.in_({r.gateway_id for r in rows} or {""}),
                )
            )
        ).all()
    }
    counters = [
        int(c)
        for (c,) in (
            await session.execute(
                select(SourceEvent.provider_metadata["f_cnt"].as_integer())
                .where(
                    SourceEvent.device_id == device_id,
                    SourceEvent.data_source_id == source_id,
                    SourceEvent.event_type == "uplink",
                    SourceEvent.ingested_at >= since,
                    SourceEvent.ingested_at < until,
                    SourceEvent.provider_metadata["f_cnt"].as_integer().is_not(None),
                )
                .order_by(SourceEvent.ingested_at)
                .limit(MAX_COUNTER_ROWS)
            )
        ).all()
    ]
    missed = 0
    for previous, current in pairwise(counters):
        if current > previous + 1:
            missed += current - previous - 1  # a reset (a smaller counter) is not a gap
    total_receptions = sum(int(r.receptions) for r in rows)
    rssi = [float(r.mean_rssi) * int(r.receptions) for r in rows if r.mean_rssi is not None]
    snr = [float(r.mean_snr) * int(r.receptions) for r in rows if r.mean_snr is not None]
    best = rows[0] if rows else None
    best_gateway = registry.get(best.gateway_id) if best else None
    return LoRaWANLink(
        uplinks=uplinks,
        receptions=total_receptions,
        gateway_count=len(rows),
        best_gateway_id=best_gateway.id if best_gateway else None,
        best_gateway_name=(
            (best_gateway.name_override or best_gateway.name or best_gateway.external_id)
            if best_gateway
            else (best.gateway_id if best else None)
        ),
        best_gateway_share=(
            round(min(1.0, int(best.uplinks) / uplinks), 3) if best and uplinks else None
        ),
        mean_rssi=round(sum(rssi) / total_receptions, 1) if rssi else None,
        mean_snr=round(sum(snr) / total_receptions, 1) if snr else None,
        missed_frames=missed,
        frames_seen=len(counters),
        gateways=[
            {
                "gateway_id": str(g.id) if (g := registry.get(r.gateway_id)) else None,
                "external_id": r.gateway_id,
                "name": (g.name_override or g.name) if g else None,
                "receptions": int(r.receptions),
                "uplinks": int(r.uplinks),
                "mean_rssi": round(float(r.mean_rssi), 1) if r.mean_rssi is not None else None,
                "mean_snr": round(float(r.mean_snr), 1) if r.mean_snr is not None else None,
            }
            for r in rows
        ],
    )


async def _iridium_link(
    session: AsyncSession,
    device_id: uuid.UUID,
    source_id: uuid.UUID,
    state: ConnectivityState | None,
    since: datetime,
    until: datetime,
) -> IridiumLink:
    info = SourceEvent.provider_metadata["satellite_session"]
    rows = (
        await session.execute(
            select(SourceEvent.processing_status, info)
            .where(
                SourceEvent.device_id == device_id,
                SourceEvent.data_source_id == source_id,
                SourceEvent.acquisition_channel == AcquisitionChannel.IRIDIUM,
                SourceEvent.ingested_at >= since,
                SourceEvent.ingested_at < until,
            )
            .limit(MAX_COUNTER_ROWS)
        )
    ).all()
    sessions = bytes_total = missed = duplicates = 0
    for _processing_status, data in rows:
        # a redelivery is the ingest's `duplicate_of` mark (decision D160); the decoder's own
        # `duplicate` status means the records were known already, which a repeated flash
        # buffer over another path does as well, and that session still happened
        if isinstance(data, dict) and data.get("duplicate_of") is not None:
            duplicates += 1
            continue
        parsed = SatelliteSession.from_dict(data)
        if parsed is None:
            continue
        sessions += 1
        bytes_total += parsed.bytes
        gap = data.get("missed_since_last") if isinstance(data, dict) else None
        if isinstance(gap, int):
            missed += gap
    last = (state.attributes or {}).get("satellite") if state else None
    return IridiumLink(
        last_session=dict(last) if isinstance(last, dict) else None,
        sessions=sessions,
        bytes=bytes_total,
        missed=missed,
        duplicates=duplicates,
    )
