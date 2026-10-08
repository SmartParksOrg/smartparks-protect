"""The pure parts of the habitat selection module (phase 41, decisions D313 to D317): the
area and the grid of a run, the raster stack hrHSA reads, the fixes as the GeoDataFrame it
takes, the fit, the validation and the surface read onto cells. Everything that needs hrHSA,
rasterio or pyproj is imported inside the function that needs it, so the lean API imports
this module for its types and the worker's image runs it (decision D318)."""

from __future__ import annotations

import io
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from shared.analysis.base import ModuleUnavailable
from shared.analysis.limits import MAX_RASTER_CELLS, MAX_SURFACE_CELLS
from shared.analysis.primitives.spatial import LocalGrid, utm_srid
from shared.analysis.primitives.trajectory import Trajectory

UNAVAILABLE = (
    "the analysis worker is not built with hrHSA: the habitat selection module needs the "
    "analysis image (docker/analysis.Dockerfile, decision D314)"
)
#: hrHSA's own minimum for an availability domain.
MIN_FIXES_DOMAIN = 5


def require_engine() -> None:
    """Raise `ModuleUnavailable` where hrHSA or its stack is not installed."""
    try:
        import hsa.rsf  # noqa: F401
        import rasterio  # noqa: F401
        import rioxarray  # noqa: F401
    except ImportError as exc:
        raise ModuleUnavailable(UNAVAILABLE) from exc


@dataclass(frozen=True, slots=True)
class Grid:
    """The run's raster grid: a UTM zone, a resolution in metres and an extent in that CRS,
    with the same extent in WGS84 for the providers."""

    epsg: int
    resolution_m: float
    west: float
    south: float
    east: float
    north: float
    bbox_wgs84: tuple[float, float, float, float]

    @property
    def width(self) -> int:
        return max(1, math.ceil((self.east - self.west) / self.resolution_m))

    @property
    def height(self) -> int:
        return max(1, math.ceil((self.north - self.south) / self.resolution_m))

    @property
    def cells(self) -> int:
        return self.width * self.height

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)


def _to_utm(lat: NDArray[np.float64], lon: NDArray[np.float64], epsg: int) -> tuple[Any, Any]:
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)


def mcp_ring(
    x: NDArray[np.float64], y: NDArray[np.float64], quantile: float
) -> list[tuple[float, float]] | None:
    """hrHSA's availability domain for one animal, computed the same way so the grid covers
    it: the convex hull of the fixes within the quantile of the distances to their centroid.
    None below five fixes, as hrHSA refuses it."""
    import shapely

    if x.shape[0] < MIN_FIXES_DOMAIN:
        return None
    cx, cy = float(np.mean(x)), float(np.mean(y))
    distance = np.hypot(x - cx, y - cy)
    keep = distance <= np.quantile(distance, quantile)
    if int(keep.sum()) < MIN_FIXES_DOMAIN:
        return None
    hull = shapely.MultiPoint(np.column_stack([x[keep], y[keep]])).convex_hull
    if hull.is_empty or hull.geom_type != "Polygon":
        return None
    return [(float(px), float(py)) for px, py in hull.exterior.coords]


def grid_for(
    tracks: Sequence[Trajectory],
    *,
    quantile: float,
    buffer_m: float,
    finest_m: float,
    max_cells: int = MAX_RASTER_CELLS,
) -> Grid:
    """The grid of a run: the UTM zone of the fixes' centroid, the union of the animals'
    domains buffered, snapped to the resolution, which doubles until the cells fit the bound
    (architecture 13.10: a large park answers coarser rather than refusing)."""
    lat = np.concatenate([t.lat for t in tracks if len(t)])
    lon = np.concatenate([t.lon for t in tracks if len(t)])
    if lat.shape[0] == 0:
        raise ValueError("no fixes to build a grid from")
    epsg = utm_srid(float(np.mean(lat)), float(np.mean(lon)))
    west = south = math.inf
    east = north = -math.inf
    for track in tracks:
        if not len(track):
            continue
        x, y = _to_utm(track.lat, track.lon, epsg)
        ring = mcp_ring(x, y, quantile)
        xs, ys = (
            (x, y)
            if ring is None
            else (np.array([p[0] for p in ring]), np.array([p[1] for p in ring]))
        )
        west, east = min(west, float(xs.min())), max(east, float(xs.max()))
        south, north = min(south, float(ys.min())), max(north, float(ys.max()))
    west, south, east, north = west - buffer_m, south - buffer_m, east + buffer_m, north + buffer_m
    resolution = finest_m
    while True:
        w = math.ceil((east - west) / resolution)
        h = math.ceil((north - south) / resolution)
        if w * h <= max_cells:
            break
        resolution *= 2
    # snap the extent outward to whole cells, so the grid's origin is a multiple of the step
    west_s = math.floor(west / resolution) * resolution
    south_s = math.floor(south / resolution) * resolution
    east_s = math.ceil(east / resolution) * resolution
    north_s = math.ceil(north / resolution) * resolution
    from pyproj import Transformer

    back = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    corners_x = np.array([west_s, east_s, east_s, west_s])
    corners_y = np.array([south_s, south_s, north_s, north_s])
    lons, lats = back.transform(corners_x, corners_y)
    pad = 0.002  # a little beyond the corners, so a provider's tile edge never cuts the grid
    return Grid(
        epsg=epsg,
        resolution_m=float(resolution),
        west=float(west_s),
        south=float(south_s),
        east=float(east_s),
        north=float(north_s),
        bbox_wgs84=(
            float(np.min(lons)) - pad,
            float(np.min(lats)) - pad,
            float(np.max(lons)) + pad,
            float(np.max(lats)) + pad,
        ),
    )


