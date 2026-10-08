"""The raster boundary of the habitat module (phase 41, decision D315): the keys of the cache,
the catalogue of what a project may name (a provider's layers when one is set up, a distance
layer per feature type the project has, the uploads), and the cache itself: a provider is
asked once for an area and period and the bucket answers the next time."""

import uuid
from datetime import UTC, datetime

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.analysis import environment
from shared.analysis.rasters import (
    LayerChoice,
    area_hash,
    cached_raster,
    period_key,
    project_layers,
    raster_key,
)
from shared.config import get_settings
from shared.models import EnvironmentRaster, Feature, Project, ProjectLayer
from shared.storage import get_object
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

TIFF = b"II*\x00" + b"\x00" * 60


class FakeRasterProvider:
    key = "fake_rasters"
    layers = ("ndvi",)
    raster_layers = ("ndvi", "elevation")
    source = "a fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def sample(self, *args, **kwargs):  # the weekly series, unused here
        raise AssertionError("not asked")

    async def fetch_raster(self, layer, bbox, epsg, resolution_m, time_from, time_to, project_id):
        self.calls.append((layer, period_key(time_from, time_to)))
        return TIFF


async def _empty(*_args, **_kwargs):
    return []


def test_the_keys_name_the_grid_and_the_period():
    bbox = (16.70, -20.86, 16.76, -20.83)
    near = (16.7000004, -20.86, 16.76, -20.83)
    assert area_hash(bbox, 32733, 30.0) == area_hash(near, 32733, 30.0)
    assert area_hash(bbox, 32733, 30.0) != area_hash(bbox, 32733, 60.0)
    assert area_hash(bbox, 32733, 30.0) != area_hash(bbox, 32734, 30.0)
    assert period_key(None, None) == "static"
    assert (
        period_key(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC))
        == "2026-07-01/2026-09-01"
    )
    key = raster_key("copernicus_openeo", "ndvi", "abc", "2026-07-01/2026-09-01")
    assert key == "rasters/copernicus_openeo/ndvi/abc/2026-07-01_2026-09-01.tif"
    choice = LayerChoice(name="ndvi", label="x", source="provider", periodic=True)
    assert choice.document()["periodic"] and choice.document()["layer_id"] is None


async def test_the_catalogue_follows_the_provider_the_features_and_the_uploads(
    session, monkeypatch
):
    project = Project(name=unique_name("Rasters"), slug=unique_name("rasters"), timezone="UTC")
    session.add(project)
    await session.flush()
    session.add(
        Feature(
            project_id=project.id,
            feature_type="route",
            name=unique_name("Track"),
            geom=WKTElement("LINESTRING(16.70 -20.85, 16.72 -20.84)", srid=4326),
        )
    )
    session.add(
        ProjectLayer(
            project_id=project.id,
            name="soil",
            label="Soil",
            kind="categorical",
            object_key="x",
            size_bytes=1,
            epsg=32733,
            width=1,
            height=1,
            pixel_m=30.0,
            extent={},
        )
    )
    await session.flush()
    # no provider: the distance layer and the upload alone
    monkeypatch.setattr(environment, "stored_providers", _empty)
    monkeypatch.setattr(environment, "provider_for", lambda *_a, **_k: None)
    choices = {c.name: c for c in await project_layers(session, project.id)}
    assert set(choices) == {"distance_to_route", "soil"}
    assert choices["soil"].kind == "categorical" and choices["soil"].source == "project"
    assert choices["distance_to_route"].feature_type == "route"
    # with a provider that answers rasters: NDVI and elevation join, first
    provider = FakeRasterProvider()
    monkeypatch.setattr(environment, "provider_for", lambda *_a, **_k: provider)
    names = [c.name for c in await project_layers(session, project.id)]
    assert names == ["ndvi", "elevation", "distance_to_route", "soil"]


async def test_the_cache_asks_once_per_area_and_period(session):
    provider = FakeRasterProvider()
    bbox = (16.70, -20.86, 16.76, -20.83)
    project_id = uuid.uuid4()
    t0, t1 = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)
    t2 = datetime(2026, 10, 1, tzinfo=UTC)
    args = (session, provider, "ndvi", bbox, 32733, 30.0)
    first, fetched = await cached_raster(*args, t0, t1, project_id)
    assert fetched and first == TIFF and provider.calls == [("ndvi", "2026-07-01/2026-09-01")]
    second, fetched = await cached_raster(*args, t0, t1, project_id)
    assert not fetched and second == TIFF and len(provider.calls) == 1
    # another period, another resolution, a static layer: each asked once
    await cached_raster(*args, t1, t2, project_id)
    await cached_raster(session, provider, "ndvi", bbox, 32733, 60.0, t0, t1, project_id)
    await cached_raster(session, provider, "elevation", bbox, 32733, 30.0, None, None, project_id)
    await cached_raster(session, provider, "elevation", bbox, 32733, 30.0, None, None, project_id)
    assert len(provider.calls) == 4
    rows = (
        await session.scalars(
            select(EnvironmentRaster).where(EnvironmentRaster.provider == provider.key)
        )
    ).all()
    assert len(rows) >= 4
    assert all(r.size_bytes == len(TIFF) for r in rows)
    stored = await get_object(get_settings().minio_bucket_analysis_layers, rows[0].object_key)
    assert stored == TIFF
