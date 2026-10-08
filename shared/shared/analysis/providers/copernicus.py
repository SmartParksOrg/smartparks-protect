"""Sentinel-2 through the Copernicus Data Space openEO API (decision D245): the vegetation index
(NDVI) per geometry and week. One batch job per request: the level 2A collection over the
areas' bounding box and the period, the scene classification's cloud mask (the backend's
`mask_scl_dilation`), NDVI from the red and near-infrared bands, the weekly mean per pixel,
then the mean per geometry, saved as JSON. The job is started, polled and its one asset read;
nothing is stored on their side afterwards.

Authentication is the client credentials flow against the Copernicus identity service with the
`openid` scope; openEO takes the token as `Bearer oidc/CDSE/<token>`."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.analysis.environment import LayerSample
from shared.analysis.rasters import area_hash, period_key
from shared.logger import get_logger

log = get_logger("analysis.copernicus")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
API = "https://openeo.dataspace.copernicus.eu/openeo/1.2"
COLLECTION = "SENTINEL2_L2A"
#: How long a job may take before the provider gives up, and how often it looks.
JOB_TIMEOUT_S = 20 * 60
#: A raster job's limit: the NDVI of a month over a few hundred km² takes longer than the
#: weekly series, and the habitat module waits an hour in all.
RASTER_JOB_TIMEOUT_S = 50 * 60
POLL_S = 15
#: The first wait after a 429 from openEO, doubled each time.
RETRY_S = 5
#: Areas and the cells of the vegetation mosaic go up in one job (Tim, 2026-09-18), so the cap
#: sits above `grazing.MAX_VEGETATION_CELLS` plus the areas. The pixels processed decide the
#: cost, not the number of polygons the result is aggregated onto.
MAX_GEOMETRIES = 700

MEAN = {
    "process_graph": {
        "m": {
            "process_id": "mean",
            "arguments": {"data": {"from_parameter": "data"}},
            "result": True,
        }
    }
}


class ProviderError(RuntimeError):
    """The provider could not answer; the module adds a warning and completes without it."""


def bbox(geometries: Sequence[dict[str, Any]]) -> dict[str, float]:
    xs: list[float] = []
    ys: list[float] = []

    def walk(coordinates: Any) -> None:
        if (
            isinstance(coordinates, list)
            and coordinates
            and isinstance(coordinates[0], int | float)
        ):
            xs.append(float(coordinates[0]))
            ys.append(float(coordinates[1]))
        elif isinstance(coordinates, list):
            for c in coordinates:
                walk(c)

    for geometry in geometries:
        walk(geometry.get("coordinates"))
    pad = 0.001
    return {
        "west": min(xs) - pad,
        "south": min(ys) - pad,
        "east": max(xs) + pad,
        "north": max(ys) + pad,
    }


def ndvi_process(
    geometries: Sequence[dict[str, Any]], time_from: datetime, time_to: datetime
) -> dict[str, Any]:
    """The openEO process graph: weekly mean NDVI per geometry, clouds masked."""
    features = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"index": i}, "geometry": g}
            for i, g in enumerate(geometries)
        ],
    }
    return {
        "process_graph": {
            "load": {
                "process_id": "load_collection",
                "arguments": {
                    "id": COLLECTION,
                    "spatial_extent": bbox(geometries),
                    "temporal_extent": [time_from.date().isoformat(), time_to.date().isoformat()],
                    "bands": ["B04", "B08", "SCL"],
                },
            },
            "mask": {
                "process_id": "mask_scl_dilation",
                "arguments": {"data": {"from_node": "load"}, "scl_band_name": "SCL"},
            },
            "ndvi": {
                "process_id": "ndvi",
                "arguments": {"data": {"from_node": "mask"}, "nir": "B08", "red": "B04"},
            },
            "weekly": {
                "process_id": "aggregate_temporal_period",
                "arguments": {"data": {"from_node": "ndvi"}, "period": "week", "reducer": MEAN},
            },
            "areas": {
                "process_id": "aggregate_spatial",
                "arguments": {
                    "data": {"from_node": "weekly"},
                    "geometries": features,
                    "reducer": MEAN,
                },
            },
            "save": {
                "process_id": "save_result",
                "arguments": {"data": {"from_node": "areas"}, "format": "JSON"},
                "result": True,
            },
        }
    }


#: The rasters of a habitat run (phase 41, decision D315): the period's mean NDVI from
#: Sentinel-2, and the elevation of the Copernicus 30 m DEM (`COPERNICUS_30` on the same
#: backend: one band `DEM`, 2010 to 2015, global). The slope is derived on our side.
DEM_COLLECTION = "COPERNICUS_30"
RASTER_LAYERS: tuple[str, ...] = ("ndvi", "elevation")


def _spatial_extent(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    west, south, east, north = bbox
    return {"west": west, "south": south, "east": east, "north": north}


def ndvi_raster_process(
    bbox: tuple[float, float, float, float],
    epsg: int,
    resolution_m: float,
    time_from: datetime,
    time_to: datetime,
) -> dict[str, Any]:
    """The openEO process graph of the period's mean NDVI as one GeoTIFF on the run's grid:
    the level 2A scenes over the extent (WGS84) and the period, the cloud mask, NDVI, the mean
    over time (`reduce_dimension` over `t`), resampled onto the run's CRS and resolution
    (`resample_spatial`, so the file comes in the grid the run reads), saved as a Cloud
    Optimized GeoTIFF with deflate compression."""
    return {
        "process_graph": {
            "load": {
                "process_id": "load_collection",
                "arguments": {
                    "id": COLLECTION,
                    "spatial_extent": _spatial_extent(bbox),
                    "temporal_extent": [time_from.date().isoformat(), time_to.date().isoformat()],
                    "bands": ["B04", "B08", "SCL"],
                },
            },
            "mask": {
                "process_id": "mask_scl_dilation",
                "arguments": {"data": {"from_node": "load"}, "scl_band_name": "SCL"},
            },
            "ndvi": {
                "process_id": "ndvi",
                "arguments": {"data": {"from_node": "mask"}, "nir": "B08", "red": "B04"},
            },
            "mean": {
                "process_id": "reduce_dimension",
                "arguments": {"data": {"from_node": "ndvi"}, "dimension": "t", "reducer": MEAN},
            },
            "grid": {
                "process_id": "resample_spatial",
                "arguments": {
                    "data": {"from_node": "mean"},
                    "projection": int(epsg),
                    "resolution": float(resolution_m),
                    "method": "average",
                },
            },
            "save": {
                "process_id": "save_result",
                "arguments": {
                    "data": {"from_node": "grid"},
                    "format": "GTiff",
                    "options": {"compression": "deflate"},
                },
                "result": True,
            },
        }
    }


def elevation_process(
    bbox: tuple[float, float, float, float], epsg: int, resolution_m: float
) -> dict[str, Any]:
    """The openEO process graph of the elevation over the extent as one GeoTIFF on the run's
    grid: the DEM collection's single band, reduced over its (one) time step and resampled
    with bilinear interpolation, since a height is continuous."""
    return {
        "process_graph": {
            "load": {
                "process_id": "load_collection",
                "arguments": {
                    "id": DEM_COLLECTION,
                    "spatial_extent": _spatial_extent(bbox),
                    "temporal_extent": None,
                    "bands": ["DEM"],
                },
            },
            "one": {
                "process_id": "reduce_dimension",
                "arguments": {"data": {"from_node": "load"}, "dimension": "t", "reducer": MEAN},
            },
            "grid": {
                "process_id": "resample_spatial",
                "arguments": {
                    "data": {"from_node": "one"},
                    "projection": int(epsg),
                    "resolution": float(resolution_m),
                    "method": "bilinear",
                },
            },
            "save": {
                "process_id": "save_result",
                "arguments": {
                    "data": {"from_node": "grid"},
                    "format": "GTiff",
                    "options": {"compression": "deflate"},
                },
                "result": True,
            },
        }
    }


def parse_timeseries(body: Any, count: int) -> list[list[tuple[datetime, float | None]]]:
    """The JSON the backend writes for an `aggregate_spatial` over time: a mapping from the
    timestamp to one list per geometry, each a list of band values (one band here). A null or
    a NaN is no valid observation."""
    series: list[list[tuple[datetime, float | None]]] = [[] for _ in range(count)]
    if not isinstance(body, dict):
        raise ProviderError("the openEO answer is not a mapping from time to values")
    for stamp, per_geometry in sorted(body.items()):
        try:
            when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if not isinstance(per_geometry, list):
            continue
        for index in range(count):
            entry = per_geometry[index] if index < len(per_geometry) else None
            value = entry[0] if isinstance(entry, list) and entry else entry
            number = float(value) if isinstance(value, int | float) and value == value else None
            series[index].append((when, number))
    return series


class CopernicusProvider:
    key: str = "copernicus_openeo"
    layers: tuple[str, ...] = ("ndvi",)
    raster_layers: tuple[str, ...] = RASTER_LAYERS
    source = "Sentinel-2 L2A via Copernicus Data Space openEO"
    #: Where each raster layer comes from, for a run's layers table and provenance.
    raster_sources: ClassVar[dict[str, str]] = {
        "ndvi": "Sentinel-2 L2A via Copernicus Data Space openEO",
        "elevation": f"Copernicus DEM ({DEM_COLLECTION}) via Copernicus Data Space openEO",
    }
    resolution = "10 m, weekly mean"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=60, transport=self.transport)

    async def _token(self, client: httpx.AsyncClient) -> dict[str, str]:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "openid",
            },
        )
        if response.status_code != 200:
            raise ProviderError(f"Copernicus identity refused the client ({response.status_code})")
        return {"Authorization": "Bearer oidc/CDSE/" + str(response.json().get("access_token", ""))}

    async def check(self) -> str:
        """Test connection for the Environmental data page (decision D250): the credentials
        are exchanged for a token and the collection is asked for, which costs no processing
        quota. Raises `ProviderError` with what went wrong."""
        async with self._client() as client:
            headers = await self._token(client)
            response = await client.get(f"{API}/collections/{COLLECTION}", headers=headers)
            if response.status_code != 200:
                raise ProviderError(
                    f"openEO answered {response.status_code} for {COLLECTION}; the client is "
                    "known but may lack access to the collection"
                )
        return f"Connected; {COLLECTION} is available"

    async def _until_accepted(
        self,
        client: httpx.AsyncClient,
        request: Callable[[], Awaitable[httpx.Response]],
        deadline: float,
    ) -> httpx.Response:
        """The request's answer, retried while openEO answers 429: two jobs of a run started
        in the same second had the second refused (2026-10-08). `Retry-After` when they say,
        else a wait that doubles from `RETRY_S`, up to the job deadline."""
        wait = float(RETRY_S)
        while True:
            answer = await request()
            if answer.status_code != 429 or asyncio.get_running_loop().time() + wait > deadline:
                return answer
            after = answer.headers.get("Retry-After")
            if after and after.isdigit():
                wait = max(wait, float(after))
            log.info("openEO asks to wait", seconds=wait)
            await asyncio.sleep(wait)
            wait = min(wait * 2, 120.0)

    async def _our_job(
        self, client: httpx.AsyncClient, headers: dict[str, str], title: str
    ) -> tuple[str, str] | None:
        """The newest of the account's jobs with this title that is still worth something
        (created, queued, running or finished), as (id, status); None when there is none.
        A raster job's title names its layer, grid and period, so a run that gave up on a
        job (the pangolin run of 2026-10-08 passed the 20 minute limit inside its NDVI job)
        leaves it running on their side and the next run picks it up."""
        listing = await client.get(f"{API}/jobs", headers=headers)
        if listing.status_code != 200:
            return None
        jobs = [
            j
            for j in (listing.json() or {}).get("jobs") or []
            if j.get("title") == title
            and str(j.get("status")) in ("created", "queued", "running", "finished")
        ]
        if not jobs:
            return None
        newest = max(jobs, key=lambda j: str(j.get("created") or ""))
        return str(newest["id"]), str(newest["status"])

    async def _run_job(
        self,
        process: dict[str, Any],
        title: str,
        media_type: str,
        *,
        timeout_s: float = JOB_TIMEOUT_S,
        reuse: bool = False,
    ) -> tuple[httpx.Response, str]:
        """One batch job: created (or, with `reuse`, found by its title), started, polled to
        its end within `timeout_s`, and its first asset of the media type (else any asset)
        downloaded. Answers the download and the job id. A job the deadline cuts off is left
        running on their side, for a later call with `reuse` to pick up."""
        async with self._client() as client:
            headers = await self._token(client)
            deadline = asyncio.get_running_loop().time() + timeout_s
            found = await self._our_job(client, headers, title) if reuse else None
            if found is not None:
                job_id, status = found
                log.info("openEO job reused", job=job_id, status=status, title=title)
            else:
                created = await self._until_accepted(
                    client,
                    lambda: client.post(
                        f"{API}/jobs", json={"process": process, "title": title}, headers=headers
                    ),
                    deadline,
                )
                if created.status_code not in (201, 202):
                    raise ProviderError(
                        f"openEO refused the job ({created.status_code}): {created.text[:200]}"
                    )
                job_id = str(
                    created.headers.get("OpenEO-Identifier") or (created.json() or {}).get("id")
                )
                status = "created"
            if not job_id or job_id == "None":
                raise ProviderError("openEO gave the job no id")
            if status == "created":
                started = await self._until_accepted(
                    client,
                    lambda: client.post(f"{API}/jobs/{job_id}/results", headers=headers),
                    deadline,
                )
                if started.status_code not in (200, 202):
                    # the job stays "created" on their side otherwise, forever
                    await client.delete(f"{API}/jobs/{job_id}", headers=headers)
                    raise ProviderError(f"openEO did not start the job ({started.status_code})")
            while status != "finished" and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(POLL_S)
                state = await client.get(f"{API}/jobs/{job_id}", headers=headers)
                status = str((state.json() or {}).get("status", "unknown"))
                if status in ("finished", "error", "canceled"):
                    break
            if status != "finished":
                log.warning("openEO job left running", job=job_id, status=status, title=title)
                raise ProviderError(
                    f"openEO job {job_id} ended as {status} within {int(timeout_s)} s; "
                    "it goes on on their side and a later run picks it up"
                )
            results = await client.get(f"{API}/jobs/{job_id}/results", headers=headers)
            assets = (results.json() or {}).get("assets") or {}
            hrefs = [
                str(asset.get("href"))
                for asset in assets.values()
                if asset.get("href") and str(asset.get("type", "")).startswith(media_type)
            ] or [str(asset.get("href")) for asset in assets.values() if asset.get("href")]
            for href in hrefs:
                # the asset lives on their object store behind a signed URL: our own
                # authorization header makes it refuse the download
                answer = await client.get(href)
                if answer.status_code == 200:
                    return answer, str(job_id)
            raise ProviderError(f"openEO job {job_id} finished without a result")

    async def fetch_raster(
        self,
        layer: str,
        bbox: tuple[float, float, float, float],
        epsg: int,
        resolution_m: float,
        time_from: datetime | None,
        time_to: datetime | None,
        project_id: uuid.UUID,
    ) -> bytes:
        """A layer as one GeoTIFF on the grid (phase 41): the period's mean NDVI, or the
        elevation. The bytes are the job's asset as the backend wrote it."""
        if layer == "ndvi":
            if time_from is None or time_to is None:
                raise ProviderError("the NDVI raster needs a period")
            process = ndvi_raster_process(bbox, epsg, resolution_m, time_from, time_to)
        elif layer == "elevation":
            process = elevation_process(bbox, epsg, resolution_m)
        else:
            raise ProviderError(f"layer {layer!r} is not one this provider answers as a raster")
        title = (
            f"protect {layer} {area_hash(bbox, epsg, resolution_m)} "
            f"{period_key(time_from, time_to)}"
        )
        answer, job_id = await self._run_job(
            process, title, "image/tiff", timeout_s=RASTER_JOB_TIMEOUT_S, reuse=True
        )
        data = answer.content
        if not data.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
            raise ProviderError(f"openEO job {job_id} answered something that is not a TIFF")
        log.info("copernicus raster fetched", layer=layer, job=job_id, bytes=len(data))
        return data

    async def sample(
        self,
        layer: str,
        geometries: Sequence[dict[str, Any]],
        time_from: datetime,
        time_to: datetime,
        project_id: uuid.UUID,
    ) -> LayerSample:
        if layer not in self.layers:
            raise ProviderError(f"layer {layer!r} is not one this provider answers")
        if not geometries or len(geometries) > MAX_GEOMETRIES:
            raise ProviderError(f"between 1 and {MAX_GEOMETRIES} geometries, not {len(geometries)}")
        process = ndvi_process(geometries, time_from, time_to)
        answer, job_id = await self._run_job(
            process, f"protect ndvi {project_id}", "application/json"
        )
        body = answer.json()
        log.info("copernicus ndvi sampled", geometries=len(geometries), job=job_id)
        return LayerSample(
            layer=layer,
            source=self.source,
            resolution=self.resolution,
            sampled_at=datetime.now(UTC),
            series=parse_timeseries(body, len(geometries)),
        )
