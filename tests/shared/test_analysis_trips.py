"""The stop rule and the trips on synthetic tracks (phase 39, decisions D303 and D304): a
parked receiver drifting adds no distance, a drive is one trip with its figures, a halt shorter
than the stop time is a pause and a longer one ends the trip, speeding reads the reported speed.
And phase 40 (decisions D306 to D308): the bands of the path, the speed over the period with
its breaks, the series per day on every day of the period, the limits of the rules."""

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import numpy as np
import pytest

from shared.analysis.base import Period, Subject
from shared.analysis.modules.movement import MovementParameters, analyse_trajectory
from shared.analysis.modules.vehicle_use import (
    METRICS,
    SPEED_BAND_EDGES_KMH,
    SPEED_BAND_LABELS,
    Limit,
    Site,
    VehicleParameters,
    analyse_vehicle,
    build_document,
    merge_limits,
    speed_bucket_s,
    speed_class,
    speed_limits_of,
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
    # the first trip runs at 60 km/h (the band from 40, at the limit and not over it) and the
    # second at 90 (the band from 80, over the limit)
    segments = [g for g in r.geometries if g.kind == "trip_segment"]
    assert len(segments) == 2 and segments[0].geojson["type"] == "LineString"
    assert [g.properties["speed_class"] for g in segments] == [3, 4]
    assert [g.properties["over_limit"] for g in segments] == [False, True]
    assert segments[0].properties["trip"] == 1 and segments[1].properties["speed_kmh"] == 90
    assert [g.properties["short"] for g in r.geometries if g.kind == "speeding"] == ["90"]
    # thirty minutes in the band from 40 and ten in the band from 80
    bands = dict(r.band_min)
    assert list(bands) == SPEED_BAND_LABELS
    assert bands["40"] == pytest.approx(30, abs=1) and bands["80"] == pytest.approx(10, abs=1)
    assert sum(bands.values()) == pytest.approx(40, abs=1)
    assert sum(v for _, v in r.hour_h) == pytest.approx(40 / 60, rel=0.05)
    # 12:00 UTC is 14:00 on the project's clock: both hours of the drive have their speeds
    typical, top = dict(r.hour_typical_kmh), dict(r.hour_top_kmh)
    assert typical["14"] == 60 and top["15"] == 90 and typical["3"] is None
    # the period touches one local day; its distance, driving time and speeding stand on it
    assert [len(x) for x in (r.daily_km, r.daily_h, r.daily_speeding_min)] == [1, 1, 1]
    assert r.daily_km[0][1] == pytest.approx(42, rel=0.01)
    assert r.daily_speeding_min[0][1] == pytest.approx(9, abs=1)
    # the speed over the two hours, a point a minute: parked is zero, the drive its speed,
    # and after the last fix the record is silent, which is no value at all
    speeds = [v for _, v in r.speed_series]
    assert len(speeds) == 120 and speeds[0] == 0 and speeds[20] == 60
    assert max(v for v in speeds if v is not None) == 90
    assert speeds[94] == 0 and speeds[95] is None and speeds[-1] is None

    limits = [
        Limit(40, "Camp road", "rule", zone=True),
        Limit(60, "Speeding", "rule"),
        Limit(40, "School", "rule", zone=True),
    ]
    document = build_document(
        [SUBJECT],
        [_period(2)],
        {("main", SUBJECT.id): r},
        params,
        input_count=90,
        excluded_count=0,
        limits=limits,
    )
    assert document.module == "vehicle_use"
    assert [t.key for t in document.tables] == ["summary", "trips", "days", "speeding"]
    assert [c.key for c in document.charts] == [
        "speed_over_time",
        "daily_distance",
        "daily_driving",
        "hour_driving",
        "hour_speed",
        "speed_bands",
        "daily_speeding",
    ]
    charts = {c.key: c for c in document.charts}
    # the run's limit leads and keeps its name where a rule judges by the same speed; two
    # rules of one speed share a line
    assert [(x["value"], x["label"], x["zone"]) for x in charts["speed_over_time"].limits] == [
        (60, "run_limit", False),
        (40, "Camp road, School", True),
    ]
    assert charts["speed_over_time"].breaks and charts["hour_speed"].limits
    assert [s["part"] for s in charts["hour_speed"].series] == ["typical", "top"]
    assert document.tables[1].rows[0][8] == 90  # the trips table leads with the fastest


def test_the_bands_widen_and_the_limit_cuts_a_stretch():
    assert [speed_class(v) for v in (0, 9.9, 10, 19, 20, 39, 40, 79, 80, 119, 120, 200)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        4,
        4,
        5,
        5,
    ]
    # every band is at least as wide as the one before it
    edges = (0.0, *SPEED_BAND_EDGES_KMH)
    widths = [b - a for a, b in pairwise(edges)]
    assert widths == sorted(widths)
    # 50 and 70 km/h are one band; a limit of 60 between them still cuts the path in two
    track = _drive((5, 0, 0), (10, 830, 50), (10, 1170, 70), (25, 0, 0))
    params = VehicleParameters(
        entity_ids=[SUBJECT.id], time_from=START, time_to=START + timedelta(hours=1)
    )
    r = analyse_vehicle(track, params, _period(1), "UTC", [], SUBJECT)
    segments = [g for g in r.geometries if g.kind == "trip_segment"]
    assert [g.properties["speed_class"] for g in segments] == [3, 3]
    assert [g.properties["over_limit"] for g in segments] == [False, True]


def test_the_speed_over_time_keeps_its_points_in_hand():
    hour, week, year = 3600, 7 * 86_400, 366 * 86_400
    assert speed_bucket_s(hour, 1) == 60
    assert speed_bucket_s(week, 1) == 900 and week / 900 <= 1000
    # many vehicles share the document's points, so each gets a coarser line
    assert speed_bucket_s(week, 25) == 3 * 3600 and week / (3 * 3600) <= 4000 / 25
    assert speed_bucket_s(year, 1) == 86_400


def test_a_gap_breaks_the_speed_line_and_a_quiet_vehicle_keeps_its_days():
    # a drive, three hours of silence (longer than the gap), a drive again
    first = _drive((10, 1000, 60))
    times = list(first.times) + [t + 4 * 3600 for t in first.times]
    lon = list(first.lon) + [x + 0.2 for x in first.lon]
    track = trajectory_from(
        SUBJECT.id, times, [LAT] * len(times), lon, speeds=[60 / 3.6] * len(times)
    )
    params = VehicleParameters(
        entity_ids=[SUBJECT.id],
        time_from=START,
        time_to=START + timedelta(hours=6),
        gap_hours=2,
    )
    r = analyse_vehicle(track, params, _period(6), "UTC", [], SUBJECT, bucket_s=600)
    speeds = [v for _, v in r.speed_series]
    assert len(speeds) == 36
    assert speeds[0] == 60 and speeds[24] == 60
    assert all(v is None for v in speeds[1:24])  # the silence, not a standstill

    # a vehicle without a fix in a period of three days still has three days on its axis
    nothing = trajectory_from(SUBJECT.id, [], [], [])
    long = Period(time_from=START, time_to=START + timedelta(days=3) - timedelta(hours=12))
    quiet = analyse_vehicle(nothing, params, long, "UTC", [], SUBJECT)
    assert [v for _, v in quiet.daily_km] == [0, 0, 0]
    assert all(v is None for _, v in quiet.speed_series)


def test_the_limits_a_rule_judges_by():
    anywhere = {"conditions": {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 60}}
    assert [(x.value, x.label, x.zone) for x in speed_limits_of("Speeding", anywhere)] == [
        (60, "Speeding", False)
    ]
    inside = {
        "conditions": {
            "all": [
                {"type": "threshold", "metric": "speed_kmh", "op": ">=", "value": 40},
                {"type": "spatial", "relation": "inside", "feature_type": "zone"},
            ]
        }
    }
    assert [(x.value, x.zone) for x in speed_limits_of("Camp", inside)] == [(40, True)]
    # a rule about something else, or one that asks for a slow vehicle, draws no line
    battery = {
        "conditions": {"type": "threshold", "metric": "battery_voltage", "op": ">", "value": 3}
    }
    slow = {"conditions": {"type": "threshold", "metric": "speed_kmh", "op": "<", "value": 5}}
    assert speed_limits_of("Battery", battery) == [] and speed_limits_of("Slow", slow) == []
    nested = {
        "conditions": {
            "any": [
                {"not": {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 30}},
                {"all": [{"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 80}]},
            ]
        }
    }
    assert sorted(x.value for x in speed_limits_of("Nested", nested)) == [30, 80]
    # the lowest stay when a project has more rules than a chart can carry
    many = [Limit(float(v), f"Rule {v}", "rule") for v in range(10, 130, 10)]
    kept = merge_limits([Limit(60, "run_limit", "run"), *many])
    assert [x.value for x in kept] == [60, 10, 20, 30, 40, 50]


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