def empty_stack(grid: Grid) -> Any:
    """A DataArray of the grid with no bands yet, carrying the CRS and the transform."""
    import rioxarray  # noqa: F401
    import xarray as xr

    x = grid.west + grid.resolution_m * (np.arange(grid.width) + 0.5)
    y = grid.north - grid.resolution_m * (np.arange(grid.height) + 0.5)
    template = xr.DataArray(
        np.zeros((grid.height, grid.width), dtype=np.float32),
        dims=("y", "x"),
        coords={"y": y, "x": x},
    )
    return template.rio.write_crs(f"EPSG:{grid.epsg}")


def layer_from_geotiff(data: bytes, grid: Grid, *, categorical: bool = False) -> Any:
    """A GeoTIFF's first band reprojected onto the run's grid (bilinear for a number, nearest
    for classes), nodata as NaN, as a (y, x) DataArray."""
    import rioxarray
    from rasterio.enums import Resampling

    template = empty_stack(grid)
    with rioxarray.open_rasterio(io.BytesIO(data), masked=True) as source:
        band = source.isel(band=0)
        resampled = band.rio.reproject_match(
            template, resampling=Resampling.nearest if categorical else Resampling.bilinear
        )
    values = np.asarray(resampled.values, dtype=np.float32)
    nodata = resampled.rio.nodata
    if nodata is not None and not np.isnan(nodata):
        values = np.where(values == nodata, np.nan, values)
    return template.copy(data=values)


def slope_from_elevation(elevation: Any) -> Any:
    """The slope in degrees from an elevation layer on a metric grid (Horn's method over the
    eight neighbours, the cell size from the coordinates)."""
    z = np.asarray(elevation.values, dtype=np.float64)
    x = np.asarray(elevation["x"].values)
    y = np.asarray(elevation["y"].values)
    dx = float(abs(x[1] - x[0])) if x.shape[0] > 1 else 1.0
    dy = float(abs(y[1] - y[0])) if y.shape[0] > 1 else 1.0
    filled = np.where(np.isnan(z), np.nanmean(z) if np.isfinite(np.nanmean(z)) else 0.0, z)
    padded = np.pad(filled, 1, mode="edge")
    a, b, c = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    d, f = padded[1:-1, :-2], padded[1:-1, 2:]
    g, h, i = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * dx)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * dy)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype(np.float32)
    slope = np.where(np.isnan(z), np.nan, slope)
    return elevation.copy(data=slope)


def distance_layer(grid: Grid, geometries: Sequence[dict[str, Any]]) -> Any:
    """The distance in metres from each cell's centre to the nearest of the geometries
    (GeoJSON in WGS84), on the run's grid, through a shapely tree in the grid's CRS."""
    import shapely
    from pyproj import Transformer
    from shapely.ops import transform as shapely_transform

    template = empty_stack(grid)
    if not geometries:
        return template.copy(data=np.full((grid.height, grid.width), np.nan, dtype=np.float32))
    forward = Transformer.from_crs("EPSG:4326", f"EPSG:{grid.epsg}", always_xy=True)
    shapes = [shapely_transform(forward.transform, shapely.geometry.shape(g)) for g in geometries]
    tree = shapely.STRtree(shapes)
    xs, ys = np.meshgrid(template["x"].values, template["y"].values)
    points = shapely.points(xs.ravel(), ys.ravel())
    _, distances = tree.query_nearest(points, return_distance=True, all_matches=False)
    values = np.asarray(distances, dtype=np.float32).reshape(grid.height, grid.width)
    return template.copy(data=values)


