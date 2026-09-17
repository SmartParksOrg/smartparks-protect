"""The boundary for environmental data (plan 1, section 11; decision D245 fills it): a module
asks for a layer by name and gets a weekly time series per geometry; it never names a provider.
Providers register at start when their settings are there; `sample_weekly` reads the cache
first (`environment_samples`, one row per geometry, week and layer) and asks the provider only
for a period whose weeks are not all there. A provider's failure is the module's to catch: it
adds a warning and completes without the layer."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import EnvironmentSample

WEEK = timedelta(days=7)


class LayerSample(BaseModel):
    """Values per geometry (in the order asked), or a time series per geometry, with where they
    came from and how fine they are."""

    layer: str
    source: str
    resolution: str | None = None
    sampled_at: datetime
    values: list[float | None] = Field(default_factory=list)
    series: list[list[tuple[datetime, float | None]]] = Field(default_factory=list)


class EnvironmentalDataProvider(Protocol):
    key: str
    layers: tuple[str, ...]

    async def sample(
        self,
        layer: str,
        geometries: Sequence[dict[str, Any]],
        time_from: datetime,
        time_to: datetime,
        project_id: uuid.UUID,
    ) -> LayerSample: ...


#: Providers in order of preference: a project-specific one first, an open global one after.
PROVIDERS: list[EnvironmentalDataProvider] = []


def register(provider: EnvironmentalDataProvider) -> None:
    if all(p.key != provider.key for p in PROVIDERS):
        PROVIDERS.append(provider)


def provider_for(layer: str) -> EnvironmentalDataProvider | None:
    return next((p for p in PROVIDERS if layer in p.layers), None)


def geometry_hash(geometry: dict[str, Any]) -> str:
    """A stable key for a GeoJSON geometry: its coordinates rounded to a metre or so."""

    def rounded(value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 5)
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return value

    text = json.dumps(
        {"type": geometry.get("type"), "coordinates": rounded(geometry.get("coordinates"))}
    )
    return hashlib.sha256(text.encode()).hexdigest()


def week_start(moment: datetime) -> datetime:
    """The Monday at midnight UTC of the week `moment` falls in."""
    day = moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def weeks_between(time_from: datetime, time_to: datetime) -> list[datetime]:
    """Every week the period touches, by its Monday; an empty period touches none."""
    if time_to <= time_from:
        return []
    out = []
    week = week_start(time_from)
    end = week_start(time_to)
    while week < end or (week == end and time_to > end):
        out.append(week)
        week += WEEK
    return out


def nearest_week(moment: datetime, weeks: Sequence[datetime]) -> datetime | None:
    """The week of `weeks` a provider's label belongs to: backends label a week by its Monday
    or by the Sunday before it, so the nearest within four days is the one meant; a label
    outside the period belongs to none."""
    if not weeks:
        return None
    week = min(weeks, key=lambda w: abs((moment - w).total_seconds()))
    return week if abs((moment - week).days) <= 4 else None


async def sample_weekly(
    session: AsyncSession,
    provider: EnvironmentalDataProvider,
    layer: str,
    geometries: Sequence[dict[str, Any]],
    time_from: datetime,
    time_to: datetime,
    project_id: uuid.UUID,
) -> dict[str, dict[datetime, float | None]]:
    """The layer per geometry (by hash) and week over the period, from the cache where every
    week of every geometry is there, from the provider otherwise (its whole answer is cached)."""
    hashes = [geometry_hash(g) for g in geometries]
    weeks = weeks_between(time_from, time_to)
    conditions = [
        EnvironmentSample.provider == provider.key,
        EnvironmentSample.layer == layer,
        EnvironmentSample.geometry_hash.in_(hashes),
    ]
    if weeks:
        conditions.append(EnvironmentSample.week >= weeks[0])
        conditions.append(EnvironmentSample.week <= weeks[-1])
    rows = (await session.execute(select(EnvironmentSample).where(*conditions))).scalars()
    cached: dict[str, dict[datetime, float | None]] = {h: {} for h in hashes}
    for row in rows:
        cached[row.geometry_hash][row.week] = row.value
    if weeks and all(set(weeks) <= set(cached[h]) for h in hashes):
        return cached
    # whole weeks, so the same week always covers the same seven days whichever run asks for
    # it and the cache stays sound across periods that share a boundary week
    sample = await provider.sample(layer, geometries, weeks[0], weeks[-1] + WEEK, project_id)
    fetched_at = datetime.now(UTC)
    values: list[dict[str, Any]] = []
    for h, series in zip(hashes, sample.series, strict=False):
        by_week: dict[datetime, float | None] = dict.fromkeys(weeks)
        for when, value in series:
            week = nearest_week(when, weeks)
            if week is not None:
                by_week[week] = value
        cached[h] = by_week
        values.extend(
            {
                "provider": provider.key,
                "layer": layer,
                "geometry_hash": h,
                "week": week,
                "value": value,
                "fetched_at": fetched_at,
            }
            for week, value in by_week.items()
        )
    if values:
        statement = insert(EnvironmentSample).values(values)
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_environment_samples_key",
                set_={
                    "value": statement.excluded.value,
                    "fetched_at": statement.excluded.fetched_at,
                },
            )
        )
    return cached
