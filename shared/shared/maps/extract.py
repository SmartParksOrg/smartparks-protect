"""The offline map of a project's places for Protect Go (phase 43 P3; Protect Go's decision D4).

Protomaps publishes a planet build most days at https://build.protomaps.com/YYYYMMDD.pmtiles, one
PMTiles file of some 140 GB that answers range requests, and its `pmtiles extract` command cuts
a region out of it by reading only the ranges it needs. The export worker runs that command
for a project's regions, each padded by a margin, down to a zoom level, keeps the result in
MinIO and the row says where; Protect Go downloads it beside the field bundle and serves it to
MapLibre offline. The data is OpenStreetMap's under the ODbL; Protect Go's map credits it.

A project's places may lie far apart (decision D365, Tim, 2026-10-28: the offload station in
the Netherlands, the tracker it serves in Namibia, and one box over both at zoom 14 is most of
Africa): the places are grouped into regions when they lie farther apart than
`MAP_EXTRACT_REGION_GAP_KM`, and one file is cut for all the regions at once through the
command's `--region` option with a multipolygon of boxes.
"""

import asyncio
import hashlib
import json
import math
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
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


def gap_km(a: Bbox, b: Bbox) -> float:
    """How far apart two boxes lie, in kilometres: zero when they touch or overlap."""
    lat = (a.south + a.north + b.south + b.north) / 4
    dlon = max(0.0, max(a.west, b.west) - min(a.east, b.east))
    dlat = max(0.0, max(a.south, b.south) - min(a.north, b.north))
    return math.hypot(dlon * 111.32 * math.cos(math.radians(lat)), dlat * 111.32)


def envelope(boxes: Sequence[Bbox]) -> Bbox:
    """The one box around them all."""
    if not boxes:
        raise ValueError("no boxes")
    return Bbox(
        west=min(b.west for b in boxes),
        south=min(b.south for b in boxes),
        east=max(b.east for b in boxes),
        north=max(b.north for b in boxes),
    )


def regions_of(boxes: Sequence[Bbox], gap: float) -> list[Bbox]:
    """The boxes grouped into regions (decision D365): two boxes closer than `gap` kilometres
    belong together, and a region is the envelope of its boxes; the largest first."""
    regions = list(boxes)
    merged = True
    while merged and len(regions) > 1:
        merged = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                if gap_km(regions[i], regions[j]) <= gap:
                    joined = envelope([regions[i], regions[j]])
                    regions = [r for k, r in enumerate(regions) if k not in (i, j)] + [joined]
                    merged = True
                    break
            if merged:
                break
    return sorted(
        regions, key=lambda r: ((r.east - r.west) * (r.north - r.south), r.west), reverse=True
    )


def covers(regions: Sequence[Bbox], areas: Sequence[Bbox]) -> bool:
    """Whether every area lies within one of the regions."""
    return all(any(region.contains(area) for region in regions) for area in areas)


def region_geojson(regions: Sequence[Bbox]) -> dict[str, Any]:
    """The regions as the GeoJSON multipolygon `pmtiles extract --region` reads."""
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [r.west, r.south],
                    [r.east, r.south],
                    [r.east, r.north],
                    [r.west, r.north],
                    [r.west, r.south],
                ]
            ]
            for r in regions
        ],
    }


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


async def extract(source: str, regions: Sequence[Bbox], max_zoom: int, out: Path) -> None:
    """`pmtiles extract` for the regions, down to the zoom; the command's last line on failure
    (its progress and errors go to stderr, so it is not run quiet). The regions go in as a
    GeoJSON file beside the output, one rectangle each (decision D365)."""
    if not regions:
        raise MapExtractError("No region to cut")
    settings = get_settings()
    region_file = out.with_suffix(".region.json")
    region_file.write_text(json.dumps(region_geojson(regions)))
    command = [
        settings.pmtiles_bin,
        "extract",
        source,
        str(out),
        f"--region={region_file}",
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


def row_regions(row: MapExtract) -> list[Bbox]:
    """The boxes a map row was cut for; a row from before decision D365 is its one box."""
    regions = [
        Bbox(float(r["west"]), float(r["south"]), float(r["east"]), float(r["north"]))
        for r in (row.regions or [])
        if isinstance(r, dict)
    ]
    return regions or [Bbox(row.west, row.south, row.east, row.north)]


async def queue_map_extract(
    session: AsyncSession,
    bus: RedisStreamsBus,
    project_id: uuid.UUID,
    areas: Sequence[Bbox],
    *,
    requested_by: uuid.UUID | None,
    force: bool = False,
) -> tuple[MapExtract, bool]:
    """Ask for the project's offline map. One at a time per project; an extract younger than
    `FRESH_FOR` whose regions cover every area is kept unless `force`. Returns the row and
    whether a job was queued."""
    if not areas:
        raise ValueError("no area to cut")
    settings = get_settings()
    wanted = regions_of(
        [pad(area, settings.map_extract_margin_km) for area in areas],
        settings.map_extract_region_gap_km,
    )
    row = await session.get(MapExtract, project_id)
    if row is not None:
        if row.status in (MapExtractStatus.QUEUED, MapExtractStatus.RUNNING):
            return row, False
        fresh = row.ready_at is not None and utc_now() - row.ready_at < FRESH_FOR
        if (
            row.status == MapExtractStatus.READY
            and not force
            and fresh
            and covers(row_regions(row), areas)
            and row.max_zoom >= settings.map_extract_max_zoom
        ):
            return row, False
    else:
        row = MapExtract(project_id=project_id, west=0, south=0, east=0, north=0, max_zoom=0)
        session.add(row)
    whole = envelope(wanted)
    row.status = MapExtractStatus.QUEUED
    row.west, row.south, row.east, row.north = whole.west, whole.south, whole.east, whole.north
    row.regions = [asdict(region) for region in wanted]
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
        regions = row_regions(row)
        old_key = row.object_key
        try:
            source, build = await resolve_source()
            with tempfile.TemporaryDirectory(prefix="map-extract-") as folder:
                out = Path(folder) / f"{build}.pmtiles"
                await extract(source, regions, row.max_zoom, out)
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