def stack_layers(grid: Grid, layers: dict[str, Any]) -> Any:
    """The (band, y, x) DataArray hrHSA samples and predicts on, bands in the order given."""
    import xarray as xr

    names = list(layers)
    arrays = [layers[name].expand_dims(band=[name]) for name in names]
    stack = xr.concat(arrays, dim="band").transpose("band", "y", "x")
    return stack.rio.write_crs(f"EPSG:{grid.epsg}")


def relocations(tracks: Sequence[Trajectory], names: dict[uuid.UUID, str], epsg: int) -> Any:
    """The fixes as the GeoDataFrame hrHSA takes: `entity_id`, a timezone-aware `time`, the
    point in the grid's CRS."""
    import geopandas as gpd
    import pandas as pd

    frames = []
    for track in tracks:
        if not len(track):
            continue
        x, y = _to_utm(track.lat, track.lon, epsg)
        frames.append(
            pd.DataFrame(
                {
                    "entity_id": str(track.entity_id),
                    "time": pd.to_datetime(track.times, unit="s", utc=True),
                    "x": x,
                    "y": y,
                }
            )
        )
    if not frames:
        raise ValueError("no fixes")
    df = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x, df.y), crs=f"EPSG:{epsg}")


@dataclass(slots=True)
class Coefficient:
    term: str
    estimate: float
    std_error: float | None
    p_value: float | None
    lower: float | None
    upper: float | None


@dataclass(slots=True)
class Fold:
    """One held-out animal of the leave-one-individual-out validation."""

    subject_id: uuid.UUID
    boyce: float | None
    test_fixes: int
    train_fixes: int
    error: str | None
    #: The Boyce curve: the predicted selection per bin against the observed to expected
    #: ratio, as (rsf_mid, pe) pairs.
    curve: list[tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True)
class Fit:
    coefficients: list[Coefficient]
    #: The scaler's mean and spread per linear predictor, so a reader can go back to units.
    scaling: dict[str, tuple[float, float]]
    used: int
    available: int
    converged: bool
    log_likelihood: float | None
    folds: list[Fold] = field(default_factory=list)
    #: The selection surface on the grid, (y, x), NaN outside the layers.
    surface: Any = None
    #: The value each fifth of the surface's cells starts at, once read onto cells.
    breaks: list[float] = field(default_factory=list)


