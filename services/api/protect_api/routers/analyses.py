"""Analyses (docs/ANALYTICS_PHASE1_PLAN.md, section 12): the module catalogue, the runs of a
project and their results. The API validates, bounds, narrows to the caller's scope, creates
the row and publishes; the analysis worker computes. Nothing here reads the hypertable beyond
one bounded count for the estimate."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import shared.analysis.modules
import shared.analysis.providers  # noqa: F401  (registers the environmental providers)
from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.crud import geom_to_geojson, get_or_404
from protect_api.deps import ProjectContext, language, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.analysis import (
    AnalysisEstimate,
    AnalysisModuleRead,
    AnalysisRunCreate,
    AnalysisRunRead,
    AnalysisRunUpdate,
)
from protect_api.visibility import group_and_subgroups
from shared.analysis import MODULES, project_modules
from shared.analysis.limits import (
    MAX_ANIMALS_GRAZING,
    MAX_AREAS_GRAZING,
    MAX_DAYS,
    MAX_DEVICES,
    MAX_QUEUED_PER_PROJECT,
    MAX_SUBJECTS_MOVEMENT,
)
from shared.analysis.parameters import CommonParameters
from shared.analysis.report import publish_report, queue_report, remove_report
from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.curation.effective import device_fix, effective_time, visible
from shared.database import get_session
from shared.enums import AnalysisStatus, ReportStatus
from shared.i18n import translate
from shared.models import (
    AnalysisGeometry,
    AnalysisRun,
    Device,
    DeviceProjectAssignment,
    Entity,
    EntityType,
    Position,
    User,
)
from shared.permissions import Permission
from shared.storage import stream_object
from shared.timeutil import utc_now

router = APIRouter(tags=["analyses"])
MAX_GEOMETRIES_PER_CALL = 2_000
SUBJECT_LIMITS = {
    "movement": MAX_SUBJECTS_MOVEMENT,
    "grazing": MAX_ANIMALS_GRAZING,
    "device_performance": MAX_DEVICES,
}


def _subject_kind(module: Any) -> str:
    """Entities unless the module says its subjects are devices (decision D214)."""
    return str(getattr(module, "subject_kind", "entity"))


def _module(key: str, context: ProjectContext) -> Any:
    """The module when the deployment and the project offer it; 404 otherwise, so a switched
    off module is absent rather than forbidden."""
    module = MODULES.get(key)
    if module is None or key not in project_modules(get_settings(), context.project.settings):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No analysis module {key}")
    return module


def _limits(key: str) -> dict[str, int]:
    out = {
        "subjects": SUBJECT_LIMITS.get(key, MAX_SUBJECTS_MOVEMENT),
        "days": MAX_DAYS,
        "fixes": get_settings().analysis_max_fixes,
    }
    if key == "grazing":
        out["areas"] = MAX_AREAS_GRAZING
    return out


@router.get("/analysis-modules", response_model=list[AnalysisModuleRead])
async def list_modules(_: User = Depends(current_active_user)) -> list[Any]:
    """The modules this deployment offers (the project's own list applies on the project)."""
    return [
        AnalysisModuleRead(key=m.key, label=m.label, version=m.version, limits=_limits(m.key))
        for key, m in MODULES.items()
        if key in project_modules(get_settings(), None)
    ]


async def _ensure_visible(
    session: AsyncSession, context: ProjectContext, entity_ids: list[uuid.UUID]
) -> None:
    """Every id names an entity of the project inside the caller's scope, or 422."""
    found = set(
        await session.scalars(
            select(Entity.id).where(
                Entity.project_id == context.project.id, Entity.id.in_(entity_ids)
            )
        )
    )
    missing = [str(i) for i in entity_ids if i not in found]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown entity {missing[0]}")
    outside = [i for i in entity_ids if not context.visibility.entity_visible(i)]
    if outside:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "An entity is outside what you may see"
        )


