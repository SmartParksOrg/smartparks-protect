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


# --- the autocorrelation-corrected range (docs/ANALYTICS_PHASE2_PLAN.md, section 3, D244) ---
#
# A plain KDE takes every fix as an independent draw from the range. Hourly fixes of an animal
# whose position takes two days to decorrelate are nothing of the kind: a month of them is a few
# dozen independent looks at the range, not seven hundred, and the range they cover is smaller
# than the one the animal uses. The correction below is our own approximation and is named as
# such: a variogram of the fixes, an Ornstein-Uhlenbeck fit to it, the effective sample size
# that follows, and a bandwidth chosen from those instead of from the fix count. It is not the
# AKDE of the reference implementation, which fits a continuous-time movement model of its own.

#: Index lags at which pairs of fixes are compared, up to the count of fixes: enough to draw the
#: rise of the variogram and its plateau without the square of the fixes in pairs.
_LAG_STEPS = 48
#: Bins of time lag, log spaced, into which the pairs fall.
_LAG_BINS = 24
#: Candidate autocorrelation times tried against the variogram, log spaced over the lags seen.
_TAU_GRID = 160


@dataclass(slots=True)
class Variogram:
    """Mean squared displacement between fixes a lag apart, halved (the semivariance), binned
    by lag. `pairs` is how many pairs each bin holds, which weights the fit."""

    lag_s: NDArray[np.float64]
    semivariance_m2: NDArray[np.float64]
    pairs: NDArray[np.int64]


@dataclass(slots=True)
class CorrectedRange:
    """What the fixes say about their own autocorrelation, and the bandwidth that follows.

    `stationary` is False when the fixes do not settle into a range over the period: the
    variogram keeps rising like a random walk's, or the autocorrelation time is longer than
    half the period. Then there is no range to estimate and `reason` says so; the caller
    reports it instead of a number."""

    stationary: bool
    reason: str | None
    autocorrelation_s: float | None
    range_variance_m2: float | None  # per axis, the variogram's plateau halved
    effective_fixes: float | None
    bandwidth_m: float | None
    variogram: Variogram


def variogram(
    times: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    max_lag_s: float,
) -> Variogram:
    """The semivariogram of the fixes over lags up to `max_lag_s`.

    Pairs are taken at a ladder of index lags rather than over every pair, so a year of hourly
    fixes costs a few dozen passes over the arrays and not the square of them; the pairs are
    then binned by the time lag they actually span, which is what makes irregular sampling
    harmless. Only the lags the sampling reaches are drawn."""
    n = len(times)
    if n < 3:
        empty = np.zeros(0, dtype=np.float64)
        return Variogram(empty, empty, np.zeros(0, dtype=np.int64))
    grid = _frame(lat, lon)
    x, y = _metres(grid, lat, lon)
    ladder = np.unique(np.geomspace(1, max(1, n - 1), _LAG_STEPS).astype(np.int64))
    lags: list[NDArray[np.float64]] = []
    halves: list[NDArray[np.float64]] = []
    for k in ladder:
        dt = times[k:] - times[:-k]
        keep = (dt > 0) & (dt <= max_lag_s)
        if not np.any(keep):
            continue
        d2 = (x[k:] - x[:-k]) ** 2 + (y[k:] - y[:-k]) ** 2
        lags.append(dt[keep])
        halves.append(d2[keep] / 2)
    if not lags:
        empty = np.zeros(0, dtype=np.float64)
        return Variogram(empty, empty, np.zeros(0, dtype=np.int64))
    lag = np.concatenate(lags)
    half = np.concatenate(halves)
    edges = np.geomspace(float(lag.min()), float(lag.max()) * 1.0001, _LAG_BINS + 1)
    which = np.clip(np.searchsorted(edges, lag, side="right") - 1, 0, _LAG_BINS - 1)
    counts = np.bincount(which, minlength=_LAG_BINS)
    filled = counts > 0
    mean_lag = np.bincount(which, weights=lag, minlength=_LAG_BINS)[filled] / counts[filled]
    mean_half = np.bincount(which, weights=half, minlength=_LAG_BINS)[filled] / counts[filled]
    return Variogram(mean_lag, mean_half, counts[filled].astype(np.int64))