def _f(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fit_rsf(
    reloc: Any,
    env: Any,
    *,
    linear: Sequence[str],
    quadratic: Sequence[str],
    categorical: Sequence[str],
    domain_quantile: float,
    sampling_factor: int,
    thin_hours: float | None,
    loio: bool,
    seed: int = 42,
) -> Fit:
    """The pooled frequentist RSF through hrHSA, its coefficients, the LOIO validation when
    asked, and the surface. The names of the ids are strings of the entities' ids."""
    require_engine()
    from hsa.rsf import FrequentistRSF, LeaveOneIndividualOut
    from hsa.types import FeatureSpec

    spec = FeatureSpec(
        linear=list(linear), quadratic=list(quadratic), categorical=list(categorical)
    )
    rsf = FrequentistRSF(
        reloc,
        env,
        spec=spec,
        id_col="entity_id",
        timestamp_col="time",
        domain_quantile=domain_quantile,
    )
    thin = f"{thin_hours}h" if thin_hours else None
    fitted = rsf.fit(sampling_factor=sampling_factor, thin_dt=thin, seed=seed)
    table = fitted.coefficients()
    coefficients = [
        Coefficient(
            term=str(row.term),
            estimate=float(row.estimate),
            std_error=_f(getattr(row, "std_error", None)),
            p_value=_f(getattr(row, "p_value", None)),
            lower=_f(getattr(row, "lower", None)),
            upper=_f(getattr(row, "upper", None)),
        )
        for row in table.itertuples(index=False)
    ]
    scaler = fitted.scaler
    scaling = {
        name: (float(scaler.mean_[i]), float(scaler.scale_[i])) for i, name in enumerate(linear)
    }
    model = fitted.model
    used = int(np.sum(np.asarray(model.model.endog) == 1)) if hasattr(model, "model") else 0
    available = int(model.model.endog.shape[0]) - used if hasattr(model, "model") else 0
    converged = bool(
        getattr(getattr(model, "mle_retvals", {}), "get", lambda *_: True)("converged", True)
    )
    fit = Fit(
        coefficients=coefficients,
        scaling=scaling,
        used=used,
        available=available,
        converged=converged,
        log_likelihood=_f(getattr(model, "llf", None)),
    )
    if loio:
        scheme = LeaveOneIndividualOut(
            heldout="all",
            thin_train_dt=thin,
            thin_test_dt=None,
            sampling_factor_train=sampling_factor,
            n_background=50_000,
            n_bins=10,
            seed=seed,
        )
        result = rsf.validate(scheme)
        bins = result.boyce_bins
        for row in result.summary.itertuples(index=False):
            held = str(row.heldout_ID)
            curve: list[tuple[float, float]] = []
            if len(bins) and "heldout_ID" in bins.columns:
                part = bins[bins["heldout_ID"].astype(str) == held]
                curve = [
                    (float(a), float(b))
                    for a, b in zip(part["rsf_mid"], part["pe"], strict=True)
                    if math.isfinite(float(a)) and math.isfinite(float(b))
                ]
            fit.folds.append(
                Fold(
                    subject_id=uuid.UUID(held),
                    boyce=_f(row.boyce),
                    test_fixes=int(getattr(row, "n_test_used", 0)),
                    train_fixes=int(getattr(row, "n_train_used_fitted", 0)),
                    error=str(row.error) if getattr(row, "error", None) else None,
                    curve=curve,
                )
            )
    surface = fitted.predict_surface(env)
    fit.surface = surface.isel(band=0)
    return fit


@dataclass(frozen=True, slots=True)
class SurfaceCells:
    """The surface read onto the analysis grid's cells: per cell its mean selection and its
    rank in fifths (decision D251), with the grid the page draws them on."""

    grid: LocalGrid
    cells: list[tuple[int, int, float, int]]
    breaks: list[float]


def surface_cells(
    surface: Any,
    grid: Grid,
    centre_lat: float,
    centre_lon: float,
    *,
    max_cells: int = MAX_SURFACE_CELLS,
) -> SurfaceCells:
    """The surface's mean per cell of a LocalGrid over the run's area, the cell size doubled
    from the raster's resolution until the cells fit the bound; each cell's rank as a fifth."""
    from pyproj import Transformer

    values = np.asarray(surface.values, dtype=np.float64)
    x = np.asarray(surface["x"].values)
    y = np.asarray(surface["y"].values)
    to_wgs = Transformer.from_crs(f"EPSG:{grid.epsg}", "EPSG:4326", always_xy=True)
    xs, ys = np.meshgrid(x, y)
    lons, lats = to_wgs.transform(xs.ravel(), ys.ravel())
    lons = np.asarray(lons, dtype=np.float64)
    lats = np.asarray(lats, dtype=np.float64)
    flat = values.ravel()
    ok = np.isfinite(flat)
    cell_m = grid.resolution_m
    while True:
        local = LocalGrid(centre_lat, centre_lon, cell_m)
        ix, iy = local.cells_of(lats[ok], lons[ok])
        keys = np.unique(np.column_stack([ix, iy]), axis=0)
        if keys.shape[0] <= max_cells or cell_m >= 5_000:
            break
        cell_m *= 2
    sums: dict[tuple[int, int], tuple[float, int]] = {}
    for key_x, key_y, value in zip(ix, iy, flat[ok], strict=True):
        total, count = sums.get((int(key_x), int(key_y)), (0.0, 0))
        sums[(int(key_x), int(key_y))] = (total + float(value), count + 1)
    means = [(kx, ky, total / count) for (kx, ky), (total, count) in sums.items()]
    if not means:
        return SurfaceCells(grid=local, cells=[], breaks=[])
    ordered = sorted(means, key=lambda m: m[2])
    n = len(ordered)
    ranked: list[tuple[int, int, float, int]] = []
    for position, (kx, ky, mean) in enumerate(ordered):
        ranked.append((kx, ky, round(mean, 6), min(4, position * 5 // n)))
    breaks = [ordered[min(n - 1, level * n // 5)][2] for level in range(5)]
    return SurfaceCells(grid=local, cells=ranked, breaks=[round(b, 6) for b in breaks])


def ring_wgs84(ring: Sequence[tuple[float, float]], epsg: int) -> list[list[float]]:
    from pyproj import Transformer

    back = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    xs = np.array([p[0] for p in ring])
    ys = np.array([p[1] for p in ring])
    lons, lats = back.transform(xs, ys)
    return [[round(float(a), 6), round(float(b), 6)] for a, b in zip(lons, lats, strict=True)]


def now() -> datetime:
    return datetime.now(UTC)
