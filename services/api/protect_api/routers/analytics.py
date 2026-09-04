"""Data Explorer backend: bucketed aggregates, drill-down rows and the metrics with data.

Every endpoint is bounded (architecture 13.10): a series has at most MAX_BUCKETS points, a
request at most MAX_SERIES series, drill-down rows are paginated.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.common import ORMModel
from shared.analytics import (
    BUCKETS,
    DEFAULT_AGGREGATES,
    MAX_SERIES,
    Aggregate,
    AnalyticsError,
    GroupBy,
    Layout,
    aggregate_statement,
    choose_resolution,
    whole_range,
)
from shared.curation.effective import effective_time, in_window, visible
from shared.database import get_session
from shared.enums import ValueType
from shared.models import Entity, Measurement, Metric, SavedView
from shared.permissions import Permission
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/projects/{project_id}/analytics", tags=["analytics"])

DEFAULT_RANGE = timedelta(hours=24)
DEFAULT_METRICS_RANGE = timedelta(days=30)


class SeriesPoint(BaseModel):
    time: datetime
    values: dict[str, float | None]


class Series(BaseModel):
    metric_key: str
    unit: str | None
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    points: list[SeriesPoint]


class SeriesResponse(BaseModel):
    time_from: datetime
    time_to: datetime
    bucket: str
    bucket_seconds: int
    automatic_bucket: bool
    aggregates: list[Aggregate]
    group_by: GroupBy
    layout: Layout
    series: list[Series] | None = None
    columns: list[str] | None = None
    rows: list[dict[str, Any]] | list[list[Any]] | None = None


class MeasurementRow(BaseModel):
    id: int
    time: datetime
    original_time: datetime = Field(description="The record's key; equals time unless curated")
    original_value: float | None = Field(default=None, description="Set when the value is curated")
    valid: bool = True
    curated_fields: list[str] = Field(default_factory=list)
    curation_version: int = 1
    metric_key: str
    value: float | bool | str | dict[str, Any] | None
    device_id: uuid.UUID
    entity_id: uuid.UUID | None
    data_source_id: uuid.UUID | None
    source_event_id: int | None
    source_event_ingested_at: datetime | None
    trace_id: uuid.UUID | None


class MetricWithData(BaseModel):
    key: str
    label: str
    unit: str | None
    value_type: str
    category: str
    count: int
    first_time: datetime
    last_time: datetime


def _window(
    time_from: datetime | None, time_to: datetime | None, default: timedelta
) -> tuple[datetime, datetime]:
    to = require_aware(time_to) if time_to else utc_now()
    frm = require_aware(time_from) if time_from else to - default
    if frm >= to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`to` must be after `from`")
    return frm, to


async def _aggregatable_metrics(session: AsyncSession, keys: list[str]) -> dict[str, Metric]:
    rows = (await session.scalars(select(Metric).where(Metric.key.in_(keys)))).all()
    found = {m.key: m for m in rows}
    missing = sorted(set(keys) - set(found))
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown metrics: {', '.join(missing)}")
    bad = sorted(
        k for k, m in found.items() if m.value_type not in (ValueType.NUMERIC, ValueType.BOOLEAN)
    )
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Only numeric and boolean metrics can be aggregated, not: {', '.join(bad)}",
        )
    return found


async def _bound_series(
    session: AsyncSession,
    context: ProjectContext,
    metrics: list[str],
    entity_ids: list[uuid.UUID],
    device_ids: list[uuid.UUID],
    group_by: GroupBy,
) -> None:
    """Refuse a request that could return more than MAX_SERIES series, without touching the
    hypertable: the number of groups is known from the filters or from the entity registry."""
    if group_by is GroupBy.ENTITY and entity_ids:
        groups = len(entity_ids)
    elif group_by is GroupBy.DEVICE and device_ids:
        groups = len(device_ids)
    elif group_by is GroupBy.ENTITY:
        groups = int(
            await session.scalar(
                select(func.count())
                .select_from(Entity)
                .where(Entity.project_id == context.project.id)
            )
            or 0
        )
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "group_by=device needs a device_id filter",
        )
    if len(metrics) * groups > MAX_SERIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{len(metrics)} metrics times {groups} {group_by.value}s exceeds {MAX_SERIES} series; "
            f"select fewer metrics or {group_by.value}s",
        )


@router.get("/series", response_model=SeriesResponse)
async def series(
    metric: list[str] = Query(min_length=1, max_length=MAX_SERIES),
    entity_id: list[uuid.UUID] = Query(default_factory=list, max_length=MAX_SERIES),
    device_id: list[uuid.UUID] = Query(default_factory=list, max_length=MAX_SERIES),
    data_source_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    bucket: str | None = Query(
        None, description=f"One of {', '.join(BUCKETS)} or `all`; default automatic"
    ),
    agg: list[Aggregate] = Query(default_factory=lambda: list(DEFAULT_AGGREGATES)),
    group_by: GroupBy = GroupBy.ENTITY,
    layout: Layout = Layout.SERIES,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> SeriesResponse:
    """Bucketed aggregates of measurements attributed to the project. One series per metric and
    entity (or device). Boolean metrics aggregate as 0 and 1, so `mean` is the fraction true."""
    frm, to = _window(time_from, time_to, DEFAULT_RANGE)
    metrics = await _aggregatable_metrics(session, metric)
    await _bound_series(session, context, metric, entity_id, device_id, group_by)
    aggregates = list(dict.fromkeys(agg))
    try:
        resolution = whole_range(frm, to) if bucket == "all" else choose_resolution(frm, to, bucket)
    except AnalyticsError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    statement = aggregate_statement(
        project_id=context.project.id,
        metrics=metric,
        entity_ids=entity_id,
        device_ids=device_id,
        data_source_id=data_source_id,
        time_from=frm,
        time_to=to,
        resolution=resolution,
        aggregates=aggregates,
        group_by=group_by,
    )
    rows = (await session.execute(statement)).all()

    series_map: dict[tuple[str, uuid.UUID | None], Series] = {}
    for row in rows:
        key = (row.metric_key, row.series_key)
        if key not in series_map:
            series_map[key] = Series(
                metric_key=row.metric_key,
                unit=metrics[row.metric_key].unit,
                entity_id=row.series_key if group_by is GroupBy.ENTITY else None,
                device_id=row.series_key if group_by is GroupBy.DEVICE else None,
                points=[],
            )
        series_map[key].points.append(
            SeriesPoint(
                time=row.bucket,
                values={
                    a.value: (
                        None if getattr(row, a.value) is None else float(getattr(row, a.value))
                    )
                    for a in aggregates
                },
            )
        )
    result = SeriesResponse(
        time_from=frm,
        time_to=to,
        bucket=resolution.key,
        bucket_seconds=resolution.seconds,
        automatic_bucket=resolution.automatic,
        aggregates=aggregates,
        group_by=group_by,
        layout=layout,
    )
    all_series = list(series_map.values())
    if layout is Layout.SERIES:
        result.series = all_series
    elif layout is Layout.LONG:
        result.rows = [
            {
                "time": p.time,
                "metric_key": s.metric_key,
                "entity_id": s.entity_id,
                "device_id": s.device_id,
                **p.values,
            }
            for s in all_series
            for p in s.points
        ]
    else:
        result.columns, result.rows = _wide(all_series, aggregates)
    return result


def _wide(
    all_series: list[Series], aggregates: list[Aggregate]
) -> tuple[list[str], list[list[Any]]]:
    """One row per bucket, one column per series and aggregate, `time` first."""
    columns = ["time"]
    for s in all_series:
        owner = s.entity_id or s.device_id
        columns.extend(f"{s.metric_key}|{owner}|{a.value}" for a in aggregates)
    by_time: dict[datetime, list[Any]] = {}
    for index, s in enumerate(all_series):
        offset = 1 + index * len(aggregates)
        for p in s.points:
            row = by_time.setdefault(p.time, [p.time] + [None] * (len(columns) - 1))
            for j, a in enumerate(aggregates):
                row[offset + j] = p.values[a.value]
    return columns, [by_time[t] for t in sorted(by_time)]


@router.get("/rows", response_model=PageResponse[MeasurementRow])
async def rows(
    metric: str,
    entity_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    data_source_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    include_invalid: bool = Query(False, description="Also rows marked invalid by curation"),
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[MeasurementRow]:
    """Normalized measurement rows behind a bucket: the drill-down from an aggregate. Each row
    carries its source event and trace, so the next step down is the source event detail.
    Values and times are the effective ones; curated rows say so (architecture 28.12)."""
    frm, to = _window(time_from, time_to, DEFAULT_RANGE)
    statement = select(Measurement).where(
        Measurement.project_id == context.project.id,
        Measurement.metric_key == metric,
        in_window(Measurement, frm, to),
    )
    if not include_invalid:
        statement = statement.where(visible(Measurement))
    if entity_id is not None:
        statement = statement.where(Measurement.entity_id == entity_id)
    if device_id is not None:
        statement = statement.where(Measurement.device_id == device_id)
    if data_source_id is not None:
        statement = statement.where(Measurement.data_source_id == data_source_id)
    items, next_cursor = await paginate(session, Measurement.id, statement, page)
    return PageResponse(items=[_row(m) for m in items], next_cursor=next_cursor)


def _row(m: Measurement) -> MeasurementRow:
    value: float | bool | str | dict[str, Any] | None
    if m.curated_value_num is not None:
        value = m.curated_value_num
    elif m.value_num is not None:
        value = m.value_num
    elif m.value_bool is not None:
        value = m.value_bool
    elif m.value_text is not None:
        value = m.value_text
    else:
        value = m.value_json
    return MeasurementRow(
        id=m.id,
        time=m.curated_time or m.time,
        original_time=m.time,
        original_value=m.value_num if m.curated_value_num is not None else None,
        valid=m.valid,
        curated_fields=list(m.curated_fields or []),
        curation_version=m.curation_version,
        metric_key=m.metric_key,
        value=value,
        device_id=m.device_id,
        entity_id=m.entity_id,
        data_source_id=m.data_source_id,
        source_event_id=m.source_event_id,
        source_event_ingested_at=m.source_event_ingested_at,
        trace_id=m.trace_id,
    )


@router.get("/metrics", response_model=list[MetricWithData])
async def metrics_with_data(
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[MetricWithData]:
    """Metrics that have measurements in this project within the range (default 30 days), for
    the filter builder."""
    frm, to = _window(time_from, time_to, DEFAULT_METRICS_RANGE)
    counts = (
        select(
            Measurement.metric_key,
            func.count().label("count"),
            func.min(effective_time(Measurement)).label("first_time"),
            func.max(effective_time(Measurement)).label("last_time"),
        )
        .where(
            Measurement.project_id == context.project.id,
            in_window(Measurement, frm, to),
            visible(Measurement),
        )
        .group_by(Measurement.metric_key)
        .subquery()
    )
    result = await session.execute(
        select(Metric, counts.c.count, counts.c.first_time, counts.c.last_time)
        .join(counts, counts.c.metric_key == Metric.key)
        .order_by(Metric.category, Metric.key)
    )
    return [
        MetricWithData(
            key=m.key,
            label=m.label,
            unit=m.unit,
            value_type=m.value_type,
            category=m.category,
            count=count,
            first_time=first_time,
            last_time=last_time,
        )
        for m, count, first_time, last_time in result.all()
    ]


class SavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    view: dict[str, Any]
    schema_version: int = Field(default=1, ge=1)


class SavedViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    view: dict[str, Any] | None = None
    schema_version: int | None = Field(default=None, ge=1)


class SavedViewRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID | None
    name: str
    view: dict[str, Any]
    schema_version: int
    created_at: datetime
    updated_at: datetime


@router.get("/saved-views", response_model=PageResponse[SavedViewRead])
async def list_saved_views(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[SavedViewRead]:
    """Data Explorer configurations shared by the project (decision D42)."""
    rows, next_cursor = await paginate(
        session,
        SavedView.id,
        select(SavedView).where(SavedView.project_id == context.project.id),
        page,
    )
    return PageResponse(
        items=[SavedViewRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post("/saved-views", response_model=SavedViewRead, status_code=status.HTTP_201_CREATED)
async def create_saved_view(
    body: SavedViewCreate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> SavedView:
    """Any member can save a view; names are unique per project."""
    view = SavedView(project_id=context.project.id, created_by=context.user.id, **body.model_dump())
    session.add(view)
    await flush_or_409(session, "Saved view")
    await session.commit()
    return view


async def _own_or_admin(
    session: AsyncSession, context: ProjectContext, view_id: uuid.UUID
) -> SavedView:
    """The creator or someone with project:write may change or delete a view."""
    view = await get_or_404(session, SavedView, view_id, "Saved view")
    if view.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved view not found")
    if view.created_by != context.user.id and Permission.PROJECT_WRITE not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the creator or a project admin")
    return view


@router.patch("/saved-views/{view_id}", response_model=SavedViewRead)
async def update_saved_view(
    view_id: uuid.UUID,
    body: SavedViewUpdate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> SavedView:
    view = await _own_or_admin(session, context, view_id)
    apply_patch(view, body)
    await flush_or_409(session, "Saved view")
    await session.commit()
    return view


@router.delete("/saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_view(
    view_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> None:
    view = await _own_or_admin(session, context, view_id)
    await session.delete(view)
    await session.commit()
