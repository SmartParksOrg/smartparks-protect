"""The offline map of a project's area for Protect Go (phase 43 P3; Protect Go's decision D4).

Protomaps publishes a planet build most days at https://build.protomaps.com/YYYYMMDD.pmtiles, one
PMTiles file of some 140 GB that answers range requests, and its `pmtiles extract` command cuts
a bounding box out of it by reading only the ranges it needs. The export worker runs that
command for a project's area, padded by a margin, down to a zoom level, keeps the result in
MinIO and the row says where; Protect Go downloads it beside the field bundle and serves it to
MapLibre offline. The data is OpenStreetMap's under the ODbL; Protect Go's map credits it.
"""

import asyncio
import hashlib
import math
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.database import session_scope
from shared.enums import MapExtractStatus
from shared.logger import get_logger
from shared.models import MapExtract
from shared.storage import put_file, remove_object
from shared.timeutil import utc_now

log = get_logger("maps")

PLANET_BUILDS = "https://build.protomaps.com"
LOOKBACK_DAYS = 14
#: An extract this young for the same area is reused rather than cut again.
FRESH_FOR = timedelta(days=30)


class MapExtractError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Bbox:
    west: float
    south: float
    east: float
    north: float

    def contains(self, other: "Bbox") -> bool:
        return (
            self.west <= other.west
            and self.south <= other.south
            and self.east >= other.east
            and self.north >= other.north
        )


def pad(bbox: Bbox, km: float) -> Bbox:
    """The box grown by `km` on every side, clamped to the world."""
    lat = (bbox.south + bbox.north) / 2
    dlat = km / 111.32
    dlon = km / max(111.32 * math.cos(math.radians(lat)), 1e-6)
    return Bbox(
        west=max(-180.0, bbox.west - dlon),
        south=max(-85.0, bbox.south - dlat),
        east=min(180.0, bbox.east + dlon),
        north=min(85.0, bbox.north + dlat),
    )


def object_key(project_id: uuid.UUID, build: str) -> str:
    return f"{project_id}/{build}.pmtiles"


async def latest_planet_build(
    client: httpx.AsyncClient, today: date | None = None, lookback: int = LOOKBACK_DAYS
) -> tuple[str, str]:
    """The newest planet build's URL and date: Protomaps skips a day now and then, so the
    dates are probed backwards from today."""
    day = today or datetime.now(UTC).date()
    for back in range(lookback):
        build = (day - timedelta(days=back)).strftime("%Y%m%d")
        url = f"{PLANET_BUILDS}/{build}.pmtiles"
        try:
            response = await client.head(url, timeout=20.0)
        except httpx.HTTPError as exc:
            raise MapExtractError(
                f"No answer from {PLANET_BUILDS}: {exc.__class__.__name__}"
            ) from None
        if response.status_code == 200:
            return url, build
    raise MapExtractError(f"No planet build at {PLANET_BUILDS} in the last {lookback} days")


async def resolve_source() -> tuple[str, str]:
    """The planet build to cut from: the configured one, or the newest published."""
    configured = get_settings().map_extract_source
    if configured:
        stem = configured.rsplit("/", 1)[-1].removesuffix(".pmtiles")
        return configured, stem[:32] or "configured"
    async with httpx.AsyncClient() as client:
        return await latest_planet_build(client)


