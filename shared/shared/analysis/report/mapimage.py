"""The map of a report: the result polygons (and tracks, when asked) drawn in Web Mercator over
a base map, with a scale bar, a north arrow and the attribution the base map requires.

The base map is MapTiler's static image when the server has a key that allows static maps,
else the standard OpenStreetMap raster tiles stitched together (a dozen or so small images,
fetched a few at a time with a proper user agent, the way the tile usage policy asks), else a
plain ground; the report says which when it is not the first.
"""

from __future__ import annotations

import asyncio
import io
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from PIL import Image
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from shared.logger import get_logger
from shared.version import __version__

log = get_logger("analysis.report.map")

EARTH_RADIUS = 6_378_137.0
WORLD = 2 * math.pi * EARTH_RADIUS
TILE = 512  # MapTiler's static map reckons in 512 px tiles
OSM_TILE = 256
STATIC_URL = (
    "https://api.maptiler.com/maps/streets-v2/static/{lon:.6f},{lat:.6f},{zoom:.2f}/{w}x{h}@2x.png"
)
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = (
    f"SmartParksProtect/{__version__} (+https://github.com/SmartParksOrg/smartparks-protect)"
)
MAX_ZOOM = 17.0
MIN_ZOOM = 2.0
OSM_MAX_ZOOM = 18
#: At most this many tiles per map: a report's picture, not a bulk download.
MAX_TILES = 40
TILE_CONCURRENCY = 4
MAPTILER_ATTRIBUTION = "© MapTiler © OpenStreetMap contributors"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
BACKGROUND = "#F1F4F2"
#: The areas by pressure, warm like the use they summarise (Tim, 2026-09-18); the same five
#: steps as the interface's `PRESSURE_RAMP`, so a report and the map read alike.
PRESSURE_RAMP = ["#F6F0EA", "#E6D6C6", "#D2B096", "#BE8663", "#AF4436"]
FILL_ALPHA = {"area": 0.45, "mcp": 0.12, "kde": 0.2, "cluster": 0.25, "hotspot": 0.35}

Bounds = tuple[float, float, float, float]  # xmin, xmax, ymin, ymax in Mercator metres


@dataclass
class TrackLine:
    lon: list[float]
    lat: list[float]
    color: str
    label: str


@dataclass
class Shape:
    geometry: BaseGeometry
    color: str
    kind: str
    label: str = ""
    #: A share or an isopleth level; a point (a gateway heard) is sized by it.
    level: float | None = None


@dataclass
class Extent:
    """Mercator metres of the image's edges and the zoom it was reckoned at."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zoom: float
    centre_lat: float

    @property
    def width_m(self) -> float:
        return self.xmax - self.xmin

    @property
    def bounds(self) -> Bounds:
        return (self.xmin, self.xmax, self.ymin, self.ymax)


@dataclass
class BaseImage:
    """A base map to draw over: the picture, the Mercator metres of its edges, its credit."""

    image: Image.Image
    bounds: Bounds
    attribution: str


@dataclass
class TileGrid:
    """The OpenStreetMap tiles that cover an extent at one zoom."""

    zoom: int
    x0: int
    x1: int
    y0: int
    y1: int

    @property
    def count(self) -> int:
        return (self.x1 - self.x0 + 1) * (self.y1 - self.y0 + 1)

    @property
    def bounds(self) -> Bounds:
        size = WORLD / 2**self.zoom
        return (
            self.x0 * size - WORLD / 2,
            (self.x1 + 1) * size - WORLD / 2,
            WORLD / 2 - (self.y1 + 1) * size,
            WORLD / 2 - self.y0 * size,
        )


@dataclass
class MapPicture:
    png: bytes
    with_base_map: bool
    note: str = ""
    legend: list[tuple[str, str]] = field(default_factory=list)


TileSource = Callable[[Extent, int], Awaitable[tuple["BaseImage | None", str]]]


def mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05, min(85.05, lat))
    x = math.radians(lon) * EARTH_RADIUS
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS
    return x, y


def inverse_mercator(x: float, y: float) -> tuple[float, float]:
    lon = math.degrees(x / EARTH_RADIUS)
    lat = math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)
    return lon, lat


def metres_per_pixel(zoom: float) -> float:
    return WORLD / (TILE * 2**zoom)


def pressure_color(level: float | None) -> str:
    if level is None or not math.isfinite(level):
        return PRESSURE_RAMP[0]
    if level < 0.25:
        return PRESSURE_RAMP[0]
    if level < 0.75:
        return PRESSURE_RAMP[1]
    if level < 1.25:
        return PRESSURE_RAMP[2]
    if level < 2:
        return PRESSURE_RAMP[3]
    return PRESSURE_RAMP[4]


def extent_for(
    points: list[tuple[float, float]], width_px: int, height_px: int, padding: float = 0.12
) -> Extent | None:
    """The image extent that fits every point (lon, lat) with a margin, at the finest zoom
    MapTiler's static map draws it; None without points."""
    if not points:
        return None
    xs, ys = zip(*(mercator(lon, lat) for lon, lat in points), strict=True)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span_x = max(max(xs) - min(xs), 300.0) * (1 + 2 * padding)
    span_y = max(max(ys) - min(ys), 300.0) * (1 + 2 * padding)
    zoom = min(
        math.log2(WORLD * width_px / (TILE * span_x)),
        math.log2(WORLD * height_px / (TILE * span_y)),
    )
    zoom = math.floor(max(MIN_ZOOM, min(MAX_ZOOM, zoom)) * 100) / 100
    mpp = metres_per_pixel(zoom)
    half_w, half_h = width_px * mpp / 2, height_px * mpp / 2
    _, centre_lat = inverse_mercator(cx, cy)
    return Extent(cx - half_w, cx + half_w, cy - half_h, cy + half_h, zoom, centre_lat)