async def _resolve_devices(
    session: AsyncSession, context: ProjectContext, params: CommonParameters, limit: int
) -> list[uuid.UUID]:
    """The subjects as device ids (decision D214): the given ids, every device of a type, or
    every device, each assigned to the project at some point in the period and inside the
    caller's scope. A device outside the scope or the project is refused by id and skipped
    by type."""
    window = func.tstzrange(params.time_from, params.time_to, "[)")
    in_project = select(DeviceProjectAssignment.device_id).where(
        DeviceProjectAssignment.project_id == context.project.id,
        DeviceProjectAssignment.validity.op("&&")(window),
    )
    if params.device_ids:
        found = set(
            await session.scalars(
                select(Device.id).where(Device.id.in_(params.device_ids), Device.id.in_(in_project))
            )
        )
        missing = [str(i) for i in params.device_ids if i not in found]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Device {missing[0]} is not this project's in the period",
            )
        if any(not context.visibility.device_visible(i) for i in params.device_ids):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A device is outside what you may see"
            )
        ids = list(dict.fromkeys(params.device_ids))
    elif params.device_type_id is not None or params.all_devices:
        statement = select(Device.id).where(Device.id.in_(in_project)).order_by(Device.name)
        if params.device_type_id is not None:
            statement = statement.where(Device.device_type_id == params.device_type_id)
        ids = [i for i in await session.scalars(statement) if context.visibility.device_visible(i)]
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose devices, a device type or every device"
        )
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No device to analyse")
    if len(ids) > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{len(ids)} devices; at most {limit} in one run. Choose fewer, or split the run.",
        )
    return ids


async def _resolve_subjects(
    session: AsyncSession,
    context: ProjectContext,
    params: CommonParameters,
    limit: int,
    kind: str = "entity",
) -> list[uuid.UUID]:
    """The subjects as entity ids inside the project and the caller's scope: the given ids
    (an id outside the scope is refused), or a group with its subgroups, or a type. For a
    module over devices, device ids the same way."""
    if kind == "device":
        return await _resolve_devices(session, context, params, limit)
    project_id = context.project.id
    if params.entity_ids:
        await _ensure_visible(session, context, params.entity_ids)
        ids = list(dict.fromkeys(params.entity_ids))
    elif params.group_id is not None:
        statement = select(Entity.id).where(
            Entity.project_id == project_id,
            Entity.group_id.in_(group_and_subgroups(params.group_id)),
        )
        ids = [i for i in await session.scalars(statement) if context.visibility.entity_visible(i)]
    elif params.entity_type_id is not None:
        subtypes = select(EntityType.id).where(EntityType.parent_id == params.entity_type_id)
        statement = select(Entity.id).where(
            Entity.project_id == project_id,
            (Entity.entity_type_id == params.entity_type_id) | Entity.entity_type_id.in_(subtypes),
        )
        ids = [i for i in await session.scalars(statement) if context.visibility.entity_visible(i)]
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose entities, a group or an entity type"
        )
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No entity to analyse")
    if len(ids) > limit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{len(ids)} entities; at most {limit} in one run. Choose fewer, or split the run.",
        )
    return ids


async def _count_fixes(
    session: AsyncSession,
    entity_ids: list[uuid.UUID],
    params: CommonParameters,
    kind: str = "entity",
) -> int:
    """The device fixes the run would read over its subjects and periods, one bounded count."""
    owner = Position.device_id if kind == "device" else Position.entity_id
    windows = [(params.time_from, params.time_to)]
    if params.comparison:
        windows.append((params.comparison.time_from, params.comparison.time_to))
    total = 0
    for time_from, time_to in windows:
        count = await session.scalar(
            select(func.count())
            .select_from(Position)
            .where(
                owner.in_(entity_ids),
                effective_time(Position) >= time_from,
                effective_time(Position) < time_to,
                visible(Position),
                device_fix(),
            )
        )
        total += int(count or 0)
    return total


def _parse(module: Any, parameters: dict[str, Any]) -> CommonParameters:
    try:
        params = module.parameters.model_validate(parameters)
    except ValidationError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, error.errors()[0]["msg"]
        ) from None
    if not isinstance(params, CommonParameters):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Malformed parameters")
    return params


