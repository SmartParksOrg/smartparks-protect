"""The stop rule and the trips on synthetic tracks (phase 39, decisions D303 and D304): a
parked receiver drifting adds no distance, a drive is one trip with its figures, a halt shorter
than the stop time is a pause and a longer one ends the trip, speeding reads the reported speed."""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from shared.analysis.base import Period, Subject
from shared.analysis.modules.movement import MovementParameters, analyse_trajectory
from shared.analysis.modules.vehicle_use import (
    METRICS,
    Site,
    VehicleParameters,
    analyse_vehicle,
    build_document,
)
from shared.analysis.primitives.trajectory import fold_stops, steps, trajectory_from
from shared.analysis.primitives.trips import segment_trips, speeding_episodes

LAT, LON = -24.9, 31.5
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * float(np.cos(np.radians(LAT)))
START = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
SUBJECT = Subject(id=uuid.uuid4(), name="Bakkie", type="4x4")


def _period(hours=24):
    return Period(time_from=START, time_to=START + timedelta(hours=hours))


def _drive(*legs, step_s=60.0, speeds=True):
    """Legs of (minutes, metres per minute east, reported km/h or None): a fix a minute."""
    times, lat, lon, spd = [], [], [], []
    t = START.timestamp()
    x = 0.0
    for minutes, east_m, kmh in legs:
        for _ in range(int(minutes)):
            times.append(t)
            lat.append(LAT)
            lon.append(LON + x / M_PER_DEG_LON)
            spd.append((kmh / 3.6) if (speeds and kmh is not None) else np.nan)
            t += step_s
            x += east_m
    return trajectory_from(SUBJECT.id, times, lat, lon, speeds=spd)


def test_fold_stops_takes_the_drift_of_a_parked_receiver_away():
    # parked for an hour, the receiver wandering up to 8 m around the spot
    rng = np.random.default_rng(1)
    n = 60
    times = [START.timestamp() + i * 60 for i in range(n)]
    lat = [LAT + rng.uniform(-8, 8) / M_PER_DEG_LAT for _ in range(n)]
    lon = [LON + rng.uniform(-8, 8) / M_PER_DEG_LON for _ in range(n)]
    track = trajectory_from(SUBJECT.id, times, lat, lon)
    raw = float(steps(track, 3600).dist_m.sum())
    assert raw > 200  # the drift alone walks a few hundred metres
    folded, moved = fold_stops(track, 15)
    assert moved == n - 1
    assert float(steps(folded, 3600).dist_m.sum()) == 0
    # a real move past the radius starts a new anchor and keeps its distance
    track2 = trajectory_from(
        SUBJECT.id,
        [0, 60, 120],
        [LAT, LAT, LAT],
        [LON, LON + 5 / M_PER_DEG_LON, LON + 100 / M_PER_DEG_LON],
    )
    folded2, moved2 = fold_stops(track2, 15)
    assert moved2 == 1
    assert float(steps(folded2, 3600).dist_m.sum()) == pytest.approx(100, rel=0.01)
    untouched, none = fold_stops(track2, 0)
    assert none == 0 and untouched is track2


def test_the_movement_module_folds_the_drift_out_of_its_distance():
    rng = np.random.default_rng(2)
    n = 48
    times = [START.timestamp() + i * 1800 for i in range(n)]
    # a drift of up to 5 m on each axis stays inside the 15 m radius of the first fix
    lat = [LAT + rng.uniform(-5, 5) / M_PER_DEG_LAT for _ in range(n)]
    lon = [LON + rng.uniform(-5, 5) / M_PER_DEG_LON for _ in range(n)]
    track = trajectory_from(SUBJECT.id, times, lat, lon)
    params = MovementParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(days=1)
    )
    folded, moved = fold_stops(track, params.stop_radius_m)
    m = analyse_trajectory(folded, params, _period(), "UTC", folded=moved)
    assert m.summary["distance_km"] == 0 and m.summary["folded_fixes"] == n - 1
    assert m.summary["stationary_share"] == 1


