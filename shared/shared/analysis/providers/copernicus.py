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
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from shared.analysis.environment import LayerSample
from shared.logger import get_logger

log = get_logger("analysis.copernicus")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
API = "https://openeo.dataspace.copernicus.eu/openeo/1.2"
COLLECTION = "SENTINEL2_L2A"
#: How long a job may take before the provider gives up, and how often it looks.
JOB_TIMEOUT_S = 20 * 60
POLL_S = 15
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
    source = "Sentinel-2 L2A via Copernicus Data Space openEO"
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
        async with self._client() as client:
            headers = await self._token(client)
            created = await client.post(
                f"{API}/jobs",
                json={"process": process, "title": f"protect ndvi {project_id}"},
                headers=headers,
            )
            if created.status_code not in (201, 202):
                raise ProviderError(
                    f"openEO refused the job ({created.status_code}): {created.text[:200]}"
                )
            job_id = created.headers.get("OpenEO-Identifier") or (created.json() or {}).get("id")
            if not job_id:
                raise ProviderError("openEO gave the job no id")
            started = await client.post(f"{API}/jobs/{job_id}/results", headers=headers)
            if started.status_code not in (200, 202):
                raise ProviderError(f"openEO did not start the job ({started.status_code})")
            deadline = asyncio.get_running_loop().time() + JOB_TIMEOUT_S
            status = "queued"
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(POLL_S)
                state = await client.get(f"{API}/jobs/{job_id}", headers=headers)
                status = str((state.json() or {}).get("status", "unknown"))
                if status in ("finished", "error", "canceled"):
                    break
            if status != "finished":
                raise ProviderError(f"openEO job {job_id} ended as {status}")
            results = await client.get(f"{API}/jobs/{job_id}/results", headers=headers)
            assets = (results.json() or {}).get("assets") or {}
            body: Any = None
            hrefs = [
                str(asset.get("href"))
                for asset in assets.values()
                if asset.get("href") and str(asset.get("type", "")).startswith("application/json")
            ] or [str(asset.get("href")) for asset in assets.values() if asset.get("href")]
            for href in hrefs:
                # the asset lives on their object store behind a signed URL: our own
                # authorization header makes it refuse the download
                answer = await client.get(href)
                if answer.status_code == 200:
                    body = answer.json()
                    break
            if body is None:
                raise ProviderError(f"openEO job {job_id} finished without a result")
        log.info("copernicus ndvi sampled", geometries=len(geometries), job=job_id)
        return LayerSample(
            layer=layer,
            source=self.source,
            resolution=self.resolution,
            sampled_at=datetime.now(UTC),
            series=parse_timeseries(body, len(geometries)),
        )
