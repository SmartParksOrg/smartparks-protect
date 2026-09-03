"""Devices are server-level objects. Project membership is a time-bounded assignment; moving a
device is a handover that closes one assignment and opens the next (architecture 28)."""

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.crud import apply_patch, flush_or_409, get_or_404, range_bounds
from protect_api.deps import accessible_project_ids, require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.routers.entities import assignment_read
from protect_api.schemas.domain import (
    AssignmentEnd,
    DeviceCreate,
    DeviceRead,
    DeviceUpdate,
    DeviceWithAssignments,
    ExternalIdentityCreate,
    ExternalIdentityRead,
    HandoverRequest,
    ImportResult,
    ImportRowResult,
    ProjectAssignmentCreate,
    ProjectAssignmentRead,
)
from shared.database import get_session
from shared.domain.links import resolve_links
from shared.enums import DeviceStatus, Role
from shared.models import (
    DataSource,
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    ExternalIdentity,
    Project,
    ProjectMembership,
    User,
)
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/devices", tags=["devices"])


def project_assignment_read(assignment: DeviceProjectAssignment) -> ProjectAssignmentRead:
    valid_from, valid_to = range_bounds(assignment.validity)
    return ProjectAssignmentRead(
        id=assignment.id,
        device_id=assignment.device_id,
        project_id=assignment.project_id,
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


@router.get("", response_model=PageResponse[DeviceRead])
async def list_devices(
    page: Page = Depends(page),
    project_id: uuid.UUID | None = None,
    status_filter: DeviceStatus | None = None,
    q: str | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[DeviceRead]:
    """Server admins see every device. Others see devices currently assigned to their projects.
    `project_id` narrows to devices currently assigned to that project."""
    statement = select(Device)
    now = utc_now()
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
    if q:
        pattern = f"%{q}%"
        statement = statement.where(
            or_(Device.name.ilike(pattern), Device.serial_number.ilike(pattern))
        )
    rows, next_cursor = await paginate(session, Device.id, statement, page)
    return PageResponse(items=[DeviceRead.model_validate(r) for r in rows], next_cursor=next_cursor)


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
        **DeviceRead.model_validate(device).model_dump(),
        project_assignments=[project_assignment_read(a) for a in project_assignments],
        entity_assignments=[assignment_read(a) for a in entity_assignments],
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
    await record_audit(
        session,
        user=user,
        action="project_assignment.created",
        object_type="device_project_assignment",
        object_id=str(assignment.id),
        project_id=body.project_id,
        details={"device_id": str(device.id), "valid_from": body.valid_from.isoformat()},
    )
    await session.commit()
    return project_assignment_read(assignment)


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