def _ou_fit(v: Variogram) -> tuple[float, float, float]:
    """The Ornstein-Uhlenbeck semivariogram s (1 - exp(-lag / tau)) fitted by weighted least
    squares: for each candidate tau the plateau s is linear and solved outright, and the tau
    with the least residual wins. Returns (tau, s, residual)."""
    w = v.pairs.astype(np.float64)
    best: tuple[float, float, float] | None = None
    for tau in np.geomspace(float(v.lag_s.min()) / 4, float(v.lag_s.max()) * 4, _TAU_GRID):
        f = 1 - np.exp(-v.lag_s / tau)
        denominator = float(np.sum(w * f * f))
        if denominator <= 0:
            continue
        s = float(np.sum(w * v.semivariance_m2 * f)) / denominator
        residual = float(np.sum(w * (v.semivariance_m2 - s * f) ** 2))
        if best is None or residual < best[2]:
            best = (float(tau), s, residual)
    assert best is not None
    return best


def _brownian_fit(v: Variogram) -> float:
    """The residual of a variogram that never levels off, s = b lag: what a random walk or an
    animal that left its range leaves behind. Compared against the OU fit."""
    w = v.pairs.astype(np.float64)
    denominator = float(np.sum(w * v.lag_s**2))
    if denominator <= 0:
        return float("inf")
    b = float(np.sum(w * v.semivariance_m2 * v.lag_s)) / denominator
    return float(np.sum(w * (v.semivariance_m2 - b * v.lag_s) ** 2))


def effective_sample_size(n: int, interval_s: float, tau_s: float) -> float:
    """How many independent fixes `n` fixes at `interval_s` are worth when the position
    decorrelates over `tau_s`: n over one plus twice the summed autocorrelation at the lags
    between them, each weighted by how many pairs sit that far apart (the usual form for a
    correlated series, with the exponential correlation the OU process has)."""
    if n <= 1:
        return float(max(n, 0))
    k = np.arange(1, n, dtype=np.float64)
    rho = np.exp(-k * interval_s / tau_s)
    inflation = 1 + 2 * float(np.sum((1 - k / n) * rho))
    return float(max(1.0, n / inflation))


def corrected_range(
    times: NDArray[np.float64],
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    period_s: float,
) -> CorrectedRange:
    """The autocorrelation figures of a track and the bandwidth its corrected KDE should use:
    the reference rule with the effective sample size in place of the fix count and the range
    variance the fit found in place of the sample's. Few independent looks at a range call for
    a wide kernel, which supplies what the fixes did not reach; with many, this is the plain
    reference rule again.

    A range counts as shown only when the variogram's plateau lies inside the lags drawn (a
    quarter of the period): the autocorrelation time must be at most an eighth of the period,
    so the plateau is measured and not extrapolated from a curve still rising. That is
    stricter than the plan's half, deliberately: over a month a random walk and a range that
    takes a week to cross fit the same rising curve, and the difference between them is the
    whole question."""
    n = len(times)
    v = variogram(times, lat, lon, max_lag_s=period_s / 4)
    if len(v.lag_s) < 4 or n < 10:
        return CorrectedRange(False, "too few fixes for a variogram", None, None, None, None, v)
    tau, s, residual = _ou_fit(v)
    if s <= 0 or not math.isfinite(residual):
        return CorrectedRange(False, "the variogram could not be fitted", None, None, None, None, v)
    if _brownian_fit(v) <= residual:
        return CorrectedRange(
            False,
            "the fixes keep spreading over the period instead of settling into a range",
            tau,
            None,
            None,
            None,
            v,
        )
    if tau > period_s / 8:
        return CorrectedRange(
            False,
            "the position takes too long to decorrelate for the period to show the whole "
            "range: the fixes are still spreading at the longest lags drawn",
            tau,
            None,
            None,
            None,
            v,
        )
    interval = float(np.median(np.diff(times))) if n > 1 else period_s
    n_eff = effective_sample_size(n, max(interval, 1.0), tau)
    variance = s / 2  # per axis: the plateau is the sum of two axes' variances
    bandwidth = max(1.0, math.sqrt(variance) * n_eff ** (-1 / 6))
    return CorrectedRange(True, None, tau, variance, n_eff, bandwidth, v)
