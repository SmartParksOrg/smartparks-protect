"""The movement module on synthetic tracks (docs/ANALYTICS_PHASE1_PLAN.md, section 17): the
totals of a known walk within 1 percent, the document shape, the comparison rows."""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from shared.analysis.base import Period, ResultDocument, Subject
from shared.analysis.modules.movement import (
    METRICS,
    MovementParameters,
    analyse_trajectory,
    build_document,
    hotspot_geometries,
)
from shared.analysis.primitives.trajectory import trajectory_from

LAT, LON = -19.0, 23.5  # the Okavango: the sun is up at 10:00 UTC and down at 22:00 UTC
M_PER_DEG_LAT = 111_320.0
START = datetime(2026, 5, 1, tzinfo=UTC)


def _params(**extra):
    return MovementParameters(
        entity_ids=[uuid.uuid4()],
        time_from=START,
        time_to=START + timedelta(days=10),
        **extra,
    )


def _period():
    return Period(time_from=START, time_to=START + timedelta(days=10))


def _straight_walk(entity_id=None, *, fixes=240, step_s=3600.0, step_m=500.0):
    """East at half a kilometre an hour for ten days, a fix every hour."""
    dlon = step_m / (M_PER_DEG_LAT * np.cos(np.radians(LAT)))
    times = [START.timestamp() + i * step_s for i in range(fixes)]
    return trajectory_from(
        entity_id or uuid.uuid4(), times, [LAT] * fixes, [LON + i * dlon for i in range(fixes)]
    )


def test_a_straight_walk_reproduces_its_totals():
    track = _straight_walk()
    m = analyse_trajectory(track, _params(), _period(), "Africa/Gaborone")
    s = m.summary
    assert s["fixes"] == 240 and s["days_with_data"] == 11  # ten UTC days touch eleven at UTC+2
    assert s["distance_km"] == pytest.approx(239 * 0.5, rel=0.01)
    assert s["displacement_km"] == pytest.approx(239 * 0.5, rel=0.01)
    assert s["max_displacement_km"] == s["displacement_km"]
    assert s["daily_distance_km"] == pytest.approx(12, rel=0.01)
    assert s["mean_speed_mps"] == pytest.approx(500 / 3600, rel=0.01)
    assert s["stationary_share"] == 0 and s["moving_share"] == 1
    assert s["median_interval_min"] == 60
    # half the steps start by day, half by night, at 19 degrees south in May
    assert s["day_distance_km"] + s["night_distance_km"] <= s["distance_km"]
    assert 45 < s["day_distance_km"] < 75
    assert len(m.daily_km) == 11 and all(
        v == pytest.approx(12, rel=0.05) for _, v in m.daily_km[1:-1]
    )
    assert sum(v for _, v in m.hour_km) == pytest.approx(s["distance_km"], rel=0.01)
    assert [h for h, _ in m.hour_km] == [str(h) for h in range(24)]
    # every turn is 0 degrees: the bin centred on 11 (from 0 to 22.5) holds them all
    assert sum(v for _, v in m.turning_hist) == 238
    assert dict(m.turning_hist)["11"] == 238
    # 0.139 m/s falls in the bin from 0.1 to 0.2
    assert dict(m.speed_hist)["0.1"] == 239 and sum(v for _, v in m.speed_hist) == 239
    assert m.nsd[-1][1] == pytest.approx(s["displacement_km"] ** 2, rel=0.02)
    # a walk that never lingers has hotspots over the cells it crossed, none large
    assert s["hotspot_count"] >= 1 and all(share < 0.05 for _, share, _ in m.hotspot_cells)
    assert not [w for w in m.warnings if w.level == "warning"]


def test_a_resting_animal_has_stationary_periods_and_one_hotspot():
    n = 240
    times = [START.timestamp() + i * 3600 for i in range(n)]
    track = trajectory_from(uuid.uuid4(), times, [LAT] * n, [LON] * n)
    m = analyse_trajectory(track, _params(), _period(), "UTC")
    assert m.summary["stationary_share"] == 1 and m.summary["stationary_periods"] == 1
    assert m.summary["distance_km"] == 0 and m.summary["hotspot_count"] == 1
    assert m.hotspot_cells[0][1] == pytest.approx(1.0) and m.hotspot_cells[0][2] == 1


def test_few_fixes_leave_the_spatial_figures_out():
    track = _straight_walk(fixes=10)
    m = analyse_trajectory(track, _params(), _period(), "UTC")
    assert m.summary["hotspot_count"] is None
    assert [w.code for w in m.warnings] == ["few_fixes"]