async def _estimate(
    session: AsyncSession, context: ProjectContext, key: str, parameters: dict[str, Any]
) -> tuple[AnalysisEstimate, CommonParameters, list[uuid.UUID]]:
    module = _module(key, context)
    params = _parse(module, parameters)
    limits = _limits(key)
    kind = _subject_kind(module)
    subjects = await _resolve_subjects(session, context, params, limits["subjects"], kind)
    fixes = await _count_fixes(session, subjects, params, kind)
    days = (params.time_to - params.time_from).total_seconds() / 86_400
    # a second herd (grazing) is narrowed the same way as the subjects
    herd_b: list[uuid.UUID] = list(getattr(params, "herd_b_entity_ids", None) or [])
    if herd_b:
        await _ensure_visible(session, context, herd_b)
        if len(herd_b) > limits["subjects"]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{len(herd_b)} entities in the second herd; at most {limits['subjects']}.",
            )
    reasons: list[str] = []
    check = getattr(module, "check", None)
    if check is not None:
        reasons.extend(await check(session, context.project.id, params))
    if fixes > limits["fixes"]:
        reasons.append(
            f"{fixes} fixes; at most {limits['fixes']} in one run. Choose fewer subjects or a "
            "shorter period."
        )
    estimate = AnalysisEstimate(
        module=key,
        subjects=len(subjects),
        days=round(days, 2),
        fixes=fixes,
        max_subjects=limits["subjects"],
        max_days=limits["days"],
        max_fixes=limits["fixes"],
        ok=not reasons,
        reasons=reasons,
    )
    return estimate, params, subjects


@router.get("/projects/{project_id}/analyses/estimate", response_model=AnalysisEstimate)
async def estimate(
    module: str,
    parameters: str = Query(description="The parameters as a JSON document"),
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
) -> AnalysisEstimate:
    """What a run would read, before it is queued."""
    try:
        document = json.loads(parameters)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "parameters is not JSON"
        ) from None
    result, _, _ = await _estimate(session, context, module, document)
    return result


def _visible_run(run: AnalysisRun, context: ProjectContext) -> bool:
    """A run is for the reader when it is theirs, shared, or the reader administers the
    project, and every subject is inside the reader's scope."""
    if (
        not run.shared
        and run.created_by_user_id != context.user.id
        and Permission.PROJECT_WRITE not in context.permissions
    ):
        return False
    if not context.visibility.limited:
        return True
    ids = run.parameters.get("entity_ids") or []
    devices = run.parameters.get("device_ids") or []
    return all(context.visibility.entity_visible(uuid.UUID(str(i))) for i in ids) and all(
        context.visibility.device_visible(uuid.UUID(str(i))) for i in devices
    )


async def _with_names(session: AsyncSession, reads: list[AnalysisRunRead]) -> None:
    """The name of the person who ran each, for the runs table."""
    ids = {r.created_by_user_id for r in reads if r.created_by_user_id}
    if not ids:
        return
    rows = (
        await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))
    ).all()
    names = {row.id: row.full_name or row.email for row in rows}
    for r in reads:
        r.created_by_name = names.get(r.created_by_user_id) if r.created_by_user_id else None


async def _read(session: AsyncSession, run: AnalysisRun, lang: str = "en") -> AnalysisRunRead:
    read = AnalysisRunRead.model_validate(run)
    await _with_names(session, [read])
    if lang != "en" and isinstance(read.result, dict) and read.result.get("warnings"):
        # the warnings the module composed, in the reader's language (decision D240); the
        # stored document keeps its English
        read.result = {
            **read.result,
            "warnings": [
                {**w, "text": translate(w.get("text"), lang)} if isinstance(w, dict) else w
                for w in read.result["warnings"]
            ],
        }
    return read


@router.get("/projects/{project_id}/analyses", response_model=PageResponse[AnalysisRunRead])
async def list_runs(
    module: str | None = None,
    run_status: AnalysisStatus | None = Query(None, alias="status"),
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AnalysisRunRead]:
    """The project's runs, newest first; the result document is left out here."""
    statement = select(AnalysisRun).where(AnalysisRun.project_id == context.project.id)
    if Permission.PROJECT_WRITE not in context.permissions:
        statement = statement.where(
            AnalysisRun.shared.is_(True) | (AnalysisRun.created_by_user_id == context.user.id)
        )
    if module:
        statement = statement.where(AnalysisRun.module == module)
    if run_status:
        statement = statement.where(AnalysisRun.status == run_status)
    rows, next_cursor = await paginate(session, AnalysisRun.id, statement, page)
    items = []
    for run in rows:
        if not _visible_run(run, context):
            continue
        read = AnalysisRunRead.model_validate(run)
        read.result = None
        items.append(read)
    await _with_names(session, items)
    return PageResponse(items=items, next_cursor=next_cursor)


