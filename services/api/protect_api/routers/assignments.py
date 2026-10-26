"""A device's assignment timeline and its boundaries moved after the fact (decisions D355
to D358). The existing endpoints that create, extend and end assignments stand; these move
a boundary together with the neighbouring row and correct a project and an entity boundary
in one call."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.auth.users import current_active_user
from protect_api.boundaries import last_message_before, read_timeline, run_plan
from protect_api.bus import get_bus
from protect_api.crud import get_or_404
from protect_api.deps import language
from protect_api.routers.devices import _visible_device
from protect_api.schemas.domain import (
    BoundaryCorrection,
    BoundaryEdit,
    BoundaryResult,
    DeviceAssignmentsRead,
    LastMessageRead,
)
from shared.bus import RedisStreamsBus
from shared.database import get_session
from shared.domain.boundaries import Kind, plan_boundary, plan_correction
from shared.models import DeviceEntityAssignment, DeviceProjectAssignment, User
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("/{device_id}/assignments", response_model=DeviceAssignmentsRead)
async def device_assignments(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceAssignmentsRead:
    """The device's project and entity assignments in time order, within the caller's
    projects, each with the newest attribution job touching it and the last change recorded
    on it, and whether the caller may move boundaries."""
    device = await _visible_device(session, user, device_id)
    return await read_timeline(session, user, device)


@router.get("/{device_id}/last-message", response_model=LastMessageRead)
async def device_last_message(
    device_id: uuid.UUID,
    before: datetime = Query(description="The instant to look back from"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> LastMessageRead:
    """The device's newest live message before an instant and the instant one second after
    it: what "snap to the last uplink" offers in the boundary dialog."""
    device = await _visible_device(session, user, device_id)
    return await last_message_before(session, device, require_aware(before))


@router.patch(
    "/{device_id}/project-assignments/{assignment_id}/boundary", response_model=BoundaryResult
)
async def move_project_boundary(
    device_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: BoundaryEdit,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
    lang: str = Depends(language),
) -> BoundaryResult:
    """Move the start, the end or both edges of a project assignment, each together with the
    neighbouring row's touching edge (decision D355). Server admins and project admins of every
    project whose row changes. `preview` answers what would change without writing."""
    device = await _visible_device(session, user, device_id)
    assignment = await get_or_404(session, DeviceProjectAssignment, assignment_id, "Assignment")
    if assignment.device_id != device.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    plan = await plan_boundary(
        session,
        "project",
        device.id,
        assignment.id,
        new_from=body.valid_from,
        new_to=body.valid_to,
        now=utc_now(),
    )
    return await run_plan(
        session,
        bus,
        user=user,
        device=device,
        plan=plan,
        reason=body.reason,
        preview=body.preview,
        language=lang,
        named=[("project", assignment.project_id)],
    )


@router.patch(
    "/{device_id}/entity-assignments/{assignment_id}/boundary", response_model=BoundaryResult
)
async def move_entity_boundary(
    device_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: BoundaryEdit,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
    lang: str = Depends(language),
) -> BoundaryResult:
    """The same for an entity assignment: `devices:write` in the project of every entity whose
    row changes; the rows must stay inside the device's project assignments."""
    device = await _visible_device(session, user, device_id)
    assignment = await get_or_404(session, DeviceEntityAssignment, assignment_id, "Assignment")
    if assignment.device_id != device.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    plan = await plan_boundary(
        session,
        "entity",
        device.id,
        assignment.id,
        new_from=body.valid_from,
        new_to=body.valid_to,
        now=utc_now(),
    )
    return await run_plan(
        session,
        bus,
        user=user,
        device=device,
        plan=plan,
        reason=body.reason,
        preview=body.preview,
        language=lang,
        named=[("entity", assignment.entity_id)],
    )


@router.post("/{device_id}/assignments/correct", response_model=BoundaryResult)
async def correct_boundaries(
    device_id: uuid.UUID,
    body: BoundaryCorrection,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
    lang: str = Depends(language),
) -> BoundaryResult:
    """A project boundary and an entity boundary moved to one instant in one call (the
    chained correction of decision D355): a transfer made "from now" corrected to the moment
    the device really changed hands. Each row's edge nearest the instant moves unless named;
    the neighbours follow; one attribution job covers both windows."""
    device = await _visible_device(session, user, device_id)
    named: list[tuple[Kind, uuid.UUID]] = []
    if body.project_assignment_id is not None:
        row = await get_or_404(
            session, DeviceProjectAssignment, body.project_assignment_id, "Assignment"
        )
        if row.device_id != device.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
        named.append(("project", row.project_id))
    if body.entity_assignment_id is not None:
        entity_row = await get_or_404(
            session, DeviceEntityAssignment, body.entity_assignment_id, "Assignment"
        )
        if entity_row.device_id != device.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
        named.append(("entity", entity_row.entity_id))
    plan = await plan_correction(
        session,
        device.id,
        project_assignment_id=body.project_assignment_id,
        entity_assignment_id=body.entity_assignment_id,
        instant=body.instant,
        now=utc_now(),
        project_edge=body.project_edge,
        entity_edge=body.entity_edge,
    )
    return await run_plan(
        session,
        bus,
        user=user,
        device=device,
        plan=plan,
        reason=body.reason,
        preview=body.preview,
        language=lang,
        named=named,
    )