async def extract(source: str, bbox: Bbox, max_zoom: int, out: Path) -> None:
    """`pmtiles extract` for the box, down to the zoom; the command's last line on failure
    (its progress and errors go to stderr, so it is not run quiet)."""
    settings = get_settings()
    command = [
        settings.pmtiles_bin,
        "extract",
        source,
        str(out),
        f"--bbox={bbox.west},{bbox.south},{bbox.east},{bbox.north}",
        f"--maxzoom={max_zoom}",
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        raise MapExtractError(
            f"The pmtiles command is not installed ({settings.pmtiles_bin})"
        ) from None
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.map_extract_timeout_seconds
        )
    except TimeoutError:
        process.kill()
        raise MapExtractError(
            f"The extract took longer than {settings.map_extract_timeout_seconds} s"
        ) from None
    if process.returncode != 0:
        words = (stderr or stdout).decode(errors="replace").strip().splitlines()
        raise MapExtractError(
            "pmtiles extract failed: " + (words[-1] if words else "no output")[:500]
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def queue_map_extract(
    session: AsyncSession,
    bus: RedisStreamsBus,
    project_id: uuid.UUID,
    area: Bbox,
    *,
    requested_by: uuid.UUID | None,
    force: bool = False,
) -> tuple[MapExtract, bool]:
    """Ask for the project's offline map. One at a time per project; an extract younger than
    `FRESH_FOR` that covers the area is kept unless `force`. Returns the row and whether a job
    was queued."""
    settings = get_settings()
    wanted = pad(area, settings.map_extract_margin_km)
    row = await session.get(MapExtract, project_id)
    if row is not None:
        if row.status in (MapExtractStatus.QUEUED, MapExtractStatus.RUNNING):
            return row, False
        have = Bbox(row.west, row.south, row.east, row.north)
        fresh = row.ready_at is not None and utc_now() - row.ready_at < FRESH_FOR
        if (
            row.status == MapExtractStatus.READY
            and not force
            and fresh
            and have.contains(area)
            and row.max_zoom >= settings.map_extract_max_zoom
        ):
            return row, False
    else:
        row = MapExtract(project_id=project_id, west=0, south=0, east=0, north=0, max_zoom=0)
        session.add(row)
    row.status = MapExtractStatus.QUEUED
    row.west, row.south, row.east, row.north = wanted.west, wanted.south, wanted.east, wanted.north
    row.max_zoom = settings.map_extract_max_zoom
    row.error = None
    row.requested_by = requested_by
    row.requested_at = utc_now()
    await session.flush()
    await bus.publish(Topic.MAP_EXTRACT_REQUESTED, {"project_id": str(project_id)})
    return row, True


async def run_map_extract_job(payload: dict[str, Any]) -> None:
    """The handler of `map_extract.requested`: cut the area, keep the file, say so on the row."""
    project_id = uuid.UUID(str(payload["project_id"]))
    settings = get_settings()
    async with session_scope() as session:
        row = await session.get(MapExtract, project_id)
        if row is None:
            log.warning("map extract row gone before it ran", project_id=str(project_id))
            return
        row.status = MapExtractStatus.RUNNING
        row.error = None
        await session.commit()
        bbox = Bbox(row.west, row.south, row.east, row.north)
        old_key = row.object_key
        try:
            source, build = await resolve_source()
            with tempfile.TemporaryDirectory(prefix="map-extract-") as folder:
                out = Path(folder) / f"{build}.pmtiles"
                await extract(source, bbox, row.max_zoom, out)
                size = out.stat().st_size
                if size > settings.map_extract_max_bytes:
                    raise MapExtractError(
                        f"The map is {size // (1 << 20)} MB, over the limit of "
                        f"{settings.map_extract_max_bytes // (1 << 20)} MB; a smaller area or zoom"
                    )
                key = object_key(project_id, build)
                await put_file(
                    settings.minio_bucket_map_extracts, key, str(out), "application/vnd.pmtiles"
                )
                digest = _sha256(out)
        except Exception as exc:
            await session.rollback()
            row = await session.get(MapExtract, project_id)
            if row is not None:
                row.status = MapExtractStatus.FAILED
                row.error = (
                    f"{exc}"[:1000]
                    if isinstance(exc, MapExtractError)
                    else f"{type(exc).__name__}: {exc}"[:1000]
                )
                await session.commit()
            log.error("map extract failed", project_id=str(project_id), exc_info=True)
            return
        row.status = MapExtractStatus.READY
        row.source, row.build = source, build
        row.object_key, row.size_bytes, row.sha256 = key, size, digest
        row.ready_at = utc_now()
        await session.commit()
        if old_key and old_key != key:
            try:
                await remove_object(settings.minio_bucket_map_extracts, old_key)
            except Exception as exc:
                log.warning("old map extract not removed", key=old_key, error=str(exc))
        log.info("map extract ready", project_id=str(project_id), build=build, size=size)
