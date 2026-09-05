"""Retention of export files (architecture 14): a finished job keeps its file for
`JOB_RETENTION_DAYS`; after that the export service removes the object and marks the job
expired, so the metadata and the reproduce link stay while the disk is freed. Found necessary
on the dev server, where three benchmark exports of 4.9 GB each had nothing to remove them."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.enums import ExportStatus
from shared.logger import get_logger
from shared.models import ExportJob
from shared.storage import remove_object
from shared.timeutil import utc_now

log = get_logger("export.cleanup")
BATCH = 100


async def expire_exports(session: AsyncSession, now: datetime | None = None) -> int:
    """Remove the files of done jobs past their expiry; returns how many were expired."""
    moment = now or utc_now()
    jobs = list(
        await session.scalars(
            select(ExportJob)
            .where(
                ExportJob.status == ExportStatus.DONE,
                ExportJob.expires_at.is_not(None),
                ExportJob.expires_at < moment,
                ExportJob.object_key.is_not(None),
            )
            .order_by(ExportJob.expires_at)
            .limit(BATCH)
        )
    )
    bucket = get_settings().minio_bucket_exports
    expired = 0
    for job in jobs:
        key = str(job.object_key)
        try:
            await remove_object(bucket, key)
        except Exception as exc:
            log.warning("export file not removed", job_id=str(job.id), key=key, error=str(exc))
            continue
        job.status = ExportStatus.EXPIRED
        expired += 1
        log.info("export file expired", job_id=str(job.id), key=key, size_bytes=job.size_bytes)
    if expired:
        await session.commit()
    return expired
