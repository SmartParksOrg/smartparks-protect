"""Data curation (architecture 28, decisions D80 to D83): corrections on single records,
bulk jobs with preview and impact, the optional approval step, reverts, and the record
history behind a curated value. Everything is audited; raw source events are never touched."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import get_or_404
from protect_api.deps import ProjectContext, get_project_context, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.curation import (
    CorrectionCreate,
    CorrectionRead,
    CorrectionRevert,
    CurationSummary,
    JobCreate,
    JobRead,
    RecordHistory,
)
from shared.bus import RedisStreamsBus, Topic
from shared.curation.apply import (
    CURATABLE,
    apply_correction,
    effective_of,
    load_record,
    normalize_value,
    original_of,
    recompute_current_state,
    revert_correction,
)
from shared.curation.jobs import Transformation, preview, validate_job
from shared.database import get_session
from shared.enums import (
    CorrectionStatus,
    CurationJobStatus,
    CurationReason,
    CurationTarget,
)
from shared.models import CurationJob, DataCorrection, IntegrationDelivery
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now
from shared.trace import ApplicationError

router = APIRouter(prefix="/projects/{project_id}/curation", tags=["curation"])

APPROVAL_SETTING = "curation_requires_approval"


def _need(context: ProjectContext, permission: Permission) -> None:
    if permission not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {permission} required")


def _requires_approval(context: ProjectContext) -> bool:
    return bool((context.project.settings or {}).get(APPROVAL_SETTING, False))


def _reason(code: str) -> str:
    try:
        return CurationReason(code).value
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown reason {code!r}; one of {', '.join(r.value for r in CurationReason)}",
        ) from None


async def _publish_job(
    bus: RedisStreamsBus,
    job: CurationJob,
    action: str,
    user_id: uuid.UUID,
    comment: str | None = None,
) -> None:
    await bus.publish(
        Topic.CURATION_JOB_REQUESTED,
        {
            "job_id": str(job.id),
            "project_id": str(job.project_id),
            "action": action,
            "user_id": str(user_id),
            "comment": comment,
        },
    )


@router.get("/summary", response_model=CurationSummary)
async def summary(
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> CurationSummary:
    counts: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(DataCorrection.status, func.count())
                .where(DataCorrection.project_id == context.project.id)
                .group_by(DataCorrection.status)
            )
        ).all()
    }
    jobs: dict[str, int] = {
        str(row[0]): int(row[1])
        for row in (
            await session.execute(
                select(CurationJob.status, func.count())
                .where(CurationJob.project_id == context.project.id)
                .group_by(CurationJob.status)
            )
        ).all()
    }
    stale = int(
        await session.scalar(
            select(func.count())
            .select_from(IntegrationDelivery)
            .where(
                IntegrationDelivery.project_id == context.project.id,
                IntegrationDelivery.stale_at.is_not(None),
            )
        )
        or 0
    )
    return CurationSummary(
        requires_approval=_requires_approval(context),
        pending_corrections=int(counts.get(CorrectionStatus.PENDING, 0)),
        active_corrections=int(counts.get(CorrectionStatus.ACTIVE, 0)),
        reverted_corrections=int(counts.get(CorrectionStatus.REVERTED, 0))
        + int(counts.get(CorrectionStatus.SUPERSEDED, 0)),
        jobs=jobs,
        stale_deliveries=stale,
        reasons=[r.value for r in CurationReason],
        curatable={t.value: sorted(f.value for f in fields) for t, fields in CURATABLE.items()},
        transformations=["time_offset", "set_valid", "value_offset", "value_scale"],
    )


# Corrections on single records


@router.get("/corrections", response_model=PageResponse[CorrectionRead])
async def list_corrections(
    correction_status: str | None = Query(None, alias="status"),
    target_type: str | None = Query(None),
    device_id: uuid.UUID | None = Query(None),
    job_id: uuid.UUID | None = Query(None),
    page: Page = Depends(page),
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[CorrectionRead]:
    statement = select(DataCorrection).where(DataCorrection.project_id == context.project.id)
    if correction_status:
        statement = statement.where(DataCorrection.status == correction_status)
    if target_type:
        statement = statement.where(DataCorrection.target_type == target_type)
    if device_id is not None:
        statement = statement.where(DataCorrection.device_id == device_id)
    if job_id is not None:
        statement = statement.where(DataCorrection.curation_job_id == job_id)
    rows, next_cursor = await paginate(
        session, DataCorrection.created_at, statement, page, descending=True
    )
    return PageResponse(
        items=[CorrectionRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.get("/history", response_model=RecordHistory)
async def record_history(
    target_type: str = Query(pattern="^(position|measurement)$"),
    target_id: int = Query(ge=1),
    target_time: datetime = Query(),
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> RecordHistory:
    """The effective and original values of one record with every correction, for the marker
    on curated fields (architecture 28.12)."""
    record = await load_record(session, target_type, target_id, require_aware(target_time))
    if record is None or record.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found in this project")
    fields = CURATABLE[CurationTarget(target_type)]
    corrections = (
        await session.scalars(
            select(DataCorrection)
            .where(
                DataCorrection.target_type == target_type,
                DataCorrection.target_id == target_id,
                DataCorrection.target_time == record.time,
            )
            .order_by(DataCorrection.created_at.desc())
        )
    ).all()
    return RecordHistory(
        target_type=target_type,
        target_id=target_id,
        target_time=record.time,
        effective={f.value: effective_of(record, f) for f in fields},
        original={f.value: original_of(record, f) for f in fields},
        curated_fields=list(record.curated_fields or []),
        valid=record.valid,
        curation_version=record.curation_version,
        corrections=[CorrectionRead.model_validate(c) for c in corrections],
    )


@router.post("/corrections", response_model=CorrectionRead, status_code=status.HTTP_201_CREATED)
async def create_correction(
    body: CorrectionCreate,
    context: ProjectContext = Depends(require_permission(Permission.DATA_CURATE)),
    session: AsyncSession = Depends(get_session),
) -> DataCorrection:
    """Correct one field of one record. Applied at once, or left pending when the project
    requires approval (decision D81). The permission is a route dependency, so a caller
    without it is refused before the body is read (decision D94)."""
    record = await load_record(session, body.target_type, body.target_id, body.target_time)
    if record is None or record.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found in this project")
    try:
        value = normalize_value(body.target_type, body.field, body.corrected_value)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    before = effective_of(record, body.field)
    if value == before:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "the corrected value equals the current value"
        )
    correction = DataCorrection(
        project_id=context.project.id,
        target_type=body.target_type,
        target_id=record.id,
        target_time=record.time,
        device_id=record.device_id,
        entity_id=record.entity_id,
        metric_key=getattr(record, "metric_key", None),
        field=body.field,
        original_value=before,
        corrected_value=value,
        reason_code=_reason(body.reason_code),
        comment=body.comment,
        status=CorrectionStatus.PENDING,
        created_by_user_id=context.user.id,
    )
    session.add(correction)
    await session.flush()
    action = "correction.proposed"
    if not _requires_approval(context):
        try:
            applied = await apply_correction(session, correction)
        except ApplicationError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
        await recompute_current_state(session, applied.device_id, applied.entity_ids)
        action = "correction.applied"
    await record_audit(
        session,
        user=context.user,
        action=action,
        object_type="data_correction",
        object_id=str(correction.id),
        project_id=context.project.id,
        details={
            "target": f"{body.target_type}:{record.id}",
            "field": body.field,
            "reason": correction.reason_code,
            "status": correction.status,
        },
    )
    await session.commit()
    return correction


async def _project_correction(
    session: AsyncSession, context: ProjectContext, correction_id: uuid.UUID
) -> DataCorrection:
    correction = await get_or_404(session, DataCorrection, correction_id, "Correction")
    if correction.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correction not found")
    return correction


@router.get("/corrections/{correction_id}", response_model=CorrectionRead)
async def get_correction(
    correction_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> DataCorrection:
    return await _project_correction(session, context, correction_id)


@router.post("/corrections/{correction_id}/approve", response_model=CorrectionRead)
async def approve_correction(
    correction_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> DataCorrection:
    """The second person of the two-step workflow (architecture 28.11): applies the pending
    correction. The proposer cannot approve their own."""
    _need(context, Permission.DATA_APPROVE)
    correction = await _project_correction(session, context, correction_id)
    if correction.status != CorrectionStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The correction is {correction.status}")
    if correction.created_by_user_id == context.user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A correction is approved by someone other than its author"
        )
    try:
        applied = await apply_correction(session, correction)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    correction.approved_by_user_id = context.user.id
    correction.approved_at = utc_now()
    await recompute_current_state(session, applied.device_id, applied.entity_ids)
    await record_audit(
        session,
        user=context.user,
        action="correction.approved",
        object_type="data_correction",
        object_id=str(correction.id),
        project_id=context.project.id,
        details={"field": correction.field, "reason": correction.reason_code},
    )
    await session.commit()
    return correction


@router.post("/corrections/{correction_id}/revert", response_model=CorrectionRead)
async def revert_one(
    correction_id: uuid.UUID,
    body: CorrectionRevert,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> DataCorrection:
    _need(context, Permission.DATA_REVERT)
    correction = await _project_correction(session, context, correction_id)
    if correction.status == CorrectionStatus.PENDING:
        correction.status = CorrectionStatus.REVERTED
        correction.reverted_at = utc_now()
        correction.reverted_by_user_id = context.user.id
        correction.revert_comment = body.comment
    else:
        try:
            applied = await revert_correction(
                session, correction, user_id=context.user.id, comment=body.comment
            )
        except ApplicationError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
        await recompute_current_state(session, applied.device_id, applied.entity_ids)
    await record_audit(
        session,
        user=context.user,
        action="correction.reverted",
        object_type="data_correction",
        object_id=str(correction.id),
        project_id=context.project.id,
        details={"field": correction.field, "comment": body.comment},
    )
    await session.commit()
    return correction


# Bulk jobs


@router.get("/jobs", response_model=PageResponse[JobRead])
async def list_jobs(
    job_status: str | None = Query(None, alias="status"),
    page: Page = Depends(page),
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[JobRead]:
    statement = select(CurationJob).where(CurationJob.project_id == context.project.id)
    if job_status:
        statement = statement.where(CurationJob.status == job_status)
    rows, next_cursor = await paginate(
        session, CurationJob.created_at, statement, page, descending=True
    )
    return PageResponse(items=[JobRead.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreate,
    context: ProjectContext = Depends(require_permission(Permission.DATA_CURATE_BULK)),
    session: AsyncSession = Depends(get_session),
) -> CurationJob:
    """Define a bulk correction and preview it (architecture 28.5): the count, samples before
    and after, and the impact on attribution, deliveries and rules. Nothing is applied."""
    try:
        transformation = Transformation.model_validate(body.transformation.model_dump())
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    job = CurationJob(
        project_id=context.project.id,
        status=CurationJobStatus.PREVIEWED,
        target_type=body.target_type,
        device_ids=[str(d) for d in body.device_ids],
        entity_ids=[str(e) for e in body.entity_ids],
        metric_keys=list(body.metric_keys),
        time_from=require_aware(body.time_from),
        time_to=require_aware(body.time_to),
        transformation=transformation.model_dump(),
        reason_code=_reason(body.reason_code),
        comment=body.comment,
        replay_rules=body.replay_rules,
        created_by_user_id=context.user.id,
    )
    try:
        validate_job(job)
        session.add(job)
        await session.flush()
        await preview(session, job)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await record_audit(
        session,
        user=context.user,
        action="curation_job.created",
        object_type="curation_job",
        object_id=str(job.id),
        project_id=context.project.id,
        details={
            "target_type": job.target_type,
            "transformation": transformation.describe(),
            "affected": job.affected_count,
        },
    )
    await session.commit()
    return job


async def _project_job(
    session: AsyncSession, context: ProjectContext, job_id: uuid.UUID
) -> CurationJob:
    job = await get_or_404(session, CurationJob, job_id, "Curation job")
    if job.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Curation job not found")
    return job


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> CurationJob:
    return await _project_job(session, context, job_id)


@router.post("/jobs/{job_id}/preview", response_model=JobRead)
async def preview_job(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> CurationJob:
    _need(context, Permission.DATA_CURATE_BULK)
    job = await _project_job(session, context, job_id)
    if job.status not in (
        CurationJobStatus.PREVIEWED,
        CurationJobStatus.PENDING,
        CurationJobStatus.FAILED,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"The job is {job.status}")
    try:
        await preview(session, job)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await session.commit()
    return job


@router.post("/jobs/{job_id}/apply", response_model=JobRead)
async def apply_job(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> CurationJob:
    """Apply a previewed job in the batch worker, or leave it pending for approval when the
    project requires it (decision D81)."""
    _need(context, Permission.DATA_CURATE_BULK)
    job = await _project_job(session, context, job_id)
    if job.status not in (CurationJobStatus.PREVIEWED, CurationJobStatus.FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"The job is {job.status}")
    if job.affected_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The selection holds no records")
    if _requires_approval(context):
        job.status = CurationJobStatus.PENDING
        action = "curation_job.apply_proposed"
    else:
        job.status = CurationJobStatus.APPLYING
        action = "curation_job.apply_requested"
    await record_audit(
        session,
        user=context.user,
        action=action,
        object_type="curation_job",
        object_id=str(job.id),
        project_id=context.project.id,
        details={"affected": job.affected_count},
    )
    await session.commit()
    if job.status == CurationJobStatus.APPLYING:
        await _publish_job(bus, job, "apply", context.user.id)
    return job


@router.post("/jobs/{job_id}/approve", response_model=JobRead)
async def approve_job(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> CurationJob:
    _need(context, Permission.DATA_APPROVE)
    job = await _project_job(session, context, job_id)
    if job.status != CurationJobStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The job is {job.status}")
    if job.created_by_user_id == context.user.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A job is approved by someone other than its author"
        )
    job.status = CurationJobStatus.APPLYING
    job.approved_by_user_id = context.user.id
    job.approved_at = utc_now()
    await record_audit(
        session,
        user=context.user,
        action="curation_job.approved",
        object_type="curation_job",
        object_id=str(job.id),
        project_id=context.project.id,
        details={"affected": job.affected_count},
    )
    await session.commit()
    await _publish_job(bus, job, "apply", context.user.id)
    return job


@router.post("/jobs/{job_id}/revert", response_model=JobRead)
async def revert_job(
    job_id: uuid.UUID,
    body: CorrectionRevert,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> CurationJob:
    _need(context, Permission.DATA_REVERT)
    job = await _project_job(session, context, job_id)
    if job.status == CurationJobStatus.PENDING:
        job.status = CurationJobStatus.REVERTED
        job.reverted_at = utc_now()
        job.reverted_by_user_id = context.user.id
        await session.commit()
        return job
    if job.status not in (CurationJobStatus.APPLIED, CurationJobStatus.FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"The job is {job.status}")
    job.status = CurationJobStatus.REVERTING
    await record_audit(
        session,
        user=context.user,
        action="curation_job.revert_requested",
        object_type="curation_job",
        object_id=str(job.id),
        project_id=context.project.id,
        details={"comment": body.comment},
    )
    await session.commit()
    await _publish_job(bus, job, "revert", context.user.id, body.comment)
    return job
