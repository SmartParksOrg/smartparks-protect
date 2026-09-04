"""The effective value of a canonical record (architecture 28.1, decision D80).

Canonical rows keep their original `time`, `geom` and value; a curation writes the corrected
value into the `curated_*` overlay column and null there means the original applies. Every
reader (map, analytics, rules, exports, integrations) goes through these expressions, so the
effective value is defined in one place. `valid` false hides a record from every normal view.

Time windows are written as a disjunction so an uncurated row is found through the ordinary
time indexes with chunk exclusion, and a curated one through the small partial index on
`curated_time`.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Float, Integer, and_, cast, func, or_
from sqlalchemy.sql import ColumnElement

from shared.models import Measurement, Position

Curatable = type[Position] | type[Measurement]


def effective_time(model: Curatable) -> ColumnElement[datetime]:
    return func.coalesce(model.curated_time, model.time)


def effective_geom() -> ColumnElement[Any]:
    return func.coalesce(Position.curated_geom, Position.geom)


def effective_value_num() -> ColumnElement[float | None]:
    return func.coalesce(Measurement.curated_value_num, Measurement.value_num)


def effective_number() -> ColumnElement[float | None]:
    """Numeric value for aggregation: the curated number, else the number, else a boolean as
    0 or 1 (booleans are not curatable)."""
    return func.coalesce(
        Measurement.curated_value_num,
        Measurement.value_num,
        cast(cast(Measurement.value_bool, Integer), Float),
    )


def in_window(
    model: Curatable, time_from: datetime | None = None, time_to: datetime | None = None
) -> ColumnElement[bool]:
    """`time_from <= effective time < time_to` in index-friendly form."""
    original: list[ColumnElement[bool]] = [model.curated_time.is_(None)]
    curated: list[ColumnElement[bool]] = [model.curated_time.is_not(None)]
    if time_from is not None:
        original.append(model.time >= time_from)
        curated.append(model.curated_time >= time_from)
    if time_to is not None:
        original.append(model.time < time_to)
        curated.append(model.curated_time < time_to)
    return or_(and_(*original), and_(*curated))


def before(model: Curatable, at: datetime, since: datetime | None = None) -> ColumnElement[bool]:
    """`since < effective time <= at`, the lookback form the rules use."""
    original: list[ColumnElement[bool]] = [model.curated_time.is_(None), model.time <= at]
    curated: list[ColumnElement[bool]] = [
        model.curated_time.is_not(None),
        model.curated_time <= at,
    ]
    if since is not None:
        original.append(model.time > since)
        curated.append(model.curated_time > since)
    return or_(and_(*original), and_(*curated))


def visible(model: Curatable) -> ColumnElement[bool]:
    return model.valid.is_(True)
