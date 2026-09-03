"""Run an export job to MinIO, or stream a small export straight to the caller."""

import contextlib
import hashlib
import io
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, BinaryIO, cast

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analytics import AnalyticsError, Layout
from shared.config import get_settings
from shared.database import get_session_factory
from shared.enums import ExportDataset, ExportFormat, ExportStatus
from shared.exports import DIRECT_MAX_ROWS, JOB_RETENTION_DAYS, ExportParameters
from shared.exports.datasets import (
    Lookups,
    columns,
    count_statement,
    load_lookups,
    metadata,
    stream_rows,
)
from shared.exports.writers import CONTENT_TYPES, make_writer
from shared.logger import get_logger
from shared.models import ExportJob
from shared.storage import put_file
from shared.timeutil import utc_now
from shared.version import read_version

log = get_logger("exports")

PROGRESS_EVERY = 10_000
CHUNK = 256 * 1024


class ExportTooLarge(Exception):
    def __init__(self, rows: int) -> None:
        super().__init__(
            f"{rows} rows exceed the direct export limit of {DIRECT_MAX_ROWS}; create an export job"
        )
        self.rows = rows


def object_key(job: ExportJob) -> str:
    return f"projects/{job.project_id}/{job.id}.{job.format}"


def filename(params: ExportParameters, job_id: uuid.UUID | None = None) -> str:
    stamp = params.time_from.strftime("%Y%m%d") + "-" + params.time_to.strftime("%Y%m%d")
    tail = f"-{str(job_id)[:8]}" if job_id else ""
    return f"{params.dataset.value}-{stamp}{tail}.{params.format.value}"


async def _write_all(
    session: AsyncSession,
    project_id: uuid.UUID,
    params: ExportParameters,
    lookups: Lookups,
    stream: BinaryIO,
    on_progress: Any = None,
) -> int:
    """Write every row into `stream`; returns the row count. Wide aggregate exports learn their
    columns from the first row, every other dataset knows them up front."""
    meta = metadata(params, lookups, read_version())
    wide = params.dataset is ExportDataset.AGGREGATES and params.layout is Layout.WIDE
    writer = None if wide else make_writer(params.format, stream, columns(params, lookups), meta)
    count = 0
    async for row in stream_rows(session, project_id, params, lookups):
        if writer is None:
            header = [c for c in row if c != "time_utc"]
            writer = make_writer(params.format, stream, header, meta)
        writer.write_row(row)
        count += 1
        if on_progress is not None and count % PROGRESS_EVERY == 0:
            await on_progress(count)
    if writer is None:
        writer = make_writer(params.format, stream, columns(params, lookups), meta)
    writer.finish()
    return count


async def run_export(session: AsyncSession, job: ExportJob) -> None:
    """Run one job. The job row is the record: status, progress, result or error. Failures are
    logged and stored, not re-raised, because a retry would produce the same failure."""
    params = ExportParameters.model_validate(job.parameters)
    settings = get_settings()
    # read before the first commit: a session that expires on commit would otherwise reload
    job_id, project_id, key = job.id, job.project_id, object_key(job)
    job.status = ExportStatus.RUNNING
    job.started_at = utc_now()
    await session.commit()

    async def progress(count: int) -> None:
        # A commit on the streaming session would close the server-side cursor, so progress goes
        # through its own short session.
        async with get_session_factory()() as other:
            await other.execute(
                update(ExportJob).where(ExportJob.id == job_id).values(progress_rows=count)
            )
            await other.commit()

    path = None
    try:
        lookups = await load_lookups(session, project_id)
        with tempfile.NamedTemporaryFile(suffix=f".{job.format}", delete=False) as handle:
            path = handle.name
            sink = cast(BinaryIO, handle)
            count = await _write_all(session, project_id, params, lookups, sink, progress)
        size, digest = _size_and_sha256(path)
        await put_file(settings.minio_bucket_exports, key, path, CONTENT_TYPES[params.format])
        job.status = ExportStatus.DONE
        job.row_count = count
        job.progress_rows = count
        job.object_key = key
        job.size_bytes = size
        job.sha256 = digest
        job.metadata_ = {
            **metadata(params, lookups, read_version()),
            "row_count": count,
            "size_bytes": size,
            "sha256": digest,
        }
        finished = utc_now()
        job.finished_at = finished
        job.expires_at = finished + timedelta(days=JOB_RETENTION_DAYS)
        await session.commit()
    except Exception as error:
        await session.rollback()
        job.status = ExportStatus.FAILED
        job.error_code = "EXPORT_FAILED"
        job.error_message = str(error)[:2000]
        job.finished_at = utc_now()
        await session.commit()
        log.exception("export failed", job_id=str(job_id), error=str(error))
    finally:
        if path is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)


def _size_and_sha256(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


class _ChunkBuffer(io.RawIOBase):
    """A write sink the streaming response drains in chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        self._buffer += data
        return len(data)

    def take(self) -> bytes:
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk

    def __len__(self) -> int:
        return len(self._buffer)


async def check_direct_size(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters
) -> None:
    """Refuse a direct export above DIRECT_MAX_ROWS before any row is written."""
    statement = count_statement(project_id, params)
    if statement is None:
        return
    rows = int(await session.scalar(statement) or 0)
    if rows > DIRECT_MAX_ROWS:
        raise ExportTooLarge(rows)


async def direct_export(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters
) -> AsyncIterator[bytes]:
    """Stream a small export. Formats that are complete only at the end (XLSX) go through a
    temporary file; the rest are yielded as they are written."""
    try:
        lookups = await load_lookups(session, project_id)
        if params.format is ExportFormat.XLSX:
            with tempfile.TemporaryFile(suffix=".xlsx") as handle:
                await _write_all(session, project_id, params, lookups, cast(BinaryIO, handle))
                handle.seek(0)
                while chunk := handle.read(CHUNK):
                    yield chunk
            return
        buffer = _ChunkBuffer()
        sink = cast(BinaryIO, buffer)
        meta = metadata(params, lookups, read_version())
        wide = params.dataset is ExportDataset.AGGREGATES and params.layout is Layout.WIDE
        writer = None if wide else make_writer(params.format, sink, columns(params, lookups), meta)
        async for row in stream_rows(session, project_id, params, lookups):
            if writer is None:
                writer = make_writer(params.format, sink, [c for c in row if c != "time_utc"], meta)
            writer.write_row(row)
            if len(buffer) >= CHUNK:
                yield buffer.take()
        if writer is None:
            writer = make_writer(params.format, sink, columns(params, lookups), meta)
        writer.finish()
        yield buffer.take()
    except AnalyticsError as error:
        raise ValueError(str(error)) from None
