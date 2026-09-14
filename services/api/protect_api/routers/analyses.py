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
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.crud import geom_to_geojson, get_or_404
from protect_api.deps import ProjectContext, require_permission
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
    MAX_QUEUED_PER_PROJECT,
    MAX_SUBJECTS_MOVEMENT,
    RESULT_RETENTION_DAYS,
)
from shared.analysis.parameters import CommonParameters
from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.curation.effective import device_fix, effective_time, visible
from shared.database import get_session
from shared.enums import AnalysisStatus
from shared.models import AnalysisGeometry, AnalysisRun, Entity, EntityType, Position, User
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(tags=["analyses"])
MAX_GEOMETRIES_PER_CALL = 2_000
SUBJECT_LIMITS = {"movement": MAX_SUBJECTS_MOVEMENT, "grazing": MAX_ANIMALS_GRAZING}


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


async def _resolve_subjects(
    session: AsyncSession, context: ProjectContext, params: CommonParameters, limit: int
) -> list[uuid.UUID]:
    """The subjects as entity ids inside the project and the caller's scope: the given ids
    (an id outside the scope is refused), or a group with its subgroups, or a type."""
    project_id = context.project.id
    if params.entity_ids:
        found = set(
            await session.scalars(
                select(Entity.id).where(
                    Entity.project_id == project_id, Entity.id.in_(params.entity_ids)
                )
            )
        )
        missing = [str(i) for i in params.entity_ids if i not in found]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown entity {missing[0]}"
            )
        outside = [i for i in params.entity_ids if not context.visibility.entity_visible(i)]
        if outside:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "An entity is outside what you may see"
            )
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
    session: AsyncSession, entity_ids: list[uuid.UUID], params: CommonParameters
) -> int:
    """The device fixes the run would read over its subjects and periods, one bounded count."""
    windows = [(params.time_from, params.time_to)]
    if params.comparison:
        windows.append((params.comparison.time_from, params.comparison.time_to))
    total = 0
    for time_from, time_to in windows:
        count = await session.scalar(
            select(func.count())
            .select_from(Position)
            .where(
                Position.entity_id.in_(entity_ids),
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
    subjects = await _resolve_subjects(session, context, params, limits["subjects"])
    fixes = await _count_fixes(session, subjects, params)
    days = (params.time_to - params.time_from).total_seconds() / 86_400
    reasons: list[str] = []
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
    """A run is for the reader when every subject is inside the reader's scope."""
    if not context.visibility.limited:
        return True
    ids = run.parameters.get("entity_ids") or []
    return all(context.visibility.entity_visible(uuid.UUID(str(i))) for i in ids)


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
    stored = params.model_dump(mode="json")
    stored["entity_ids"] = [str(i) for i in subjects]
    stored.pop("group_id", None)
    stored.pop("entity_type_id", None)
    module = _module(body.module, context)
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
) -> AnalysisRun:
    return await _run_for(session, context, run_id)


@router.patch("/projects/{project_id}/analyses/{run_id}", response_model=AnalysisRunRead)
async def update_run(
    run_id: uuid.UUID,
    body: AnalysisRunUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
) -> AnalysisRun:
    """Keep the run under a name (it stops expiring), or drop the name (it expires again)."""
    run = await _run_for(session, context, run_id)
    _may_change(run, context)
    run.name = body.name
    if body.name:
        run.expires_at = None
    elif run.finished_at is not None:
        run.expires_at = run.finished_at + timedelta(days=RESULT_RETENTION_DAYS)
    await record_audit(
        session,
        user=context.user,
        action="analysis.updated",
        object_type="analysis_run",
        object_id=str(run.id),
        project_id=context.project.id,
        details={"name": body.name},
    )
    await session.commit()
    return run


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


@router.post(
    "/projects/{project_id}/analyses/{run_id}/rerun",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def rerun(
    run_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ANALYSIS_RUN)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> AnalysisRun:
    """A new run with the same parameters, linked to this one."""
    source = await _run_for(session, context, run_id)
    module = _module(source.module, context)
    fresh = AnalysisRun(
        project_id=context.project.id,
        module=source.module,
        parameters=source.parameters,
        method_version=module.version,
        created_by_user_id=context.user.id,
        source_run_id=source.id,
    )
    session.add(fresh)
    await session.flush()
    await record_audit(
        session,
        user=context.user,
        action="analysis.created",
        object_type="analysis_run",
        object_id=str(fresh.id),
        project_id=context.project.id,
        details={"module": source.module, "source_run_id": str(source.id)},
    )
    await session.commit()
    await bus.publish(Topic.ANALYSIS_REQUESTED, {"run_id": str(fresh.id)})
    return fresh


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


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}