@router.post(
    "/projects/{project_id}/analyses",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    body: AnalysisRunCreate,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> AnalysisRun:
    """Queue a run: the parameters validated by the module, the subjects resolved and narrowed
    to the caller's scope, the bounds checked, then the row and the message."""
    estimate, params, subjects = await _estimate(session, context, body.module, body.parameters)
    if not estimate.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, estimate.reasons[0])
    queued = await session.scalar(
        select(func.count())
        .select_from(AnalysisRun)
        .where(
            AnalysisRun.project_id == context.project.id,
            AnalysisRun.status.in_([AnalysisStatus.QUEUED, AnalysisStatus.RUNNING]),
        )
    )
    if int(queued or 0) >= MAX_QUEUED_PER_PROJECT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"{queued} runs are queued or running in this project; wait for one to finish",
        )
    module = _module(body.module, context)
    stored = params.model_dump(mode="json")
    if _subject_kind(module) == "device":
        stored["device_ids"] = [str(i) for i in subjects]
        stored.pop("entity_ids", None)
    else:
        stored["entity_ids"] = [str(i) for i in subjects]
        stored.pop("device_ids", None)
    for key in ("group_id", "entity_type_id", "device_type_id", "all_devices"):
        stored.pop(key, None)
    run = AnalysisRun(
        project_id=context.project.id,
        module=body.module,
        name=body.name,
        parameters=stored,
        method_version=module.version,
        created_by_user_id=context.user.id,
    )
    session.add(run)
    await session.flush()
    await record_audit(
        session,
        user=context.user,
        action="analysis.created",
        object_type="analysis_run",
        object_id=str(run.id),
        project_id=context.project.id,
        details={"module": body.module, "subjects": len(subjects), "fixes": estimate.fixes},
    )
    await session.commit()
    await bus.publish(Topic.ANALYSIS_REQUESTED, {"run_id": str(run.id)})
    return run


async def _run_for(
    session: AsyncSession, context: ProjectContext, run_id: uuid.UUID
) -> AnalysisRun:
    run = await get_or_404(session, AnalysisRun, run_id, "Analysis")
    if run.project_id != context.project.id or not _visible_run(run, context):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return run


def _may_change(run: AnalysisRun, context: ProjectContext) -> None:
    if run.created_by_user_id == context.user.id or Permission.PROJECT_WRITE in context.permissions:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the person who ran it, or a project admin")


@router.get("/projects/{project_id}/analyses/{run_id}", response_model=AnalysisRunRead)
async def get_run(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
    lang: str = Depends(language),
) -> AnalysisRunRead:
    return await _read(session, await _run_for(session, context, run_id), lang)


