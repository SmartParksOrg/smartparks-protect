"""Server-side aggregation for the Data Explorer and exports (architecture 12, 13.5, D41).

A series is one metric for one entity or device. Values are bucketed with TimescaleDB
`time_bucket`; the bucket is chosen from a fixed ladder so a series never returns more than
`MAX_BUCKETS` points unless the caller sets the bucket explicitly (still bounded). The API and
the export worker build the same statement here.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, Integer, Interval, Select, cast, func, literal, select
from sqlalchemy.sql import ColumnElement

from shared.models import Measurement


class AnalyticsError(ValueError):
    """A request the API answers with 422; the message is for the user."""


MAX_BUCKETS = 5_000
MAX_SERIES = 20
MAX_RAW_ROWS = 5_000

# Ladder from decision D41. Keys are what the API accepts as `bucket`.
BUCKETS: dict[str, timedelta] = {
    "1s": timedelta(seconds=1),
    "10s": timedelta(seconds=10),
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
}


class Aggregate(StrEnum):
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    MEDIAN = "median"
    SUM = "sum"
    COUNT = "count"
    FIRST = "first"
    LAST = "last"


DEFAULT_AGGREGATES = (Aggregate.MEAN, Aggregate.MIN, Aggregate.MAX, Aggregate.COUNT)


class Layout(StrEnum):
    SERIES = "series"
    LONG = "long"
    WIDE = "wide"


class GroupBy(StrEnum):
    ENTITY = "entity"
    DEVICE = "device"


@dataclass(frozen=True, slots=True)
class Resolution:
    key: str
    width: timedelta
    automatic: bool

    @property
    def seconds(self) -> int:
        return int(self.width.total_seconds())


def choose_resolution(time_from: datetime, time_to: datetime, bucket: str | None) -> Resolution:
    """Smallest ladder bucket that keeps one series at or under MAX_BUCKETS points. An explicit
    bucket is accepted only if it respects the same bound, so a request can never explode."""
    span = time_to - time_from
    if span <= timedelta(0):
        raise AnalyticsError("`to` must be after `from`")
    if bucket is not None:
        if bucket not in BUCKETS:
            raise AnalyticsError(f"Unknown bucket {bucket!r}; one of {', '.join(BUCKETS)}")
        width = BUCKETS[bucket]
        if span / width > MAX_BUCKETS:
            raise AnalyticsError(
                f"Bucket {bucket} gives more than {MAX_BUCKETS} points over this range; "
                "widen the bucket or shorten the range"
            )
        return Resolution(bucket, width, automatic=False)
    for key, width in BUCKETS.items():
        if span / width <= MAX_BUCKETS:
            return Resolution(key, width, automatic=True)
    raise AnalyticsError(f"Range too long for the coarsest bucket ({list(BUCKETS)[-1]})")


def whole_range(time_from: datetime, time_to: datetime) -> Resolution:
    """One bucket over the whole range: the statistics view."""
    return Resolution("all", time_to - time_from, automatic=False)


def aggregate_columns(
    value: ColumnElement[Any], aggregates: list[Aggregate]
) -> list[ColumnElement[Any]]:
    by_name: dict[Aggregate, ColumnElement[Any]] = {
        Aggregate.MEAN: func.avg(value),
        Aggregate.MIN: func.min(value),
        Aggregate.MAX: func.max(value),
        Aggregate.MEDIAN: func.percentile_cont(0.5).within_group(value),
        Aggregate.SUM: func.sum(value),
        Aggregate.COUNT: func.count(value),
        Aggregate.FIRST: func.first(value, Measurement.time),
        Aggregate.LAST: func.last(value, Measurement.time),
    }
    return [by_name[a].label(a.value) for a in aggregates]


def aggregate_statement(
    *,
    project_id: uuid.UUID,
    metrics: list[str],
    entity_ids: list[uuid.UUID],
    device_ids: list[uuid.UUID],
    data_source_id: uuid.UUID | None,
    time_from: datetime,
    time_to: datetime,
    resolution: Resolution,
    aggregates: list[Aggregate],
    group_by: GroupBy,
) -> Select[Any]:
    """Rows of (bucket, metric_key, series_key, <one column per aggregate>) ordered by metric,
    series and bucket. Booleans count as 0 and 1, so `mean` is the fraction true."""
    value = func.coalesce(Measurement.value_num, cast(cast(Measurement.value_bool, Integer), Float))
    group_column = Measurement.entity_id if group_by is GroupBy.ENTITY else Measurement.device_id
    time_column = (
        literal(time_from).label("bucket")
        if resolution.key == "all"
        else func.time_bucket(literal(resolution.width, type_=Interval), Measurement.time).label(
            "bucket"
        )
    )
    conditions = [
        Measurement.project_id == project_id,
        Measurement.metric_key.in_(metrics),
        Measurement.time >= time_from,
        Measurement.time < time_to,
    ]
    if entity_ids:
        conditions.append(Measurement.entity_id.in_(entity_ids))
    if device_ids:
        conditions.append(Measurement.device_id.in_(device_ids))
    if data_source_id is not None:
        conditions.append(Measurement.data_source_id == data_source_id)
    return (
        select(
            time_column,
            Measurement.metric_key,
            group_column.label("series_key"),
            *aggregate_columns(value, aggregates),
        )
        .where(*conditions)
        .group_by(time_column, Measurement.metric_key, group_column)
        .order_by(Measurement.metric_key, group_column, time_column)
    )
