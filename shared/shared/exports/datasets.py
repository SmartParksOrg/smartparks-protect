"""Row sources for exports: one streamed query per dataset, rows as dicts in column order.

Rows are read with a server-side cursor (`yield_per`), so a 10 million row export walks the
table without holding it. Times are written in the requested zone; `time_utc` travels with
every row for writers that need UTC (GPX).
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analytics import (
    AnalyticsError,
    Layout,
    Resolution,
    aggregate_statement,
    choose_resolution,
    whole_range,
)
from shared.enums import ExportDataset, ExportFormat
from shared.exports import ExportParameters
from shared.models import (
    Device,
    DeviceProjectAssignment,
    Entity,
    Measurement,
    Metric,
    Position,
    SourceEvent,
)

YIELD_PER = 2_000


@dataclass
class Lookups:
    """Names for identifiers, loaded once per export. Bounded by the registries, not the data."""

    entities: dict[uuid.UUID, str] = field(default_factory=dict)
    devices: dict[uuid.UUID, str] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)


async def load_lookups(session: AsyncSession, project_id: uuid.UUID) -> Lookups:
    entities = await session.execute(
        select(Entity.id, Entity.name).where(Entity.project_id == project_id)
    )
    devices = await session.execute(select(Device.id, Device.name))
    metrics = (await session.scalars(select(Metric))).all()
    return Lookups(
        entities={row[0]: row[1] for row in entities.all()},
        devices={row[0]: row[1] for row in devices.all()},
        metrics={m.key: m for m in metrics},
    )


def _iso(value: datetime | None, params: ExportParameters) -> str | None:
    return None if value is None else value.astimezone(params.zone()).isoformat()


def _utc(value: datetime | None) -> str | None:
    return None if value is None else value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def columns(params: ExportParameters, lookups: Lookups) -> list[str]:
    """The header, in order. `include_names` adds the human readable columns."""
    names = params.include_names
    if params.dataset is ExportDataset.POSITIONS:
        cols = ["time", "entity_id"]
        cols += ["entity_name"] if names else []
        cols += ["device_id"]
        cols += ["device_name"] if names else []
        cols += [
            "latitude",
            "longitude",
            "altitude_m",
            "speed_mps",
            "heading_deg",
            "accuracy_m",
            "satellites",
            "record_type",
            "data_source_id",
            "source_event_id",
            "trace_id",
            "attributes",
        ]
        if params.format is ExportFormat.GPX:
            cols += ["track_key", "track_name"]
        return cols
    if params.dataset is ExportDataset.MEASUREMENTS:
        cols = ["time", "entity_id"]
        cols += ["entity_name"] if names else []
        cols += ["device_id"]
        cols += ["device_name"] if names else []
        cols += ["metric_key"]
        cols += ["metric_label", "unit"] if names else []
        cols += ["value", "data_source_id", "source_event_id", "trace_id"]
        return cols
    if params.dataset is ExportDataset.SOURCE_EVENTS:
        cols = ["ingested_at", "network_received_at", "device_id"]
        cols += ["device_name"] if names else []
        cols += [
            "external_id",
            "event_type",
            "acquisition_channel",
            "ingestion_method",
            "processing_status",
            "error_code",
            "data_source_id",
            "payload",
            "payload_object_key",
            "provider_metadata",
            "trace_id",
        ]
        return cols
    # aggregates
    owner = "entity" if params.group_by.value == "entity" else "device"
    if params.layout is Layout.WIDE:
        cols = ["time"]
        for series_key in _wide_series(params, lookups):
            cols += [f"{series_key}|{a.value}" for a in params.aggregates]
        return cols
    cols = ["time", "metric_key"]
    cols += ["metric_label", "unit"] if names else []
    cols += [f"{owner}_id"]
    cols += [f"{owner}_name"] if names else []
    cols += [a.value for a in params.aggregates]
    return cols


def _wide_series(params: ExportParameters, lookups: Lookups) -> list[str]:
    """Series keys of a wide aggregate export are known up front only when the owners are
    listed; otherwise the header is built after the query (see `stream_rows`)."""
    owners = params.entity_ids if params.group_by.value == "entity" else params.device_ids
    return [f"{metric}|{owner}" for metric in params.metric_keys for owner in owners]


def _base_conditions(model: Any, project_id: uuid.UUID, params: ExportParameters) -> list[Any]:
    conditions = [
        model.project_id == project_id,
        model.time >= params.time_from,
        model.time < params.time_to,
    ]
    if params.entity_ids:
        conditions.append(model.entity_id.in_(params.entity_ids))
    if params.device_ids:
        conditions.append(model.device_id.in_(params.device_ids))
    if params.data_source_id is not None:
        conditions.append(model.data_source_id == params.data_source_id)
    return conditions


def _source_event_conditions(project_id: uuid.UUID, params: ExportParameters) -> list[Any]:
    project_devices = select(DeviceProjectAssignment.device_id).where(
        DeviceProjectAssignment.project_id == project_id
    )
    conditions = [
        SourceEvent.device_id.in_(project_devices),
        SourceEvent.ingested_at >= params.time_from,
        SourceEvent.ingested_at < params.time_to,
    ]
    if params.device_ids:
        conditions.append(SourceEvent.device_id.in_(params.device_ids))
    if params.data_source_id is not None:
        conditions.append(SourceEvent.data_source_id == params.data_source_id)
    return conditions


def count_statement(project_id: uuid.UUID, params: ExportParameters) -> Select[Any] | None:
    """Row count of a normalized or raw export, for the direct export bound. Aggregates are
    bounded by construction and return None."""
    if params.dataset is ExportDataset.POSITIONS:
        return (
            select(func.count())
            .select_from(Position)
            .where(*_base_conditions(Position, project_id, params))
        )
    if params.dataset is ExportDataset.MEASUREMENTS:
        conditions = _base_conditions(Measurement, project_id, params)
        if params.metric_keys:
            conditions.append(Measurement.metric_key.in_(params.metric_keys))
        return select(func.count()).select_from(Measurement).where(*conditions)
    if params.dataset is ExportDataset.SOURCE_EVENTS:
        return (
            select(func.count())
            .select_from(SourceEvent)
            .where(*_source_event_conditions(project_id, params))
        )
    return None


def resolution_for(params: ExportParameters) -> Resolution:
    if params.bucket == "all":
        return whole_range(params.time_from, params.time_to)
    return choose_resolution(params.time_from, params.time_to, params.bucket)


async def stream_rows(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters, lookups: Lookups
) -> AsyncIterator[dict[str, Any]]:
    if params.dataset is ExportDataset.POSITIONS:
        async for row in _positions(session, project_id, params, lookups):
            yield row
    elif params.dataset is ExportDataset.MEASUREMENTS:
        async for row in _measurements(session, project_id, params, lookups):
            yield row
    elif params.dataset is ExportDataset.SOURCE_EVENTS:
        async for row in _source_events(session, project_id, params, lookups):
            yield row
    else:
        async for row in _aggregates(session, project_id, params, lookups):
            yield row


async def _positions(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters, lookups: Lookups
) -> AsyncIterator[dict[str, Any]]:
    # Plain columns, not ORM objects: a streamed export must not grow the session's identity map.
    statement = select(
        Position.time,
        Position.entity_id,
        Position.device_id,
        func.ST_Y(Position.geom).label("lat"),
        func.ST_X(Position.geom).label("lon"),
        Position.altitude_m,
        Position.speed_mps,
        Position.heading_deg,
        Position.accuracy_m,
        Position.satellites,
        Position.record_type,
        Position.data_source_id,
        Position.source_event_id,
        Position.trace_id,
        Position.attributes,
    ).where(*_base_conditions(Position, project_id, params))
    if params.format is ExportFormat.GPX:
        # one track per entity (device when unassigned), points in order
        statement = statement.order_by(Position.entity_id, Position.device_id, Position.time)
    else:
        statement = statement.order_by(Position.time, Position.id)
    result = await session.stream(statement.execution_options(yield_per=YIELD_PER))
    async for row in result:
        track_id = row.entity_id or row.device_id
        yield {
            "time": _iso(row.time, params),
            "time_utc": _utc(row.time),
            "entity_id": row.entity_id,
            "entity_name": lookups.entities.get(row.entity_id) if row.entity_id else None,
            "device_id": row.device_id,
            "device_name": lookups.devices.get(row.device_id),
            "latitude": row.lat,
            "longitude": row.lon,
            "altitude_m": row.altitude_m,
            "speed_mps": row.speed_mps,
            "heading_deg": row.heading_deg,
            "accuracy_m": row.accuracy_m,
            "satellites": row.satellites,
            "record_type": row.record_type,
            "data_source_id": row.data_source_id,
            "source_event_id": row.source_event_id,
            "trace_id": row.trace_id,
            "attributes": row.attributes,
            "track_key": str(track_id),
            "track_name": (
                lookups.entities.get(row.entity_id)
                if row.entity_id
                else lookups.devices.get(row.device_id)
            ),
        }


def _value(num: float | None, boolean: bool | None, text: str | None, json_value: Any) -> Any:
    if num is not None:
        return num
    if boolean is not None:
        return boolean
    if text is not None:
        return text
    return json_value


async def _measurements(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters, lookups: Lookups
) -> AsyncIterator[dict[str, Any]]:
    conditions = _base_conditions(Measurement, project_id, params)
    if params.metric_keys:
        conditions.append(Measurement.metric_key.in_(params.metric_keys))
    statement = (
        select(
            Measurement.time,
            Measurement.entity_id,
            Measurement.device_id,
            Measurement.metric_key,
            Measurement.value_num,
            Measurement.value_bool,
            Measurement.value_text,
            Measurement.value_json,
            Measurement.data_source_id,
            Measurement.source_event_id,
            Measurement.trace_id,
        )
        .where(*conditions)
        .order_by(Measurement.time, Measurement.id)
    )
    result = await session.stream(statement.execution_options(yield_per=YIELD_PER))
    async for m in result:
        metric = lookups.metrics.get(m.metric_key)
        yield {
            "time": _iso(m.time, params),
            "time_utc": _utc(m.time),
            "entity_id": m.entity_id,
            "entity_name": lookups.entities.get(m.entity_id) if m.entity_id else None,
            "device_id": m.device_id,
            "device_name": lookups.devices.get(m.device_id),
            "metric_key": m.metric_key,
            "metric_label": metric.label if metric else None,
            "unit": metric.unit if metric else None,
            "value": _value(m.value_num, m.value_bool, m.value_text, m.value_json),
            "data_source_id": m.data_source_id,
            "source_event_id": m.source_event_id,
            "trace_id": m.trace_id,
        }


async def _source_events(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters, lookups: Lookups
) -> AsyncIterator[dict[str, Any]]:
    statement = (
        select(
            SourceEvent.ingested_at,
            SourceEvent.network_received_at,
            SourceEvent.device_id,
            SourceEvent.external_id,
            SourceEvent.event_type,
            SourceEvent.acquisition_channel,
            SourceEvent.ingestion_method,
            SourceEvent.processing_status,
            SourceEvent.error_code,
            SourceEvent.data_source_id,
            SourceEvent.payload,
            SourceEvent.payload_object_key,
            SourceEvent.provider_metadata,
            SourceEvent.trace_id,
        )
        .where(*_source_event_conditions(project_id, params))
        .order_by(SourceEvent.ingested_at, SourceEvent.id)
    )
    result = await session.stream(statement.execution_options(yield_per=YIELD_PER))
    async for e in result:
        yield {
            "ingested_at": _iso(e.ingested_at, params),
            "time_utc": _utc(e.ingested_at),
            "network_received_at": _iso(e.network_received_at, params),
            "device_id": e.device_id,
            "device_name": lookups.devices.get(e.device_id) if e.device_id else None,
            "external_id": e.external_id,
            "event_type": e.event_type,
            "acquisition_channel": e.acquisition_channel,
            "ingestion_method": e.ingestion_method,
            "processing_status": e.processing_status,
            "error_code": e.error_code,
            "data_source_id": e.data_source_id,
            "payload": e.payload,
            "payload_object_key": e.payload_object_key,
            "provider_metadata": e.provider_metadata,
            "trace_id": e.trace_id,
        }


async def _aggregates(
    session: AsyncSession, project_id: uuid.UUID, params: ExportParameters, lookups: Lookups
) -> AsyncIterator[dict[str, Any]]:
    try:
        resolution = resolution_for(params)
    except AnalyticsError as error:
        raise ValueError(str(error)) from None
    statement = aggregate_statement(
        project_id=project_id,
        metrics=params.metric_keys,
        entity_ids=params.entity_ids,
        device_ids=params.device_ids,
        data_source_id=params.data_source_id,
        time_from=params.time_from,
        time_to=params.time_to,
        resolution=resolution,
        aggregates=params.aggregates,
        group_by=params.group_by,
    )
    by_entity = params.group_by.value == "entity"
    owner = "entity" if by_entity else "device"
    names = lookups.entities if by_entity else lookups.devices
    result = await session.stream(statement.execution_options(yield_per=YIELD_PER))
    if params.layout is Layout.LONG:
        async for row in result:
            metric = lookups.metrics.get(row.metric_key)
            yield {
                "time": _iso(row.bucket, params),
                "time_utc": _utc(row.bucket),
                "metric_key": row.metric_key,
                "metric_label": metric.label if metric else None,
                "unit": metric.unit if metric else None,
                f"{owner}_id": row.series_key,
                f"{owner}_name": names.get(row.series_key) if row.series_key else None,
                **{a.value: getattr(row, a.value) for a in params.aggregates},
            }
        return
    # wide: one row per bucket. The result is bounded (MAX_SERIES x MAX_BUCKETS), so it can be
    # pivoted in memory; column keys follow the Data Explorer (`metric|owner|aggregate`).
    buckets: dict[datetime, dict[str, Any]] = {}
    async for row in result:
        cells = buckets.setdefault(row.bucket, {})
        for a in params.aggregates:
            cells[f"{row.metric_key}|{row.series_key}|{a.value}"] = getattr(row, a.value)
    for bucket in sorted(buckets):
        yield {"time": _iso(bucket, params), "time_utc": _utc(bucket), **buckets[bucket]}


def metadata(params: ExportParameters, lookups: Lookups, version: str) -> dict[str, Any]:
    """Recorded with the job and written into JSON exports: enough to reproduce the export and
    to read the values correctly (architecture 14, 28.13)."""
    used = (
        params.metric_keys
        if params.metric_keys
        else sorted(lookups.metrics)
        if params.dataset is ExportDataset.MEASUREMENTS
        else []
    )
    return {
        "generator": f"Smart Parks Protect {version}",
        "parameters": json.loads(params.model_dump_json()),
        "timezone": params.timezone,
        "metrics": {
            key: {
                "label": lookups.metrics[key].label,
                "unit": lookups.metrics[key].unit,
                "value_type": lookups.metrics[key].value_type,
            }
            for key in used
            if key in lookups.metrics
        },
    }