async def fetch_base_map(
    extent: Extent, width_px: int, height_px: int, key: str, referer: str
) -> tuple[BaseImage | None, str]:
    """MapTiler's static map at the extent's centre and zoom, or the reason there is none."""
    cx, cy = (extent.xmin + extent.xmax) / 2, (extent.ymin + extent.ymax) / 2
    lon, lat = inverse_mercator(cx, cy)
    url = STATIC_URL.format(lon=lon, lat=lat, zoom=extent.zoom, w=width_px, h=height_px)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                url,
                params={"key": key, "attribution": "false"},
                headers={"Referer": referer.rstrip("/") + "/", "User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as exc:
        log.warning("MapTiler static map not fetched", error=str(exc))
        return None, "MapTiler did not answer"
    if response.status_code == 403:
        # MapTiler says why in a header ("Access to rendered maps not allowed": the key's
        # allowed services exclude the Static Maps API, which the key's settings can allow)
        why = response.headers.get("statustext", "").removeprefix("403 ").strip()
        log.warning("MapTiler static map refused", status=response.status_code, reason=why)
        return None, (
            f"MapTiler refused this server's key ({why}); allow the Static Maps API for the key"
            if why
            else "MapTiler refused this server's key; allow the Static Maps API for the key"
        )
    if response.status_code != 200 or not response.headers.get("content-type", "").startswith(
        "image/"
    ):
        log.warning("MapTiler static map refused", status=response.status_code)
        return None, f"MapTiler answered {response.status_code}"
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    return BaseImage(image, extent.bounds, MAPTILER_ATTRIBUTION), ""


def tile_grid(extent: Extent, width_px: int) -> TileGrid:
    """The OpenStreetMap tiles covering the extent at the zoom whose pixels are at least as
    fine as the picture's, coarsened until at most `MAX_TILES` tiles are needed."""
    wanted = extent.width_m / width_px
    zoom = min(OSM_MAX_ZOOM, max(0, math.ceil(math.log2(WORLD / (OSM_TILE * wanted)))))
    while True:
        size = WORLD / 2**zoom
        x0 = math.floor((extent.xmin + WORLD / 2) / size)
        x1 = math.floor((extent.xmax + WORLD / 2) / size)
        y0 = math.floor((WORLD / 2 - extent.ymax) / size)
        y1 = math.floor((WORLD / 2 - extent.ymin) / size)
        limit = 2**zoom - 1
        grid = TileGrid(zoom, max(0, x0), min(limit, x1), max(0, y0), min(limit, y1))
        if grid.count <= MAX_TILES or zoom == 0:
            return grid
        zoom -= 1


def stitch_tiles(grid: TileGrid, tiles: dict[tuple[int, int], bytes]) -> BaseImage:
    """One picture from the tiles of a grid; a tile that did not arrive stays the ground colour."""
    columns, rows = grid.x1 - grid.x0 + 1, grid.y1 - grid.y0 + 1
    canvas = Image.new("RGB", (columns * OSM_TILE, rows * OSM_TILE), BACKGROUND)
    for (x, y), data in tiles.items():
        try:
            tile = Image.open(io.BytesIO(data)).convert("RGB")
        except OSError:
            continue
        canvas.paste(tile, ((x - grid.x0) * OSM_TILE, (y - grid.y0) * OSM_TILE))
    return BaseImage(canvas, grid.bounds, OSM_ATTRIBUTION)


async def fetch_osm_tiles(extent: Extent, width_px: int) -> tuple[BaseImage | None, str]:
    """The standard OpenStreetMap tiles under the extent, a few at a time with a proper user
    agent, or the reason there is none."""
    grid = tile_grid(extent, width_px)
    semaphore = asyncio.Semaphore(TILE_CONCURRENCY)
    tiles: dict[tuple[int, int], bytes] = {}
    failures: list[str] = []

    async def one(client: httpx.AsyncClient, x: int, y: int) -> None:
        async with semaphore:
            try:
                response = await client.get(OSM_TILE_URL.format(z=grid.zoom, x=x, y=y))
            except httpx.HTTPError as exc:
                failures.append(str(exc))
                return
            if response.status_code == 200:
                tiles[(x, y)] = response.content
            else:
                failures.append(str(response.status_code))

    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
            await asyncio.gather(
                *(
                    one(client, x, y)
                    for x in range(grid.x0, grid.x1 + 1)
                    for y in range(grid.y0, grid.y1 + 1)
                )
            )
    except httpx.HTTPError as exc:
        failures.append(str(exc))
    if not tiles:
        log.warning("OpenStreetMap tiles not fetched", zoom=grid.zoom, error=failures[:1])
        return None, "OpenStreetMap's tiles did not arrive"
    if failures:
        log.info("OpenStreetMap tiles partly missing", missing=len(failures), of=grid.count)
    return stitch_tiles(grid, tiles), ""


def _scale_bar_length(width_m: float, cos_lat: float) -> tuple[float, str]:
    """A round ground length about a fifth of the image, and its label."""
    target = width_m * cos_lat / 5
    for metres in (50, 100, 200, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000):
        if metres >= target:
            break
    else:
        metres = 100_000
    label = f"{metres / 1000:g} km" if metres >= 1000 else f"{metres} m"
    return metres, label


def draw_map(
    extent: Extent,
    base: BaseImage | None,
    tracks: list[TrackLine],
    shapes: list[Shape],
    *,
    width_px: int,
    height_px: int,
) -> bytes:
    """The picture: the base map (or a plain ground), the shapes, the tracks, a scale bar, a
    north arrow and the attribution, as PNG."""
    fig = Figure(figsize=(width_px / 100, height_px / 100), dpi=200)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    ax.set_xlim(extent.xmin, extent.xmax)
    ax.set_ylim(extent.ymin, extent.ymax)
    ax.set_aspect("equal")
    if base is not None:
        # the base image's own edges; the axes clip it to the extent
        ax.imshow(
            base.image, extent=base.bounds, aspect="equal", zorder=0, interpolation="bilinear"
        )
    else:
        ax.set_facecolor(BACKGROUND)
        fig.patch.set_facecolor(BACKGROUND)
    for item in shapes:
        _draw_shape(ax, item)
    for track in tracks:
        xy = [mercator(lon, lat) for lon, lat in zip(track.lon, track.lat, strict=True)]
        if len(xy) < 2:
            continue
        xs, ys = zip(*xy, strict=True)
        ax.plot(xs, ys, color=track.color, linewidth=0.9, alpha=0.9, zorder=5)
        ax.plot(xs[-1], ys[-1], marker="o", markersize=3, color=track.color, zorder=6)
    _decorate(ax, extent, base.attribution if base else None)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _draw_shape(ax: Any, item: Shape) -> None:
    geometry = item.geometry
    if geometry.geom_type == "Point":
        # a gateway heard: a marker sized by its share of the uplinks
        x, y = mercator(geometry.x, geometry.y)
        size = 4 + 10 * (item.level or 0)
        ax.plot(
            x,
            y,
            marker="o",
            markersize=size,
            color=item.color,
            markeredgecolor="white",
            markeredgewidth=0.8,
            alpha=0.9,
            zorder=7,
        )
        return
    polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    alpha = FILL_ALPHA.get(item.kind, 0.2)
    for polygon in polygons:
        if polygon.geom_type != "Polygon" or polygon.is_empty:
            continue
        xy = [mercator(x, y) for x, y in polygon.exterior.coords]
        xs, ys = zip(*xy, strict=True)
        ax.fill(xs, ys, color=item.color, alpha=alpha, zorder=2, linewidth=0)
        ax.plot(xs, ys, color=item.color, linewidth=0.8, zorder=3)


LABEL_BOX = {"boxstyle": "round,pad=0.15", "facecolor": "white", "alpha": 0.7, "linewidth": 0}


def _decorate(ax: Any, extent: Extent, attribution: str | None) -> None:
    cos_lat = max(0.2, math.cos(math.radians(extent.centre_lat)))
    metres, label = _scale_bar_length(extent.width_m, cos_lat)
    bar = metres / cos_lat
    x0 = extent.xmin + extent.width_m * 0.03
    y0 = extent.ymin + (extent.ymax - extent.ymin) * 0.05
    ax.plot([x0, x0 + bar], [y0, y0], color="#1F2A24", linewidth=2, zorder=10)
    ax.text(
        x0 + bar / 2,
        y0 + (extent.ymax - extent.ymin) * 0.012,
        label,
        ha="center",
        va="bottom",
        fontsize=6,
        color="#1F2A24",
        zorder=10,
        bbox=LABEL_BOX,
    )
    nx = extent.xmax - extent.width_m * 0.05
    ny = extent.ymax - (extent.ymax - extent.ymin) * 0.16
    ax.annotate(
        "",
        xy=(nx, ny + (extent.ymax - extent.ymin) * 0.09),
        xytext=(nx, ny),
        arrowprops={"arrowstyle": "-|>", "color": "#1F2A24", "linewidth": 1},
        zorder=10,
    )
    ax.text(nx, ny + (extent.ymax - extent.ymin) * 0.1, "N", ha="center", fontsize=7, zorder=10)
    ax.text(
        extent.xmax - extent.width_m * 0.01,
        extent.ymin + (extent.ymax - extent.ymin) * 0.012,
        attribution or "Drawn without a base map",
        ha="right",
        va="bottom",
        fontsize=5,
        color="#4B5651",
        zorder=10,
        bbox=LABEL_BOX,
    )


def shapes_from_geometries(
    rows: list[dict[str, Any]], subject_colors: dict[str, str]
) -> list[Shape]:
    """The result geometries as shapes: areas by their pressure, everything else in the
    subject's colour; the largest first, so small polygons draw on top."""
    shapes: list[Shape] = []
    for row in rows:
        geometry = shape(row["geojson"])
        if geometry.is_empty:
            continue
        kind = str(row.get("kind", ""))
        if kind == "area":
            color = pressure_color(row.get("level"))
        else:
            color = subject_colors.get(str(row.get("subject_id") or ""), "#B86B5C")
        level = row.get("level")
        shapes.append(
            Shape(
                geometry,
                color,
                kind,
                str(row.get("label", "")),
                float(level) if isinstance(level, int | float) else None,
            )
        )
    shapes.sort(key=lambda s: -s.geometry.area)
    return shapes


def points_of(tracks: list[TrackLine], shapes: list[Shape]) -> list[tuple[float, float]]:
    """The extent comes from the polygons when there are any (a track may hold a far outlier),
    else from the tracks."""
    points: list[tuple[float, float]] = []
    for item in shapes:
        minx, miny, maxx, maxy = item.geometry.bounds
        points += [(minx, miny), (maxx, maxy)]
    if points:
        return points
    for track in tracks:
        points += list(zip(track.lon, track.lat, strict=True))
    return points


async def map_picture(
    tracks: list[TrackLine],
    shapes: list[Shape],
    *,
    maptiler_key: str | None,
    referer: str,
    width_px: int = 1000,
    height_px: int = 620,
    tile_source: TileSource | None = fetch_osm_tiles,
) -> MapPicture | None:
    """The whole picture, or None when there is nothing to draw. MapTiler when the key allows
    it, OpenStreetMap's tiles otherwise (`tile_source`, None to skip them), a plain ground last;
    the note says why when the base map is missing."""
    extent = extent_for(points_of(tracks, shapes), width_px, height_px)
    if extent is None:
        return None
    base: BaseImage | None = None
    reasons: list[str] = []
    if maptiler_key:
        base, reason = await fetch_base_map(extent, width_px, height_px, maptiler_key, referer)
        if base is None:
            reasons.append(reason)
    if base is None and tile_source is not None:
        base, reason = await tile_source(extent, width_px)
        if base is None:
            reasons.append(reason)
    png = draw_map(extent, base, tracks, shapes, width_px=width_px, height_px=height_px)
    note = "" if base is not None else "The base map is not drawn: " + "; ".join(reasons) + "."
    return MapPicture(png=png, with_base_map=base is not None, note=note)
