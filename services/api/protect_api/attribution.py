"""The API's side of the attribution jobs (decision D206): an assignment change queues one, or
folds into the device's queued job, and never waits for a running one (decision D291)."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.schemas.domain import AttributionJobRead
from shared.domain.attribution import QueueResult, queue_reattribution
from shared.models import AttributionJob, User


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
    """Queue the rewrite of the records in the window, fold it into the device's queued job, or
    queue a follow-up to its running one. The endpoint commits and then publishes a created
    job with `shared.domain.attribution.publish_job`."""
    return await queue_reattribution(
        session,
        device_id=device_id,
        start=start,
        end=end,
        reason=reason,
        user_id=user.id,
        project_id=project_id,
    )


def job_read(job: AttributionJob | None) -> AttributionJobRead | None:
    return AttributionJobRead.model_validate(job) if job is not None else None
