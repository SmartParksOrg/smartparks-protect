"""Attribution jobs (decision D206).

An assignment change (a start moved back, a device assigned to a project or an entity, a
handover, "Recompute attribution") no longer rewrites the device's earlier records inside the
request: the request writes the assignment, queues one job row and returns, and the export
service runs the rewrite in windows of `WINDOW_DAYS`, one transaction each, with the records
done so far on the row. The pages poll the device's jobs and draw the progress. A change made
while the device's job is still queued folds into it (the job reads the assignments when it
runs; its window widens if needed), so the assign dialog's two steps and a quick correction
need no second job; a change while the job is running is refused with `AttributionBusy` (409
at the API), so two rewrites never race over the same rows.

The rewrite itself is `shared.domain.assignments.rewrite_attribution`; the current state of the
device and the entities involved is recomputed once at the end.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.curation.apply import recompute_current_state
from shared.curation.effective import effective_time
from shared.database import session_scope
from shared.domain.assignments import rewrite_attribution
from shared.enums import AttributionJobStatus, ErrorCode, TraceClass, TraceStatus
from shared.logger import get_logger
from shared.models import AttributionJob, Measurement, Position
from shared.timeutil import require_aware, utc_now
from shared.trace import Tracer

log = get_logger("attribution")

# One transaction rewrites this many days of a device's records; a device reporting every ten
# minutes has about 20,000 rows in it, a few seconds on compressed chunks.
WINDOW_DAYS = 30
ACTIVE = (AttributionJobStatus.QUEUED, AttributionJobStatus.RUNNING)


class AttributionBusy(Exception):
    """A job is running for the device; assignment changes wait for it."""

    def __init__(self, job: AttributionJob) -> None:
        super().__init__(
            "The records of this device are being given their project and entity; "
            "wait until that has finished"
        )
        self.job = job


@dataclass(frozen=True, slots=True)
class QueueResult:
    """What `queue_reattribution` did: the job the change rides on (None when nothing needs a
    rewrite) and whether it is new, in which case the caller publishes it after the commit."""

    job: AttributionJob | None
    created: bool


async def active_job(
    session: AsyncSession, device_id: uuid.UUID, *, for_update: bool = False
) -> AttributionJob | None:
    statement = (
        select(AttributionJob)
        .where(AttributionJob.device_id == device_id, AttributionJob.status.in_(ACTIVE))
        .order_by(AttributionJob.created_at.desc())
        .limit(1)
    )
    if for_update:
        # serialised against the worker's start, which locks the row while it reads the window
        statement = statement.with_for_update()
    job: AttributionJob | None = await session.scalar(statement)
    return job


async def ensure_not_attributing(session: AsyncSession, device_id: uuid.UUID) -> None:
    """Refuse while a job runs; a queued one reads the assignments when it starts."""
    job = await active_job(session, device_id)
    if job is not None and job.status == AttributionJobStatus.RUNNING:
        raise AttributionBusy(job)


async def recent_jobs(
    session: AsyncSession, device_id: uuid.UUID, *, limit: int = 5
) -> list[AttributionJob]:
    """The device's newest jobs, newest first (a bounded read for the pages' poll)."""
    rows = await session.scalars(
        select(AttributionJob)
        .where(AttributionJob.device_id == device_id)
        .order_by(AttributionJob.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def count_records(
    session: AsyncSession, device_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model, name in ((Position, "positions"), (Measurement, "measurements")):
        when = effective_time(model)
        counts[name] = int(
            await session.scalar(
                select(func.count()).where(model.device_id == device_id, when >= start, when < end)
            )
            or 0
        )
    return counts


async def queue_reattribution(
    session: AsyncSession,
    *,
    device_id: uuid.UUID,
    start: datetime,
    end: datetime,
    reason: str,
    user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> QueueResult:
    """Queue the rewrite of the device's records in `[start, end)`. A job still queued for the
    device takes the change along (its window widened to cover this one); a running one raises
    `AttributionBusy`; otherwise a new row, or none when the window holds no record (nothing
    to rewrite, so the current state cannot change either). The caller commits and then calls
    `publish_job` for a created job, so the worker never reads an uncommitted row."""
    require_aware(start)
    require_aware(end)
    active = await active_job(session, device_id, for_update=True)
    if active is not None:
        if active.status == AttributionJobStatus.RUNNING:
            raise AttributionBusy(active)
        if end > start:
            active.time_from = min(active.time_from, start)
            active.time_to = max(active.time_to, end)
            widened = await count_records(session, device_id, active.time_from, active.time_to)
            active.records_total = sum(widened.values())
            await session.flush()
        return QueueResult(active, created=False)
    if end <= start:
        return QueueResult(None, created=False)
    counts = await count_records(session, device_id, start, end)
    total = sum(counts.values())
    if total == 0:
        return QueueResult(None, created=False)
    job = AttributionJob(
        device_id=device_id,
        project_id=project_id,
        requested_by_user_id=user_id,
        reason=reason,
        time_from=start,
        time_to=end,
        records_total=total,
    )
    session.add(job)
    await session.flush()
    return QueueResult(job, created=True)


def job_message(job: AttributionJob) -> tuple[str, dict[str, Any]]:
    return Topic.ATTRIBUTION_REQUESTED, {"job_id": str(job.id)}


async def publish_job(bus: RedisStreamsBus, job: AttributionJob) -> None:
    """After the commit: the export service picks the job up."""
    topic, payload = job_message(job)
    await bus.publish(topic, payload)


def windows(
    start: datetime, end: datetime, days: int = WINDOW_DAYS
) -> list[tuple[datetime, datetime]]:
    """`[start, end)` cut into consecutive windows of at most `days`, the last one shorter."""
    out: list[tuple[datetime, datetime]] = []
    step = timedelta(days=days)
    cursor = start
    while cursor < end:
        upper = min(cursor + step, end)
        out.append((cursor, upper))
        cursor = upper
    return out


async def run_attribution_job(payload: dict[str, Any]) -> None:
    """The handler of `attribution.requested`: rewrite the job's window per `WINDOW_DAYS`, the
    records done on the row after every window, the current state recomputed once at the end.
    A redelivery after a crash starts the job over (the row still says running); the rewrite is
    idempotent. The topic's loop runs one job at a time, so a job is never handled twice at once."""
    job_id = uuid.UUID(str(payload["job_id"]))
    async with session_scope() as session:
        # the lock keeps a change that folds into this job from committing a wider window after
        # the window was read here (see queue_reattribution)
        job = await session.get(AttributionJob, job_id, with_for_update=True)
        if job is None:
            log.warning("attribution job not found", job_id=str(job_id))
            return
        if job.status == AttributionJobStatus.COMPLETE:
            return  # a redelivery after the acknowledgement was lost
        if job.status == AttributionJobStatus.RUNNING:
            log.warning("attribution job restarted after an interrupted run", job_id=str(job_id))
        tracer = Tracer(
            session,
            root_object_type="attribution_job",
            root_object_id=str(job.id),
            trace_class=TraceClass.ROUTINE,
            project_id=job.project_id,
            device_id=job.device_id,
        )
        await tracer.start()
        job.trace_id = tracer.trace_id
        job.status = AttributionJobStatus.RUNNING
        job.started_at = utc_now()
        job.records_done = 0
        job.counts = {}
        job.error_code = None
        job.error_message = None
        device_id, start, end = job.device_id, job.time_from, job.time_to
        await session.commit()
        trace_id = tracer.trace_id

    done = 0
    counts: dict[str, int] = {"positions": 0, "measurements": 0}
    entity_ids: set[uuid.UUID | None] = {None}
    try:
        for lower, upper in windows(start, end):
            async with session_scope() as session:
                part, ids = await rewrite_attribution(session, device_id, lower, upper)
                entity_ids |= ids
                for key, value in part.items():
                    counts[key] = counts.get(key, 0) + value
                done += sum(part.values())
                job = await session.get(AttributionJob, job_id)
                assert job is not None
                job.records_done = done
                job.counts = dict(counts)
                await session.commit()
        async with session_scope() as session:
            await recompute_current_state(session, device_id, entity_ids)
            job = await session.get(AttributionJob, job_id)
            assert job is not None
            job.status = AttributionJobStatus.COMPLETE
            job.finished_at = utc_now()
            job.records_done = done
            job.counts = dict(counts)
            tracer = await Tracer.resume(session, trace_id)
            async with tracer.step("attribution", "records rewritten") as step:
                step.metadata.update(counts)
            await tracer.finish()
            await session.commit()
    except Exception as exc:
        async with session_scope() as session:
            job = await session.get(AttributionJob, job_id)
            assert job is not None
            job.status = AttributionJobStatus.FAILED
            job.error_code = ErrorCode.INTERNAL_ERROR
            job.error_message = f"{type(exc).__name__}: {exc}"[:1000]
            job.finished_at = utc_now()
            job.records_done = done
            tracer = await Tracer.resume(session, trace_id)
            async with tracer.step("attribution", "job failed") as step:
                step.metadata.update(error=str(exc))
            await tracer.finish(TraceStatus.FAILED)
            await session.commit()
        log.error("attribution job failed", job_id=str(job_id), exc_info=True)
        raise
    log.info("attribution job done", job_id=str(job_id), counts=counts)
