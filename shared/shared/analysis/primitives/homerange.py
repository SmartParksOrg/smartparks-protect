"""Home range (docs/ANALYTICS_PHASE1_PLAN.md, section 8.2): the minimum convex polygon of the
fixes inside a percentile of distance from their centre, and a Gaussian kernel density on a
grid with its 50 and 95 percent isopleths as unions of cells. numpy and shapely only; the
kernel is applied by FFT convolution over the binned fixes, so a year of fixes costs the same
as a week."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import MultiPoint, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from shared.analysis.primitives.spatial import M_PER_DEG_LAT, LocalGrid
from shared.analysis.primitives.trajectory import haversine_array


def _frame(lat: NDArray[np.float64], lon: NDArray[np.float64]) -> LocalGrid:
    return LocalGrid(float(np.mean(lat)), float(np.mean(lon)), 1.0)


def _metres(
    grid: LocalGrid, lat: NDArray[np.float64], lon: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x = (lon - grid.origin_lon) * grid.m_per_deg_lon
    y = (lat - grid.origin_lat) * M_PER_DEG_LAT
    return x, y


def _degrees(grid: LocalGrid, geometry: BaseGeometry) -> BaseGeometry:
    from shapely.ops import transform

    return transform(
        lambda x, y, z=None: (
            grid.origin_lon + x / grid.m_per_deg_lon,
            grid.origin_lat + y / M_PER_DEG_LAT,
        ),
        geometry,
    )


@dataclass(slots=True)
class HomeRange:
    """One isopleth: the polygon in degrees, its level and its planar area in hectares (the
    runner stores the geodesic one from PostGIS)."""

    level: float
    geometry: BaseGeometry
    hectares: float


def mcp(lat: NDArray[np.float64], lon: NDArray[np.float64], percent: float = 95) -> HomeRange:
    """The convex hull of the fixes inside `percent` of the distances from the centroid."""
    centre_lat, centre_lon = float(np.mean(lat)), float(np.mean(lon))
    distance = haversine_array(
        np.full(lat.shape, centre_lat), np.full(lon.shape, centre_lon), lat, lon
    )
    cut = float(np.percentile(distance, percent))
    keep = distance <= cut
    grid = _frame(lat[keep], lon[keep])
    x, y = _metres(grid, lat[keep], lon[keep])
    hull = MultiPoint(np.column_stack([x, y])).convex_hull
    return HomeRange(percent / 100, _degrees(grid, hull), hull.area / 10_000)


def reference_bandwidth(lat: NDArray[np.float64], lon: NDArray[np.float64]) -> float:
    """The reference (Silverman, Worton) bandwidth in metres: the mean standard deviation of
    the coordinates scaled by the count."""
    grid = _frame(lat, lon)
    x, y = _metres(grid, lat, lon)
    sigma = math.sqrt((float(np.var(x)) + float(np.var(y))) / 2)
    return float(max(1.0, sigma * len(x) ** (-1 / 6)))


@dataclass(slots=True)
class KdeGrid:
    grid: LocalGrid
    ix0: int
    iy0: int
    density: NDArray[np.float64]  # [rows (y), columns (x)], sums to 1
    bandwidth_m: float
    cell_m: float


def kde_grid(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    bandwidth_m: float,
    max_cells: int,
    weights: NDArray[np.float64] | None = None,
) -> KdeGrid:
    """The kernel density of the (weighted) fixes on a square grid of at most `max_cells`
    cells a side covering the fixes and three bandwidths around them."""
    grid = _frame(lat, lon)
    x, y = _metres(grid, lat, lon)
    pad = 3 * bandwidth_m
    x0, x1 = float(x.min()) - pad, float(x.max()) + pad
    y0, y1 = float(y.min()) - pad, float(y.max()) + pad
    cell = max((x1 - x0) / max_cells, (y1 - y0) / max_cells, bandwidth_m / 4, 1.0)
    frame = LocalGrid(grid.origin_lat, grid.origin_lon, cell)
    ix0, iy0 = math.floor(x0 / cell), math.floor(y0 / cell)
    nx, ny = math.ceil(x1 / cell) - ix0 + 1, math.ceil(y1 / cell) - iy0 + 1
    ix = np.floor(x / cell).astype(np.int64) - ix0
    iy = np.floor(y / cell).astype(np.int64) - iy0
    counts = np.zeros((ny, nx), dtype=np.float64)
    np.add.at(counts, (iy, ix), weights if weights is not None else 1.0)
    # the kernel on the same cell size, four bandwidths each way
    reach = max(1, math.ceil(4 * bandwidth_m / cell))
    offsets = (np.arange(-reach, reach + 1) * cell) ** 2
    kernel = np.exp(-(offsets[:, None] + offsets[None, :]) / (2 * bandwidth_m**2))
    kernel /= kernel.sum()
    density = _convolve(counts, kernel)
    density = np.clip(density, 0, None)
    total = density.sum()
    if total > 0:
        density /= total
    return KdeGrid(frame, ix0, iy0, density, bandwidth_m, cell)


def _convolve(field: NDArray[np.float64], kernel: NDArray[np.float64]) -> NDArray[np.float64]:
    """Same-size convolution through the FFT, zero padded."""
    ky, kx = kernel.shape
    fy, fx = field.shape
    shape = (fy + ky - 1, fx + kx - 1)
    out = np.fft.irfft2(np.fft.rfft2(field, shape) * np.fft.rfft2(kernel, shape), shape)
    oy, ox = ky // 2, kx // 2
    result: NDArray[np.float64] = out[oy : oy + fy, ox : ox + fx]
    return result


def isopleths(kde: KdeGrid, levels: list[float]) -> list[HomeRange]:
    """For each level, the union of the densest cells that together hold that share of the
    volume, as one polygon (possibly multi), lightly simplified."""
    flat = kde.density.ravel()
    order = np.argsort(flat)[::-1]
    cumulative = np.cumsum(flat[order])
    out = []
    for level in levels:
        n_cells = int(np.searchsorted(cumulative, level, side="left")) + 1
        mask = np.zeros(flat.shape, dtype=np.bool_)
        mask[order[:n_cells]] = True
        mask2 = mask.reshape(kde.density.shape)
        boxes = []
        cell = kde.cell_m
        for row in range(len(mask2)):
            cols = np.where(mask2[row])[0]
            if cols.size == 0:
                continue
            # contiguous runs of cells become one rectangle
            breaks = np.where(np.diff(cols) > 1)[0] + 1
            for run in np.split(cols, breaks):
                x_start = (kde.ix0 + int(run[0])) * cell
                x_end = (kde.ix0 + int(run[-1]) + 1) * cell
                # edges from the index, never by adding a cell: rows must share exact edges
                y_start = (kde.iy0 + row) * cell
                y_end = (kde.iy0 + row + 1) * cell
                boxes.append(box(x_start, y_start, x_end, y_end))
        shape = make_valid(unary_union(boxes).simplify(cell / 2, preserve_topology=True))
        out.append(HomeRange(level, _degrees(kde.grid, shape), shape.area / 10_000))
    return out
