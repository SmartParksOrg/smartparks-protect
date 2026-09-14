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
    assert m.speed_hist[0][0] == 0 and sum(v for _, v in m.speed_hist) == 239
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
