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

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import EnvironmentSample, ServerSetting
from shared.secrets import decrypt_json

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


#: The server setting a server admin fills in from the interface (decision D250). The secret is
#: stored as a Fernet token, the way a data source's credentials are.
PROVIDER_SETTING = "environment_providers"


def _provider_from(key: str, config: dict[str, Any]) -> EnvironmentalDataProvider | None:
    """One configured provider, built from its stored settings; None when it is off or its
    credentials are incomplete. Unknown keys are ignored, so a setting from a newer version
    does not break an older server."""
    if key != "copernicus" or not config.get("enabled", True):
        return None
    client_id = str(config.get("client_id") or "")
    secret = config.get("client_secret")
    client_secret = ""
    if isinstance(secret, str) and secret:
        try:
            client_secret = str(decrypt_json(secret.encode()).get("client_secret") or "")
        except InvalidToken:
            return None
    if not client_id or not client_secret:
        return None
    from shared.analysis.providers.copernicus import CopernicusProvider

    return CopernicusProvider(client_id=client_id, client_secret=client_secret)


async def stored_providers(session: AsyncSession) -> list[EnvironmentalDataProvider]:
    """The providers a server admin set up in the interface (decision D250)."""
    row = await session.get(ServerSetting, PROVIDER_SETTING)
    if row is None or not isinstance(row.value, dict):
        return []
    built = [
        _provider_from(key, config) for key, config in row.value.items() if isinstance(config, dict)
    ]
    return [p for p in built if p is not None]


async def configured_provider(
    session: AsyncSession, layer: str
) -> EnvironmentalDataProvider | None:
    """The provider for a layer: what a server admin set up in the interface first, so a change
    there takes effect without a restart, and the environment variables after it (decision
    D250). None when the server has neither."""
    for provider in await stored_providers(session):
        if layer in provider.layers:
            return provider
    return provider_for(layer)


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
    """The layer per geometry (by hash) and week over the period: from the cache where it has
    the week, from the provider for the weeks it does not.

    Only a week that has ended is cached. A week still running has no final answer yet, and a
    week whose satellite passes were all cloudy is cached as "nothing seen" so a rerun does not
    ask again (Tim, 2026-09-18: the layer is the slow part of a run; a period that ends today
    used to refetch its whole span every time)."""
    hashes = [geometry_hash(g) for g in geometries]
    weeks = weeks_between(time_from, time_to)
    if not weeks:
        return {h: {} for h in hashes}
    conditions = [
        EnvironmentSample.provider == provider.key,
        EnvironmentSample.layer == layer,
        EnvironmentSample.geometry_hash.in_(hashes),
        EnvironmentSample.week >= weeks[0],
        EnvironmentSample.week <= weeks[-1],
    ]
    rows = (await session.execute(select(EnvironmentSample).where(*conditions))).scalars()
    cached: dict[str, dict[datetime, float | None]] = {h: {} for h in hashes}
    for row in rows:
        cached[row.geometry_hash][row.week] = row.value
    # a week is done when every geometry has it; one geometry short and the week is asked again
    missing = [week for week in weeks if any(week not in cached[h] for h in hashes)]
    if not missing:
        return cached
    sample = await provider.sample(layer, geometries, missing[0], missing[-1] + WEEK, project_id)
    if len(sample.series) != len(geometries):
        raise ValueError(
            f"{provider.key} answered {len(sample.series)} series for {len(geometries)} "
            "geometries; the module cannot tell which belongs to which"
        )
    fetched_at = datetime.now(UTC)
    values: list[dict[str, Any]] = []
    for h, series in zip(hashes, sample.series, strict=True):
        fresh: dict[datetime, float | None] = dict.fromkeys(missing)
        for when, value in series:
            week = nearest_week(when, missing)
            if week is not None:
                fresh[week] = value
        cached[h].update(fresh)
        values.extend(
            {
                "provider": provider.key,
                "layer": layer,
                "geometry_hash": h,
                "week": week,
                "value": value,
                "fetched_at": fetched_at,
            }
            for week, value in fresh.items()
            # a week that has not ended may still gain a cloud-free pass
            if week + WEEK <= fetched_at
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
