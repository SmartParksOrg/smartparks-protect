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