def test_the_document_holds_subjects_periods_and_the_mean_row():
    a, b = uuid.uuid4(), uuid.uuid4()
    subjects = [
        Subject(id=a, name="Aldo", type="Elephant"),
        Subject(id=b, name="Bibi", type="Elephant"),
    ]
    main = _period()
    comparison = Period(key="comparison", time_from=START - timedelta(days=10), time_to=START)
    params = _params(comparison={"time_from": comparison.time_from, "time_to": comparison.time_to})
    results = {}
    for period in (main, comparison):
        for subject, step_m in ((subjects[0], 500.0), (subjects[1], 250.0)):
            track = _straight_walk(subject.id, step_m=step_m)
            results[(period.key, subject.id)] = analyse_trajectory(track, params, period, "UTC")
    document = build_document(
        subjects,
        [main, comparison],
        results,
        params,
        input_count=960,
        excluded_count=0,
        geometries={"hotspot": 7},
    )
    assert ResultDocument.model_validate(document.model_dump(mode="json"))
    table = document.tables[0]
    assert table.columns == ["subject", "period", *METRICS]
    assert [r[:2] for r in table.rows] == [
        ["Aldo", "main"],
        ["Bibi", "main"],
        ["Aldo", "comparison"],
        ["Bibi", "comparison"],
        ["mean", "main"],
        ["sd", "main"],
        ["mean", "comparison"],
        ["sd", "comparison"],
    ]
    distance = METRICS.index("distance_km") + 2
    assert table.rows[4][distance] == pytest.approx((119.5 + 59.75) / 2, rel=0.01)
    assert document.summary["main"][str(a)]["distance_km"] == pytest.approx(119.5, rel=0.01)
    assert {c.key for c in document.charts} == {
        "daily_distance",
        "speed_histogram",
        "hour_profile",
        "turning",
        "nsd",
        "day_night",
    }
    assert all(len(c.series) == 4 for c in document.charts)
    assert document.geometries == {"hotspot": 7}
    assert document.provenance.parameters["max_speed_mps"] == 15
    geometries = hotspot_geometries(subjects[0], main, results[("main", a)])
    assert (
        geometries
        and geometries[0].kind == "hotspot"
        and geometries[0].geojson["type"] == "Polygon"
    )


def test_the_module_is_in_the_catalogue():
    import shared.analysis.modules  # noqa: F401
    from shared.analysis import MODULES

    # the boundary test re-imports the package, so compare by name, not identity
    module = MODULES["movement"]
    assert module.key == "movement" and module.version == "movement/1"
    assert module.parameters.__name__ == MovementParameters.__name__


class TestMovementFromNoise:
    """The rule that decides a device moved, against the noise a device that cannot move makes.

    Measured on the 45 PWN scanners bolted to posts, 10,177 activity samples over eleven days
    (Tim, 2026-09-19: they read "moving" while bolted down). Their accelerometer is 8-bit over
    ±100 m/s² reported in two-count steps, so a still device reports changes in multiples of
    0.784 m/s² as the temperature drifts: 0.784 on one axis, 1.109 on two, 1.358 on three.
    """

    def _times(self, values, previous=None):
        from shared.domain.movement import movement_times

        start = datetime(2026, 9, 10, tzinfo=UTC)
        samples = [(start + timedelta(hours=i), v) for i, v in enumerate(values)]
        return movement_times(samples, previous)

    def test_the_quantisation_of_a_still_device_is_not_movement(self):
        """One step on each of the three axes is 1.358 m/s² and means the sensor read itself
        differently, not that anything happened. This is 3,236 of the scanners' samples."""
        from shared.domain.movement import MOVEMENT_THRESHOLD_MPS2, SENSOR_STEP_MPS2

        one_axis = SENSOR_STEP_MPS2
        two_axes = SENSOR_STEP_MPS2 * 2**0.5
        three_axes = SENSOR_STEP_MPS2 * 3**0.5
        assert three_axes < MOVEMENT_THRESHOLD_MPS2, (
            "the threshold has to clear the noise floor of a device that cannot move"
        )
        assert self._times([one_axis, two_axes, three_axes, three_axes]) == []

    def test_a_single_drift_between_quiet_messages_is_not_movement(self):
        """A bolted device crossing 1.4 once, with quiet either side: temperature, not motion."""
        assert self._times([0.0, 1.57, 0.0, 0.784]) == []

    def test_two_moderate_changes_running_are_movement(self):
        """An animal that moves produces a run, which is what tells it from drift."""
        found = self._times([0.0, 1.5, 1.6, 0.0])
        assert len(found) == 1, "the second of the pair confirms it"

    def test_one_clear_jump_is_movement_without_waiting(self):
        """Somebody picking the device up. Waiting for a second sample would lose the moment."""
        from shared.domain.movement import MOVEMENT_ALONE_MPS2

        assert len(self._times([0.0, 5.0, 0.0])) == 1
        assert MOVEMENT_ALONE_MPS2 > 1.358, "still above the three-axis quantisation"

    def test_a_run_carried_over_from_the_delivery_before(self):
        """The device does not stop moving because a message boundary fell in the middle."""
        assert len(self._times([1.6], previous=1.5)) == 1
        assert self._times([1.6], previous=0.0) == []
        assert self._times([1.6], previous=None) == [], "nothing known before: wait for a second"

    def test_a_still_device_reports_nothing(self):
        assert self._times([0.0] * 10) == []
