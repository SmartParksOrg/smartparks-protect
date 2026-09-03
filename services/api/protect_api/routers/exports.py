"""Exports (architecture 14): jobs run by the export service, small direct downloads here."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.common import ORMModel
from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.database import get_session
from shared.enums import ExportStatus
from shared.exports import ExportParameters
from shared.exports.runner import (
    ExportTooLarge,
    check_direct_size,
    direct_export,
    filename,
)
from shared.exports.writers import CONTENT_TYPES
from shared.models import ExportJob
from shared.permissions import Permission
from shared.storage import stream_object

router = APIRouter(prefix="/projects/{project_id}/exports", tags=["exports"])


class ExportJobRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID | None
    status: str
    dataset: str
    format: str
    parameters: dict[str, Any]
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    source_job_id: uuid.UUID | None
    progress_rows: int
    row_count: int | None
    size_bytes: int | None
    sha256: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None


async def _project_job(
    session: AsyncSession, context: ProjectContext, job_id: uuid.UUID
) -> ExportJob:
    job = await get_or_404(session, ExportJob, job_id, "Export job")
    if job.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export job not found")
    return job


async def _queue(
    session: AsyncSession,
    bus: RedisStreamsBus,
    context: ProjectContext,
    params: ExportParameters,
    source_job: ExportJob | None = None,
) -> ExportJob:
    job = ExportJob(
        project_id=context.project.id,
        created_by=context.user.id,
        status=ExportStatus.QUEUED,
        dataset=params.dataset,
        format=params.format,
        parameters=params.model_dump(mode="json"),
        source_job_id=source_job.id if source_job else None,
    )
    session.add(job)
    await session.flush()
    await record_audit(
        session,
        user=context.user,
        action="export.created",
        object_type="export_job",
        object_id=str(job.id),
        project_id=context.project.id,
        details={"dataset": params.dataset, "format": params.format},
    )
    await session.commit()
    await bus.publish(Topic.EXPORT_REQUESTED, {"job_id": str(job.id)})
    return job


@router.post("", response_model=ExportJobRead, status_code=status.HTTP_201_CREATED)
async def create_export(
    params: ExportParameters,
    context: ProjectContext = Depends(require_permission(Permission.EXPORTS_CREATE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ExportJob:
    """Queue an export job. The export service writes the file to MinIO; poll the job, then
    download it. Nothing is limited in size here, the file streams from the database."""
    return await _queue(session, bus, context, params)


@router.get("", response_model=PageResponse[ExportJobRead])
async def list_exports(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[ExportJobRead]:
    rows, next_cursor = await paginate(
        session,
        ExportJob.id,
        select(ExportJob).where(ExportJob.project_id == context.project.id),
        page,
    )
    return PageResponse(
        items=[ExportJobRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.get("/direct")
async def direct(
    params: Annotated[ExportParameters, Query()],
    context: ProjectContext = Depends(require_permission(Permission.EXPORTS_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Download a small export at once (at most DIRECT_MAX_ROWS rows, architecture 13.8).
    Larger requests get 413 and should become a job."""
    try:
        await check_direct_size(session, context.project.id, params)
    except ExportTooLarge as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    await record_audit(
        session,
        user=context.user,
        action="export.direct",
        object_type="project",
        object_id=str(context.project.id),
        project_id=context.project.id,
        details={"dataset": params.dataset, "format": params.format},
    )
    await session.commit()
    return StreamingResponse(
        direct_export(session, context.project.id, params),
        media_type=CONTENT_TYPES[params.format],
        headers={"Content-Disposition": f'attachment; filename="{filename(params)}"'},
    )


@router.get("/{job_id}", response_model=ExportJobRead)
async def get_export(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> ExportJob:
    return await _project_job(session, context, job_id)


@router.get("/{job_id}/download")
async def download_export(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """The finished file, streamed from MinIO through the API (the browser never talks to
    MinIO)."""
    job = await _project_job(session, context, job_id)
    if job.status != ExportStatus.DONE or job.object_key is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Export is {job.status}, not done")
    params = ExportParameters.model_validate(job.parameters)
    return StreamingResponse(
        stream_object(get_settings().minio_bucket_exports, job.object_key),
        media_type=CONTENT_TYPES[params.format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename(params, job.id)}"',
            "Content-Length": str(job.size_bytes) if job.size_bytes else "",
            "X-Content-SHA256": job.sha256 or "",
        },
    )


@router.post(
    "/{job_id}/reproduce", response_model=ExportJobRead, status_code=status.HTTP_201_CREATED
)
async def reproduce_export(
    job_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.EXPORTS_CREATE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ExportJob:
    """Run the same parameters again as a new job (architecture 14: reproducible from explicit
    filters). Late data makes the result differ; the metadata of both jobs shows how."""
    source = await _project_job(session, context, job_id)
    params = ExportParameters.model_validate(source.parameters)
    return await _queue(session, bus, context, params, source_job=source)