@router.patch("/projects/{project_id}/analyses/{run_id}", response_model=AnalysisRunRead)
async def update_run(
    run_id: uuid.UUID,
    body: AnalysisRunUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
) -> AnalysisRunRead:
    """Save the run under a name (it stops expiring), drop the name (it expires again), or
    share it with the project's members; a field left out stays as it is."""
    run = await _run_for(session, context, run_id)
    _may_change(run, context)
    changed = body.model_dump(exclude_unset=True)
    if "name" in changed:
        run.name = body.name
        if body.name:
            run.expires_at = None
        elif run.finished_at is not None:
            run.expires_at = run.finished_at + timedelta(
                days=get_settings().analysis_retention_days
            )
    if body.shared is not None:
        run.shared = body.shared
    await record_audit(
        session,
        user=context.user,
        action="analysis.updated",
        object_type="analysis_run",
        object_id=str(run.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return await _read(session, run)


@router.post("/projects/{project_id}/analyses/{run_id}/cancel", response_model=AnalysisRunRead)
async def cancel_run(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
) -> AnalysisRun:
    """A queued run is cancelled at once; a running one stops at its next step."""
    run = await _run_for(session, context, run_id)
    _may_change(run, context)
    if run.status == AnalysisStatus.QUEUED:
        run.status = AnalysisStatus.CANCELLED
        run.error_code = "CANCELLED"
        run.finished_at = utc_now()
    elif run.status == AnalysisStatus.RUNNING:
        run.cancel_requested = True
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The run is {run.status}")
    await session.commit()
    return run


@router.delete("/projects/{project_id}/analyses/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    run = await _run_for(session, context, run_id)
    _may_change(run, context)
    await record_audit(
        session,
        user=context.user,
        action="analysis.deleted",
        object_type="analysis_run",
        object_id=str(run.id),
        project_id=context.project.id,
        details={"module": run.module},
    )
    await remove_report(run)
    await session.delete(run)
    await session.commit()


@router.get("/projects/{project_id}/analyses/{run_id}/geometries")
async def run_geometries(
    run_id: uuid.UUID,
    kind: str | None = None,
    subject_id: uuid.UUID | None = None,
    limit: int = Query(MAX_GEOMETRIES_PER_CALL, ge=1, le=MAX_GEOMETRIES_PER_CALL),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The run's result geometries as a GeoJSON feature collection, by kind and subject."""
    run = await _run_for(session, context, run_id)
    statement = select(AnalysisGeometry).where(AnalysisGeometry.run_id == run.id)
    if kind:
        statement = statement.where(AnalysisGeometry.kind == kind)
    if subject_id:
        statement = statement.where(AnalysisGeometry.subject_id == subject_id)
    rows = list(await session.scalars(statement.order_by(AnalysisGeometry.id).limit(limit)))
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row.id,
                "geometry": geom_to_geojson(row.geom),
                "properties": {
                    "kind": row.kind,
                    "subject_id": str(row.subject_id) if row.subject_id else None,
                    "label": row.label,
                    "level": row.level,
                    "area_m2": row.area_m2,
                    **row.properties,
                },
            }
            for row in rows
        ],
    }


@router.get("/projects/{project_id}/analyses/{run_id}/export")
async def export_run(
    run_id: uuid.UUID,
    what: str = Query("document", pattern="^(document|geometries|[a-z_]+)$"),
    format: str = Query("json", pattern="^(json|geojson|csv)$"),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The result to take elsewhere: the document as JSON, the geometries as GeoJSON, or one
    of the document's tables (by its key) as CSV."""
    run = await _run_for(session, context, run_id)
    if run.result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The run has no result yet")
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    name = f"{run.module}-{str(run.id)[:8]}-{stamp}"
    if what == "document":
        body = json.dumps(run.result, indent=2).encode()
        return Response(body, media_type="application/json", headers=_attachment(f"{name}.json"))
    if what == "geometries":
        collection = await run_geometries(
            run_id, None, None, MAX_GEOMETRIES_PER_CALL, context, session
        )
        body = json.dumps(collection).encode()
        return Response(
            body, media_type="application/geo+json", headers=_attachment(f"{name}.geojson")
        )
    table = next((t for t in run.result.get("tables", []) if t.get("key") == what), None)
    if table is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"The result has no table {what}")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(table["columns"])
    for row in table["rows"]:
        writer.writerow(row)
    return Response(
        out.getvalue().encode(),
        media_type="text/csv; charset=utf-8",
        headers=_attachment(f"{name}-{what}.csv"),
    )


@router.post("/projects/{project_id}/analyses/{run_id}/report", response_model=AnalysisRunRead)
async def make_report(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.EXPORTS_CREATE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> AnalysisRunRead:
    """Ask for the run's PDF report (decision D211): the export service renders it and keeps it
    with the run; the run read says when it is ready. 409 while one is being made."""
    run = await _run_for(session, context, run_id)
    if run.result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The run has no result yet")
    if run.report_status in (ReportStatus.QUEUED, ReportStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, "The report is being made")
    queue_report(run)
    await record_audit(
        session,
        user=context.user,
        action="analysis.report_requested",
        object_type="analysis_run",
        object_id=str(run.id),
        project_id=context.project.id,
        details={"module": run.module},
    )
    await session.commit()
    await publish_report(bus, run)
    return await _read(session, run)


@router.get("/projects/{project_id}/analyses/{run_id}/report")
async def download_report(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """The run's PDF report, once it is ready (decision D211)."""
    run = await _run_for(session, context, run_id)
    if run.report_status != ReportStatus.READY or not run.report_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The run has no report yet")
    stamp = (run.report_at or datetime.now(UTC)).strftime("%Y%m%d")
    stem = (run.name or f"{run.module}-{str(run.id)[:8]}").replace("/", "-")
    return StreamingResponse(
        stream_object(get_settings().minio_bucket_exports, run.report_key),
        media_type="application/pdf",
        headers=_attachment(f"{stem}-{stamp}.pdf"),
    )


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
