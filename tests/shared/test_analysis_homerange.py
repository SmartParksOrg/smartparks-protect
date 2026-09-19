"""Home range on known shapes (docs/ANALYTICS_PHASE1_PLAN.md, section 17): the MCP of a
square is that square, the KDE of a Gaussian cloud has the analytic 95 percent area."""

import math

import numpy as np
import pytest
from shapely.geometry import Point

from shared.analysis.limits import KDE_MAX_CELLS
from shared.analysis.primitives.homerange import isopleths, kde_grid, mcp, reference_bandwidth

LAT, LON = -19.0, 23.5
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(LAT))


def test_the_mcp_of_a_square_is_that_square():
    side = 1000.0
    dlat, dlon = side / M_PER_DEG_LAT, side / M_PER_DEG_LON
    lat = np.array([LAT, LAT + dlat, LAT + dlat, LAT, LAT + dlat / 2])
    lon = np.array([LON, LON, LON + dlon, LON + dlon, LON + dlon / 2])
    hull = mcp(lat, lon, percent=100)
    assert hull.level == 1 and hull.geometry.geom_type == "Polygon"
    assert hull.hectares == pytest.approx(100, rel=0.01)
    minx, miny, maxx, maxy = hull.geometry.bounds
    assert minx == pytest.approx(LON, abs=1e-6) and maxy == pytest.approx(LAT + dlat, abs=1e-6)
    assert maxx == pytest.approx(LON + dlon, abs=1e-6) and miny == pytest.approx(LAT, abs=1e-6)


def test_a_far_fix_is_outside_the_95_percent_mcp():
    rng = np.random.default_rng(1)
    n = 200
    lat = LAT + rng.normal(0, 300, n) / M_PER_DEG_LAT
    lon = LON + rng.normal(0, 300, n) / M_PER_DEG_LON
    lat[0] += 0.5  # 55 km away
    full = mcp(lat, lon, percent=100)
    core = mcp(lat, lon, percent=95)
    assert core.hectares < full.hectares / 10


def test_the_kde_of_a_gaussian_cloud_has_the_analytic_area():
    rng = np.random.default_rng(7)
    n, sigma = 5000, 500.0
    lat = LAT + rng.normal(0, sigma, n) / M_PER_DEG_LAT
    lon = LON + rng.normal(0, sigma, n) / M_PER_DEG_LON
    h = reference_bandwidth(lat, lon)
    assert h == pytest.approx(sigma * n ** (-1 / 6), rel=0.05)
    kde = kde_grid(lat, lon, h, KDE_MAX_CELLS)
    assert max(kde.density.shape) <= KDE_MAX_CELLS + 2
    assert kde.density.sum() == pytest.approx(1)
    fifty, ninety_five = isopleths(kde, [0.5, 0.95])
    # the smoothed density has variance sigma² + h²
    smoothed = sigma**2 + h**2
    expected_95 = math.pi * smoothed * (-2 * math.log(0.05)) / 10_000
    expected_50 = math.pi * smoothed * (-2 * math.log(0.5)) / 10_000
    assert ninety_five.hectares == pytest.approx(expected_95, rel=0.15)
    assert fifty.hectares == pytest.approx(expected_50, rel=0.15)
    assert fifty.hectares < ninety_five.hectares
    assert ninety_five.geometry.contains(fifty.geometry.representative_point())
    assert ninety_five.geometry.is_valid and fifty.geometry.is_valid


def test_weights_move_the_density():
    lat = np.array([LAT, LAT + 0.02])
    lon = np.array([LON, LON])
    heavy = kde_grid(lat, lon, 200.0, 100, weights=np.array([9.0, 1.0]))
    fifty = isopleths(heavy, [0.5])[0]
    assert fifty.geometry.contains(Point(LON, LAT))


# --- the autocorrelation-corrected range (docs/ANALYTICS_PHASE2_PLAN.md, section 3) ---

from shared.analysis.primitives.homerange import (  # noqa: E402
    corrected_range,
    effective_sample_size,
    variogram,
)


