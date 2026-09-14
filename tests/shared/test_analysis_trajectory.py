"""The trajectory primitives on synthetic tracks (docs/ANALYTICS_PHASE1_PLAN.md, section 17)."""

import uuid

import numpy as np
import pytest

from shared.analysis.primitives.spatial import LocalGrid, hotspots, residence
from shared.analysis.primitives.trajectory import (
    exclude_impossible,
    steps,
    time_weights,
    trajectory_from,
    turning_angles,
)
from shared.geodesy import bearing_deg, haversine_m, metres_between

LAT, LON = 52.09, 5.36
M_PER_DEG_LAT = 111_320.0


def _square(side_m: float = 1000.0, step_s: float = 600.0):
    """Four legs of a square walked clockwise from the south west corner, one fix per corner
    and back to the start."""
    dlat = side_m / M_PER_DEG_LAT
    dlon = side_m / (M_PER_DEG_LAT * np.cos(np.radians(LAT)))
    corners = [
        (LAT, LON),
        (LAT + dlat, LON),
        (LAT + dlat, LON + dlon),
        (LAT, LON + dlon),
        (LAT, LON),
    ]
    return trajectory_from(
        uuid.uuid4(),
        [i * step_s for i in range(5)],
        [c[0] for c in corners],
        [c[1] for c in corners],
    )


def test_geodesy_matches_known_distances_and_bearings():
    assert haversine_m(LAT, LON, LAT + 1000 / M_PER_DEG_LAT, LON) == pytest.approx(1000, rel=0.002)
    assert metres_between((LON, LAT), (LON, LAT)) == 0
    assert bearing_deg(LAT, LON, LAT + 0.01, LON) == pytest.approx(0, abs=0.01)
    assert bearing_deg(LAT, LON, LAT, LON + 0.01) == pytest.approx(90, abs=0.5)


def test_a_square_walk_has_four_equal_steps_and_right_turns():
    track = _square()
    s = steps(track, gap_seconds=3600)
    assert len(s) == 4 and not s.gap.any()
    assert s.dist_m == pytest.approx([1000, 1000, 1000, 1000], rel=0.003)
    assert float(s.dist_m.sum()) == pytest.approx(4000, rel=0.003)
    assert s.speed_mps == pytest.approx([1000 / 600] * 4, rel=0.003)
    turns = turning_angles(s)
    assert turns == pytest.approx([90, 90, 90], abs=0.6)
    # back at the start: no displacement
    assert haversine_m(track.lat[0], track.lon[0], track.lat[-1], track.lon[-1]) < 1


def test_a_gap_is_no_movement_and_carries_no_weight():
    track = trajectory_from(
        uuid.uuid4(),
        [0, 600, 600 + 86_400, 600 + 86_400 + 600],
        [LAT] * 4,
        [LON, LON + 0.01, LON + 0.02, LON + 0.03],
    )
    s = steps(track, gap_seconds=3600)
    assert list(s.gap) == [False, True, False]
    weights = time_weights(track, gap_seconds=3600)
    # the day of silence counts one gap threshold at most on either side
    assert weights == pytest.approx([300, 300 + 1800, 1800 + 300, 300])
    assert float(weights.sum()) == pytest.approx(600 + 3600 + 600)


def test_an_impossible_speed_drops_the_fix():
    track = trajectory_from(uuid.uuid4(), [0, 60, 120], [LAT, LAT + 1.0, LAT], [LON, LON, LON])
    kept, dropped = exclude_impossible(track, max_speed_mps=15)
    assert dropped == 1 and len(kept) == 2 and list(kept.times) == [0, 120]


def test_residence_on_a_grid_counts_time_and_visits():
    # sits in one cell for an hour, leaves for a day, comes back for an hour
    times = [i * 600 for i in range(7)] + [86_400 + i * 600 for i in range(7)]
    lat = [LAT] * 7 + [LAT] * 7
    lon = [LON] * 7 + [LON] * 7
    track = trajectory_from(uuid.uuid4(), times, lat, lon)
    grid = LocalGrid.around(track, cell_m=100)
    cells = residence(track, time_weights(track, gap_seconds=3600), grid, min_absence_s=12 * 3600)
    assert len(cells) == 1
    cell = next(iter(cells.values()))
    assert cell.visits == 2
    # an hour of fixes each side, plus half a gap threshold at the join, twice
    assert cell.seconds == pytest.approx(2 * 3600 + 3600, rel=0.01)
    top = hotspots(cells, share=0.5)
    assert len(top) == 1 and grid.polygon(*top[0][0])[0] != grid.polygon(*top[0][0])[2]
