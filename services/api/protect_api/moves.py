"""The API's side of a move between projects (decisions D292 and D293): the plan read back
as the preview or the result, the permission rule and the audit."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.deps import is_project_admin
from protect_api.schemas.domain import (
    MoveDeviceRead,
    MoveEntityRead,
    MoveResult,
    MoveSpanRead,
)
from shared.domain.moves import DeviceOutcome, MovePlan, project_names
from shared.i18n import translate
from shared.models import User


async def require_admin_of_every_project(session: AsyncSession, user: User, plan: MovePlan) -> None:
    """A move is allowed for server admins and for admins of every project involved: the
    target and each project a device or an entity leaves."""
    if user.is_superuser:
        return
    involved = {plan.project_id}
    involved |= {d.project_id for d in plan.devices if d.project_id and not d.skipped}
    involved |= {e.project_id for e in plan.entities.values() if e.moves}
    for project_id in involved:
        if not await is_project_admin(session, user, project_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Project admin access to every project involved required"
            )


async def move_result(
    session: AsyncSession, plan: MovePlan, *, preview: bool, language: str = "en"
) -> MoveResult:
    names = await project_names(
        session,
        {plan.project_id}
        | {d.project_id for d in plan.devices}
        | {e.project_id for e in plan.entities.values()},
    )

    def entity_read(entity_id: uuid.UUID) -> MoveEntityRead:
        e = plan.entities[entity_id]
        return MoveEntityRead(
            entity_id=e.entity_id,
            name=e.name,
            project_id=e.project_id,
            project_name=names.get(e.project_id),
            moves=e.moves,
            reason=translate(e.reason, language),
        )

    def device_read(d: DeviceOutcome) -> MoveDeviceRead:
        return MoveDeviceRead(
            device_id=d.device_id,
            name=d.name,
            project_id=d.project_id,
            project_name=names.get(d.project_id) if d.project_id else None,
            spans=[MoveSpanRead(start=s.start, end=s.end) for s in d.spans],
            entities_along=[entity_read(e) for e in d.entities_along],
            entities_staying=[entity_read(e) for e in d.entities_staying],
            skipped=translate(d.skipped, language),
            attribution_job_id=d.attribution_job_id,
        )

    return MoveResult(
        project_id=plan.project_id,
        project_name=names.get(plan.project_id, ""),
        preview=preview,
        devices=[device_read(d) for d in plan.devices],
        entities=[entity_read(e) for e in plan.entities],
        moved_devices=sum(1 for d in plan.devices if not d.skipped and d.spans),
        moved_entities=sum(
            1 for e in plan.entities.values() if e.moves and e.project_id != plan.project_id
        ),
        attribution_jobs=sum(1 for d in plan.devices if d.attribution_job_id is not None),
    )


async def audit_plan(session: AsyncSession, user: User, plan: MovePlan, start: str) -> None:
    for d in plan.devices:
        if d.skipped or not d.spans:
            continue
        await record_audit(
            session,
            user=user,
            action="device.moved",
            object_type="device",
            object_id=str(d.device_id),
            project_id=plan.project_id,
            details={
                "from_project_id": str(d.project_id) if d.project_id else None,
                "to_project_id": str(plan.project_id),
                "start": start,
                "spans": [
                    [s.start.isoformat(), s.end.isoformat() if s.end else None] for s in d.spans
                ],
                "entities_along": [str(e) for e in d.entities_along],
                "entities_staying": [str(e) for e in d.entities_staying],
                "attribution_job_id": str(d.attribution_job_id) if d.attribution_job_id else None,
            },
        )
    for e in plan.entities.values():
        if not e.moves or e.project_id == plan.project_id:
            continue
        await record_audit(
            session,
            user=user,
            action="entity.moved_project",
            object_type="entity",
            object_id=str(e.entity_id),
            project_id=plan.project_id,
            details={"from_project_id": str(e.project_id), "to_project_id": str(plan.project_id)},
        )