def test_a_drive_with_a_pause_and_a_stop_is_two_trips():
    # parked 20 min, 30 min at 60 km/h (1 km a minute), a 5 minute halt, 10 min at 30 km/h,
    # then parked 40 min, then 15 min at 90 km/h and parked till the end
    track = _drive(
        (20, 0, 0),
        (30, 1000, 60),
        (5, 0, 0),
        (10, 500, 30),
        (40, 0, 0),
        (15, 1500, 90),
        (30, 0, 0),
    )
    folded, _ = fold_stops(track, 15)
    s = steps(folded, 4 * 3600)
    trips = segment_trips(folded, s, moving_mps=5 / 3.6, stop_s=1200)
    assert len(trips) == 2
    first, second = trips
    assert first.distance_m == pytest.approx(30 * 1000 + 10 * 500, rel=0.01)
    assert first.paused_s == pytest.approx(5 * 60, abs=60)
    assert first.duration_s == pytest.approx((30 + 5 + 10) * 60, abs=120)
    assert first.top_reported_mps == pytest.approx(60 / 3.6)
    assert first.mean_mps * 3.6 == pytest.approx(52.5, rel=0.05)
    assert not first.cut_by_gap
    assert second.distance_m == pytest.approx(15 * 1500, rel=0.01)
    assert second.top_reported_mps == pytest.approx(90 / 3.6)
    assert second.start_s > first.end_s


def test_a_parked_car_at_hourly_fixes_drifting_past_the_radius_makes_no_trip():
    # a fix an hour, each 40 m from the last: past the stop radius, but 0.01 m/s is no movement
    n = 24
    times = [START.timestamp() + i * 3600 for i in range(n)]
    lon = [LON + (40 * (i % 2)) / M_PER_DEG_LON for i in range(n)]
    track = trajectory_from(SUBJECT.id, times, [LAT] * n, lon)
    folded, moved = fold_stops(track, 15)
    assert moved == 0
    s = steps(folded, 4 * 3600)
    assert segment_trips(folded, s, moving_mps=5 / 3.6, stop_s=600) == []
    params = VehicleParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(days=1)
    )
    r = analyse_vehicle(folded, params, _period(), "UTC", [], SUBJECT)
    assert r.summary["trips"] == 0 and r.summary["distance_km"] == 0
    assert r.summary["driving_h"] == 0 and r.summary["days_active"] == 0


def test_a_gap_cuts_a_trip_and_the_step_speed_stands_in_without_a_reported_one():
    track = _drive((10, 1000, None), (10, 1000, None), speeds=False)
    # five hours of silence in the middle
    times = track.times.copy()
    times[10:] += 5 * 3600
    track = trajectory_from(SUBJECT.id, list(times), list(track.lat), list(track.lon))
    s = steps(track, 4 * 3600)
    trips = segment_trips(track, s, moving_mps=5 / 3.6, stop_s=600)
    assert len(trips) == 2 and trips[0].cut_by_gap and not trips[1].cut_by_gap
    assert trips[0].top_reported_mps is None
    assert trips[0].top_step_mps == pytest.approx(1000 / 60, rel=0.01)


def test_speeding_reads_the_reported_speed_alone():
    track = _drive((5, 800, 50), (3, 1200, 75), (2, 900, 55), (4, 1300, 80), (5, 0, 0))
    episodes = speeding_episodes(track, 60 / 3.6)
    assert [(e.end_index - e.start_index + 1) for e in episodes] == [3, 4]
    assert episodes[1].top_mps == pytest.approx(80 / 3.6)
    assert speeding_episodes(_drive((5, 800, None), speeds=False), 60 / 3.6) == []


