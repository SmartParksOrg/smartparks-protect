"""Run one analysis (docs/ANALYTICS_PHASE1_PLAN.md, section 7): the run row is the record, its
status, progress, result or error. A failure is stored and never re-raised, because a retry
would produce the same failure; a timeout and a cancellation are stored the same way."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

from geoalchemy2.shape import from_shape
from pydantic import BaseModel
from shapely.geometry import shape
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis import MODULES, enabled_modules
from shared.analysis.base import AnalysisCancelled, RunContext, RunResult
from shared.analysis.limits import MAX_GEOMETRIES, MAX_RESULT_BYTES, RESULT_RETENTION_DAYS
from shared.config import get_settings
from shared.database import get_session_factory
from shared.enums import AnalysisStatus
from shared.logger import get_logger
from shared.models import AnalysisGeometry, AnalysisRun
from shared.timeutil import utc_now

log = get_logger("analysis.runner")
CLEANUP_BATCH = 100


class AnalysisTooLarge(Exception):
    """The module read or produced more than the run may hold."""


async def _write(run_id: uuid.UUID, **values: object) -> None:
    """A change to the run row through its own short session, so the module's session and its
    cursors stay untouched (the export runner does the same for progress)."""
    async with get_session_factory()() as other:
        await other.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(**values))
        await other.commit()


async def _cancel_requested(run_id: uuid.UUID) -> bool:
    async with get_session_factory()() as other:
        flag = await other.scalar(
            select(AnalysisRun.cancel_requested).where(AnalysisRun.id == run_id)
        )
        return bool(flag)


async def run_analysis(session: AsyncSession, run: AnalysisRun) -> None:
    """Run one queued analysis on `session`; the row ends completed, failed or cancelled."""
    settings = get_settings()
    run_id, project_id, key = run.id, run.project_id, run.module
    module = MODULES.get(key)
    if module is None or key not in enabled_modules(settings):
        await _finish(session, run, AnalysisStatus.FAILED, "MODULE_DISABLED", f"{key} is off")
        return
    run.status = AnalysisStatus.RUNNING
    run.started_at = utc_now()
    await session.commit()
    # the module's statements end with the run's own timeout, not the API's
    timeout_ms = int(settings.analysis_statement_timeout_seconds) * 1000
    await session.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))

    async def progress(percent: int, step: str) -> None:
        await _write(run_id, progress=max(0, min(100, percent)))
        if await _cancel_requested(run_id):
            raise AnalysisCancelled(step)

    ctx = RunContext(
        project_id=project_id,
        run_id=run_id,
        session=session,
        progress=progress,
        cancelled=lambda: _cancel_requested(run_id),
    )
    try:
        params: BaseModel = module.parameters.model_validate(run.parameters)
        result = await asyncio.wait_for(
            module.run(ctx, params), timeout=settings.analysis_timeout_seconds
        )
        await _store(session, run, result)
        await _finish(session, run, AnalysisStatus.COMPLETED)
    except AnalysisCancelled as stopped:
        await session.rollback()
        await _finish(session, run, AnalysisStatus.CANCELLED, "CANCELLED", str(stopped))
    except TimeoutError:
        await session.rollback()
        await _finish(
            session,
            run,
            AnalysisStatus.FAILED,
            "ANALYSIS_TIMEOUT",
            f"the run exceeded {settings.analysis_timeout_seconds} seconds",
        )
    except AnalysisTooLarge as error:
        await session.rollback()
        await _finish(session, run, AnalysisStatus.FAILED, "INPUT_TOO_LARGE", str(error))
    except Exception as error:
        await session.rollback()
        await _finish(session, run, AnalysisStatus.FAILED, "ANALYSIS_FAILED", str(error))
        log.exception("analysis failed", run_id=str(run_id), module=key, error=str(error))


async def _store(session: AsyncSession, run: AnalysisRun, result: RunResult) -> None:
    document = result.document.model_dump(mode="json")
    size = len(json.dumps(document).encode())
    if size > MAX_RESULT_BYTES:
        raise AnalysisTooLarge(
            f"the result document is {size} bytes, above {MAX_RESULT_BYTES}; "
            "choose fewer subjects, areas or a shorter period"
        )
    if len(result.geometries) > MAX_GEOMETRIES:
        raise AnalysisTooLarge(
            f"{len(result.geometries)} result geometries, above {MAX_GEOMETRIES}"
        )
    await session.execute(delete(AnalysisGeometry).where(AnalysisGeometry.run_id == run.id))
    for g in result.geometries:
        session.add(
            AnalysisGeometry(
                run_id=run.id,
                kind=g.kind,
                subject_id=g.subject_id,
                label=g.label,
                level=g.level,
                geom=from_shape(shape(g.geojson), srid=4326),
                properties=g.properties,
            )
        )
    run.result = document
    run.result_version = result.document.version
    run.input_count = result.document.provenance.input_count
    run.excluded_count = result.document.provenance.excluded_count
    await session.flush()
    # the area of every polygon from PostGIS, in one statement
    await session.execute(
        text(
            "UPDATE analysis_geometries SET area_m2 = ST_Area(geom::geography) "
            "WHERE run_id = :run_id AND ST_Dimension(geom) = 2"
        ),
        {"run_id": run.id},
    )


async def _finish(
    session: AsyncSession,
    run: AnalysisRun,
    status: AnalysisStatus,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    finished = utc_now()
    run.status = status
    run.error_code = error_code
    run.error_message = error_message[:2000] if error_message else None
    run.finished_at = finished
    run.progress = 100 if status == AnalysisStatus.COMPLETED else run.progress
    if run.name is None:
        run.expires_at = finished + timedelta(days=RESULT_RETENTION_DAYS)
    await session.commit()


async def expire_analyses(session: AsyncSession) -> int:
    """Delete runs past their expiry (their geometries go by cascade); returns how many."""
    now = utc_now()
    ids = list(
        await session.scalars(
            select(AnalysisRun.id)
            .where(AnalysisRun.expires_at.is_not(None), AnalysisRun.expires_at < now)
            .order_by(AnalysisRun.expires_at)
            .limit(CLEANUP_BATCH)
        )
    )
    if not ids:
        return 0
    await session.execute(delete(AnalysisRun).where(AnalysisRun.id.in_(ids)))
    await session.commit()
    return len(ids)