def _ou_track(
    tau_s: float, sigma_m: float, days: int, interval_s: float = 3600.0, seed: int = 11
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An Ornstein-Uhlenbeck walk with a known range: per-axis standard deviation `sigma_m`
    at rest, decorrelating over `tau_s`, sampled every `interval_s`."""
    rng = np.random.default_rng(seed)
    n = int(days * 86_400 / interval_s)
    decay = np.exp(-interval_s / tau_s)
    kick = sigma_m * np.sqrt(1 - decay**2)
    x = np.zeros(n)
    y = np.zeros(n)
    x[0], y[0] = rng.normal(0, sigma_m), rng.normal(0, sigma_m)
    for i in range(1, n):
        x[i] = x[i - 1] * decay + rng.normal(0, kick)
        y[i] = y[i - 1] * decay + rng.normal(0, kick)
    times = np.arange(n) * interval_s
    return times, LAT + y / M_PER_DEG_LAT, LON + x / M_PER_DEG_LON


def test_the_variogram_of_an_ou_walk_rises_to_its_plateau():
    tau, sigma = 2 * 86_400.0, 500.0
    times, lat, lon = _ou_track(tau, sigma, days=120)
    v = variogram(times, lat, lon, max_lag_s=30 * 86_400)
    assert v.lag_s.size >= 10
    # the semivariance of two axes with variance sigma² each rises to 2 sigma²
    assert v.semivariance_m2[-1] == pytest.approx(2 * sigma**2, rel=0.3)
    assert v.semivariance_m2[0] < v.semivariance_m2[-1] / 5


def test_hourly_fixes_two_days_apart_in_memory_are_few_independent_ones():
    n_eff = effective_sample_size(720, 3600.0, 2 * 86_400.0)
    assert 5 < n_eff < 20, n_eff
    assert effective_sample_size(720, 3600.0, 60.0) == pytest.approx(720, rel=0.05)


def test_the_corrected_range_recovers_a_known_range_where_the_plain_kde_falls_short():
    """The exit criterion of the phase: simulated tracks with a known range, the corrected 95
    percent area within twenty percent of the truth where the plain KDE is far below it.

    Over several tracks and not one: forty days of a range that takes two days to cross is
    ten or twenty independent looks at it, and a single track's own spread is that far from
    the process's either way. What an estimator can promise is to be right on average, and
    the plain KDE is not."""
    tau, sigma, days = 2 * 86_400.0, 500.0, 40
    truth_ha = math.pi * sigma**2 * (-2 * math.log(0.05)) / 10_000
    corrected: list[float] = []
    plain: list[float] = []
    for seed in range(11, 19):
        times, lat, lon = _ou_track(tau, sigma, days=days, seed=seed)
        found = corrected_range(times, lat, lon, days * 86_400.0)
        assert found.stationary, found.reason
        assert found.autocorrelation_s == pytest.approx(tau, rel=0.6)
        assert found.effective_fixes is not None and found.effective_fixes < len(times) / 10
        assert found.bandwidth_m is not None
        corrected.append(
            isopleths(kde_grid(lat, lon, found.bandwidth_m, KDE_MAX_CELLS), [0.95])[0].hectares
        )
        plain.append(
            isopleths(kde_grid(lat, lon, reference_bandwidth(lat, lon), KDE_MAX_CELLS), [0.95])[
                0
            ].hectares
        )
    assert np.mean(corrected) == pytest.approx(truth_ha, rel=0.2), (np.mean(corrected), truth_ha)
    assert np.mean(plain) < 0.8 * truth_ha, (np.mean(plain), truth_ha)


@pytest.mark.parametrize("seed", [5, 6, 7])
def test_a_walk_that_never_settles_is_reported_not_computed(seed):
    rng = np.random.default_rng(seed)
    n = 24 * 30
    x = np.cumsum(rng.normal(0, 200, n))
    y = np.cumsum(rng.normal(0, 200, n))
    times = np.arange(n) * 3600.0
    found = corrected_range(times, LAT + y / M_PER_DEG_LAT, LON + x / M_PER_DEG_LON, n * 3600.0)
    assert not found.stationary
    assert found.reason is not None
    assert found.bandwidth_m is None


def test_a_range_that_decorrelates_slower_than_half_the_period_is_not_stationary_either():
    times, lat, lon = _ou_track(20 * 86_400.0, 500.0, days=30, seed=2)
    found = corrected_range(times, lat, lon, 30 * 86_400.0)
    assert not found.stationary


def test_too_few_fixes_give_no_variogram():
    found = corrected_range(np.arange(5) * 3600.0, np.full(5, LAT), np.full(5, LON), 86_400.0)
    assert not found.stationary and found.reason is not None