def test_the_vehicle_figures_and_the_document():
    track = _drive((10, 0, 0), (30, 1000, 60), (25, 0, 0), (10, 1200, 90), (20, 0, 0))
    params = VehicleParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(hours=2)
    )
    folded, moved = fold_stops(track, params.stop_radius_m)
    sites = [Site("Main gate", LAT, LON), Site("Camp", LAT, LON + 30_000 / M_PER_DEG_LON)]
    r = analyse_vehicle(
        folded, params, _period(2), "Africa/Johannesburg", sites, SUBJECT, folded=moved
    )
    s = r.summary
    assert set(s) == set(METRICS)
    assert s["trips"] == 2 and s["fixes"] == 95
    assert s["distance_km"] == pytest.approx(42, rel=0.01)
    assert s["driving_h"] == pytest.approx(40 / 60, rel=0.05)
    assert s["top_speed_kmh"] == 90 and s["speeding_episodes"] == 1
    assert s["speeding_top_kmh"] == 90 and s["fixes_with_speed_share"] == 1
    assert s["days_active"] == 1 and s["longest_trip_km"] == pytest.approx(30, rel=0.01)
    trips = sorted(r.trips, key=lambda row: row[3])
    assert trips[0][2] == 1 and trips[0][10] == "Main gate" and trips[0][11] == "Camp"
    assert trips[0][9] == "reported" and trips[0][14] == "stop"
    assert len(r.days) == 1 and r.days[0][3] == 2
    assert r.days[0][6] == "14:10"  # the first movement, on the project's clock (UTC+2)
    kinds = [g.kind for g in r.geometries]
    assert kinds.count("trip_marker") == 4
    roles = [g.properties["role"] for g in r.geometries if g.kind == "trip_marker"]
    assert roles == ["start", "end", "start", "end"]
    assert kinds.count("speeding") == 1
    # the first trip runs at 60 km/h (at the limit, one class) and the second at 90 (far over)
    segments = [g for g in r.geometries if g.kind == "trip_segment"]
    assert len(segments) == 2 and segments[0].geojson["type"] == "LineString"
    assert [g.properties["speed_class"] for g in segments] == [3, 4]
    assert segments[0].properties["trip"] == 1 and segments[1].properties["speed_kmh"] == 90
    assert [g.properties["short"] for g in r.geometries if g.kind == "speeding"] == ["90"]
    assert dict(r.speed_hist)["60"] == 30 and dict(r.speed_hist)["80"] == 10
    assert sum(v for _, v in r.hour_km) == pytest.approx(42, rel=0.01)

    document = build_document(
        [SUBJECT], [_period(2)], {("main", SUBJECT.id): r}, params, input_count=90, excluded_count=0
    )
    assert document.module == "vehicle_use"
    assert [t.key for t in document.tables] == ["summary", "trips", "days", "speeding"]
    assert [c.key for c in document.charts] == ["daily_distance", "speed_histogram", "hour_profile"]
    assert document.tables[1].rows[0][8] == 90  # the trips table leads with the fastest


def test_a_vehicle_without_reported_speeds_says_so():
    track = _drive((10, 1000, None), (10, 0, None), speeds=False)
    params = VehicleParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(hours=1)
    )
    r = analyse_vehicle(track, params, _period(1), "UTC", [], SUBJECT)
    assert "no_reported_speed" in {w.code for w in r.warnings}
    assert r.summary["speeding_episodes"] == 0 and r.summary["fixes_with_speed_share"] == 0
    assert r.summary["top_speed_kmh"] == pytest.approx(60, rel=0.01)
    assert r.trips[0][9] == "between fixes"


def test_a_move_shorter_than_the_minimum_is_not_a_trip():
    track = _drive((5, 0, 0), (2, 100, 20), (30, 0, 0))
    params = VehicleParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(hours=1)
    )
    r = analyse_vehicle(track, params, _period(1), "UTC", [], SUBJECT)
    assert r.summary["trips"] == 0 and r.geometries == []
    loose = VehicleParameters(
        entity_ids=[SUBJECT.id],
        time_from=START,
        time_to=START + timedelta(hours=1),
        min_trip_m=0,
    )
    assert analyse_vehicle(track, loose, _period(1), "UTC", [], SUBJECT).summary["trips"] == 1
