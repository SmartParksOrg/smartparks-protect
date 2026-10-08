"""The raster layers of a habitat run (phase 41, decision D315), beside the weekly series of
`environment.py`: what a project can put into a model (the layers a provider fetches, the
distance to the project's features, what a project uploaded), the cache of what a provider
answered, and the GeoTIFF files in the analysis layers bucket. No raster library here: this
module runs in the lean API as well as in the worker; the pixels are the worker's business
(`primitives/habitat.py`)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis.environment import configured_provider
from shared.config import get_settings
from shared.enums import LayerKind
from shared.models import EnvironmentRaster, Feature, ProjectLayer
from shared.storage import get_object, put_object

#: The layers a provider answers as rasters, with the period they depend on.
FETCHED_LAYERS: dict[str, dict[str, Any]] = {
    "ndvi": {
        "label": "Vegetation (NDVI, Sentinel-2)",
        "periodic": True,
        "resolution_m": 10.0,
        "description": "The mean vegetation index of the period, clouds masked",
    },
    "elevation": {
        "label": "Elevation (Copernicus DEM)",
        "periodic": False,
        "resolution_m": 30.0,
        "description": "Height above sea level in metres",
    },
    "slope": {
        "label": "Slope (from the Copernicus DEM)",
        "periodic": False,
        "resolution_m": 30.0,
        "description": "The steepness of the ground in degrees, from the elevation",
    },
}
#: The feature types a distance layer can be made from, with the band name's suffix.
DISTANCE_FEATURE_TYPES: dict[str, str] = {
    "site": "Distance to the nearest site",
    "route": "Distance to the nearest route",
    "zone": "Distance to the nearest zone",
    "geofence": "Distance to the nearest geofence",
    "fence": "Distance to the nearest fence line",
}
DISTANCE_PREFIX = "distance_to_"
LayerSource = Literal["provider", "distance", "project"]


class RasterProvider(Protocol):
    """A provider that answers a layer as a GeoTIFF over an area (the openEO provider does);
    `raster_layers` names the ones it has."""

    key: str
    raster_layers: tuple[str, ...]

    async def fetch_raster(
        self,
        layer: str,
        bbox: tuple[float, float, float, float],
        epsg: int,
        resolution_m: float,
        time_from: datetime | None,
        time_to: datetime | None,
        project_id: uuid.UUID,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class LayerChoice:
    """One layer the form offers and a run names: the band name, where it comes from, and how
    it enters the model."""

    name: str
    label: str
    source: LayerSource
    kind: str = LayerKind.CONTINUOUS
    description: str | None = None
    #: A fetched layer that depends on the run's period (NDVI) or not (elevation).
    periodic: bool = False
    #: The feature type of a distance layer, the project layer's id for an upload.
    feature_type: str | None = None
    layer_id: uuid.UUID | None = None

    def document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "source": self.source,
            "kind": self.kind,
            "description": self.description,
            "periodic": self.periodic,
            "feature_type": self.feature_type,
            "layer_id": str(self.layer_id) if self.layer_id else None,
        }


async def project_layers(session: AsyncSession, project_id: uuid.UUID) -> list[LayerChoice]:
    """Every layer a run of the project may name: the provider's when a server admin set one
    up, a distance layer per feature type the project has features of, and the uploads."""
    choices: list[LayerChoice] = []
    provider = await configured_provider(session, "ndvi")
    names: tuple[str, ...] = getattr(provider, "raster_layers", ()) if provider else ()
    # the slope is derived from the elevation here, so a provider that answers the elevation
    # offers the slope too (the first catalogue on dev, 2026-10-08, left it out)
    if "elevation" in names and "slope" not in names:
        names = (*names, "slope")
    for name in names:
        meta = FETCHED_LAYERS.get(name)
        if meta is not None:
            choices.append(
                LayerChoice(
                    name=name,
                    label=str(meta["label"]),
                    source="provider",
                    description=str(meta["description"]),
                    periodic=bool(meta["periodic"]),
                )
            )
    counts = (
        await session.execute(
            select(Feature.feature_type, func.count())
            .where(Feature.project_id == project_id)
            .group_by(Feature.feature_type)
        )
    ).all()
    for feature_type, count in counts:
        label = DISTANCE_FEATURE_TYPES.get(str(feature_type))
        if label is None or not count:
            continue
        choices.append(
            LayerChoice(
                name=f"{DISTANCE_PREFIX}{feature_type}",
                label=label,
                source="distance",
                description=f"Metres from each cell to the nearest of the project's {count} "
                f"{feature_type}{'s' if count != 1 else ''}",
                feature_type=str(feature_type),
            )
        )
    rows = (
        await session.scalars(
            select(ProjectLayer)
            .where(ProjectLayer.project_id == project_id)
            .order_by(ProjectLayer.name)
        )
    ).all()
    for row in rows:
        choices.append(
            LayerChoice(
                name=row.name,
                label=row.label,
                source="project",
                kind=row.kind,
                description=f"Uploaded GeoTIFF, {row.pixel_m:g} m pixels, EPSG:{row.epsg}",
                layer_id=row.id,
            )
        )
    return choices


def area_hash(bbox: Sequence[float], epsg: int, resolution_m: float) -> str:
    """The key of a raster's grid: the extent in degrees to a hundred-thousandth (about a
    metre), the CRS and the resolution. Rounding to the degree, as the first version did,
    served one run's raster to another run in the same degree cell (Okonjima, 2026-10-08),
    whose grid it did not cover."""
    rounded = [round(float(v), 5) for v in bbox]
    payload = json.dumps([rounded, int(epsg), round(float(resolution_m), 3)])
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def period_key(time_from: datetime | None, time_to: datetime | None) -> str:
    if time_from is None or time_to is None:
        return "static"
    return f"{time_from.date().isoformat()}/{time_to.date().isoformat()}"


def raster_key(provider: str, layer: str, hashed: str, period: str) -> str:
    return f"rasters/{provider}/{layer}/{hashed}/{period.replace('/', '_')}.tif"


def layer_key(project_id: uuid.UUID, layer_id: uuid.UUID) -> str:
    return f"projects/{project_id}/layers/{layer_id}.tif"


async def cached_raster(
    session: AsyncSession,
    provider: RasterProvider,
    layer: str,
    bbox: tuple[float, float, float, float],
    epsg: int,
    resolution_m: float,
    time_from: datetime | None,
    time_to: datetime | None,
    project_id: uuid.UUID,
) -> tuple[bytes, bool]:
    """The layer as a GeoTIFF over the grid: from the bucket when the cache holds it, else
    from the provider, stored for the next run. Answers the bytes and whether they were
    fetched now. A provider's failure propagates: the module turns it into a warning."""
    settings = get_settings()
    hashed = area_hash(bbox, epsg, resolution_m)
    period = period_key(time_from, time_to)
    row = await session.scalar(
        select(EnvironmentRaster).where(
            EnvironmentRaster.provider == provider.key,
            EnvironmentRaster.layer == layer,
            EnvironmentRaster.area_hash == hashed,
            EnvironmentRaster.epsg == epsg,
            EnvironmentRaster.resolution_m == resolution_m,
            EnvironmentRaster.period == period,
        )
    )
    if row is not None:
        return await get_object(settings.minio_bucket_analysis_layers, row.object_key), False
    data = await provider.fetch_raster(
        layer, bbox, epsg, resolution_m, time_from, time_to, project_id
    )
    key = raster_key(provider.key, layer, hashed, period)
    await put_object(settings.minio_bucket_analysis_layers, key, data, "image/tiff")
    session.add(
        EnvironmentRaster(
            provider=provider.key,
            layer=layer,
            area_hash=hashed,
            epsg=epsg,
            resolution_m=resolution_m,
            period=period,
            object_key=key,
            size_bytes=len(data),
            fetched_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return data, True


async def project_layer_bytes(layer: ProjectLayer) -> bytes:
    return await get_object(get_settings().minio_bucket_analysis_layers, layer.object_key)
