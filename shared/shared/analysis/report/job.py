"""The PDF report as a job (decision D211): the API queues it on the run row, the export
service gathers the run's document, geometries and tracks, renders the PDF and keeps it in
the exports bucket beside the run."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select

from shared.analysis.base import AnalysisTooLarge
from shared.analysis.primitives.trajectory import load_trajectory
from shared.analysis.report.mapimage import (
    MapPicture,
    TrackLine,
    map_picture,
    shapes_from_geometries,
)
from shared.analysis.report.render import ReportInput, render_pdf, subject_colors
from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.database import session_scope
from shared.enums import ReportStatus
from shared.logger import get_logger
from shared.models import AnalysisGeometry, AnalysisRun, Project, User
from shared.storage import put_object, remove_object
from shared.timeutil import utc_now
from shared.version import __version__

log = get_logger("analysis.report")

REPORT_PREFIX = "analysis-reports"
#: A track is drawn with at most this many points; the map is a picture, not the data.
TRACK_POINTS = 2000


def report_key(run_id: uuid.UUID) -> str:
    return f"{REPORT_PREFIX}/{run_id}.pdf"


def queue_report(run: AnalysisRun) -> None:
    """Mark the run's report queued; the caller commits and publishes."""
    run.report_status = ReportStatus.QUEUED
    run.report_error = None


def report_message(run: AnalysisRun) -> tuple[str, dict[str, Any]]:
    return Topic.ANALYSIS_REPORT_REQUESTED, {"run_id": str(run.id)}


async def publish_report(bus: RedisStreamsBus, run: AnalysisRun) -> None:
    topic, payload = report_message(run)
    await bus.publish(topic, payload)


async def remove_report(run: AnalysisRun) -> None:
    """The PDF goes with the run (a deletion, an expiry)."""
    if run.report_key:
        await remove_object(get_settings().minio_bucket_exports, run.report_key)


async def _tracks(
    session: Any, document: dict[str, Any], colors: dict[str, str], max_fixes: int
) -> list[TrackLine]:
    main = next((p for p in document.get("periods", []) if p.get("key") == "main"), None)
    if main is None:
        return []
    from datetime import datetime

    time_from = datetime.fromisoformat(main["time_from"])
    time_to = datetime.fromisoformat(main["time_to"])
    tracks: list[TrackLine] = []
    for subject in document.get("subjects", []):
        entity_id = uuid.UUID(str(subject["id"]))
        try:
            trajectory = await load_trajectory(
                session, entity_id, time_from, time_to, max_fixes=max_fixes
            )
        except AnalysisTooLarge:
            log.info("report track skipped, too many fixes", entity_id=str(entity_id))
            continue
        n = len(trajectory.times)
        if n == 0:
            continue
        step = max(1, n // TRACK_POINTS)
        tracks.append(
            TrackLine(
                lon=[float(v) for v in trajectory.lon[::step]],
                lat=[float(v) for v in trajectory.lat[::step]],
                color=colors.get(str(subject["id"]), "#52735E"),
                label=str(subject["name"]),
            )
        )
    return tracks


async def _geometries(session: Any, run_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(AnalysisGeometry)
        .where(AnalysisGeometry.run_id == run_id)
        .order_by(AnalysisGeometry.id)
    )
    return [
        {
            "kind": row.kind,
            "subject_id": row.subject_id,
            "label": row.label,
            "level": row.level,
            "geojson": mapping(to_shape(row.geom)),
        }
        for row in rows
    ]


async def build_input(session: Any, run: AnalysisRun) -> ReportInput:
    """Everything the report needs from the database, plus the map picture."""
    settings = get_settings()
    document = run.result or {}
    project = await session.get(Project, run.project_id)
    creator = await session.get(User, run.created_by_user_id) if run.created_by_user_id else None
    colors = subject_colors(document)
    shapes = shapes_from_geometries(await _geometries(session, run.id), colors)
    tracks = await _tracks(session, document, colors, settings.analysis_max_fixes)
    picture: MapPicture | None = await map_picture(
        tracks,
        shapes,
        maptiler_key=settings.maptiler_key,
        referer=settings.public_url,
    )
    provenance = document.get("provenance") or {}
    computed = provenance.get("computed_at")
    from datetime import datetime

    return ReportInput(
        document=document,
        parameters=dict(run.parameters),
        module=run.module,
        run_name=run.name,
        project_name=project.name if project else "",
        timezone=project.timezone if project else "UTC",
        created_by=(creator.full_name or creator.email) if creator else None,
        created_at=run.created_at,
        computed_at=datetime.fromisoformat(computed) if isinstance(computed, str) else None,
        version=__version__,
        map=picture,
    )


async def run_report_job(payload: dict[str, Any]) -> None:
    """The handler of `analysis_report.requested`: render the run's PDF and keep it."""
    run_id = uuid.UUID(str(payload["run_id"]))
    async with session_scope() as session:
        run = await session.get(AnalysisRun, run_id)
        if run is None:
            log.warning("analysis run gone before its report", run_id=str(run_id))
            return
        if run.result is None:
            run.report_status = ReportStatus.FAILED
            run.report_error = "The run has no result to report"
            await session.commit()
            return
        run.report_status = ReportStatus.RUNNING
        run.report_error = None
        await session.commit()
        try:
            inp = await build_input(session, run)
            pdf = render_pdf(inp)
            key = report_key(run.id)
            await put_object(get_settings().minio_bucket_exports, key, pdf, "application/pdf")
        except Exception as exc:
            await session.rollback()
            run = await session.get(AnalysisRun, run_id)
            if run is not None:
                run.report_status = ReportStatus.FAILED
                run.report_error = f"{type(exc).__name__}: {exc}"[:1000]
                await session.commit()
            log.error("analysis report failed", run_id=str(run_id), exc_info=True)
            raise
        run.report_status = ReportStatus.READY
        run.report_key = key
        run.report_at = utc_now()
        await session.commit()
    log.info("analysis report ready", run_id=str(run_id), bytes=len(pdf))
