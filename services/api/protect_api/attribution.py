"""The API's side of the attribution jobs (decision D206): an assignment change queues one and
answers 409 while one is queued or running for the device."""

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.schemas.domain import AttributionJobRead
from shared.domain.attribution import (
    AttributionBusy,
    QueueResult,
    ensure_not_attributing,
    queue_reattribution,
)
from shared.models import AttributionJob, User


async def hold_while_attributing(session: AsyncSession, device_id: uuid.UUID) -> None:
    """Before an assignment of the device changes without queueing a rewrite of its own: 409
    while a job runs (a queued one reads the assignments when it starts)."""
    try:
        await ensure_not_attributing(session, device_id)
    except AttributionBusy as busy:
        raise HTTPException(status.HTTP_409_CONFLICT, str(busy)) from busy


async def queue_job(
    session: AsyncSession,
    *,
    device_id: uuid.UUID,
    start: datetime,
    end: datetime,
    reason: str,
    user: User,
    project_id: uuid.UUID | None,
) -> QueueResult:
    """Queue the rewrite of the records in the window, or fold it into the device's queued job;
    409 while one runs. The endpoint commits and then publishes a created job with
    `shared.domain.attribution.publish_job`."""
    try:
        return await queue_reattribution(
            session,
            device_id=device_id,
            start=start,
            end=end,
            reason=reason,
            user_id=user.id,
            project_id=project_id,
        )
    except AttributionBusy as busy:
        raise HTTPException(status.HTTP_409_CONFLICT, str(busy)) from busy


def job_read(job: AttributionJob | None) -> AttributionJobRead | None:
    return AttributionJobRead.model_validate(job) if job is not None else None
