"""The whole cardiac record (phase 35, decisions D287 to D290): the primitives that read every
metric in the day, the night and the resting hours, and one subject through `subject_figures`
and `build_document` over synthetic days, all without a database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

import shared.analysis.modules.cardiac as cardiac
from shared.analysis.base import Period, Subject
from shared.analysis.primitives.cardiac import (
    MIN_READINGS,
    before_after,
    box,
    daylight,
    fixed_daylight,
    night_days,
    real_activity,
    report_step_s,
    restless_nights,
)

START = datetime(2026, 8, 1, tzinfo=UTC)
FIVE_MIN = 300


def test_a_box_has_tukey_whiskers_and_leaves_the_far_readings_out() -> None:
    values = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 100], dtype=float)
    shape = box(values)
    assert shape is not None
    assert (shape.q1, shape.median, shape.q3) == (12.25, 14.5, 16.75)
    assert shape.low == 10 and shape.high == 18  # 100 is beyond 1.5 middle halves
    assert shape.n == 10
    assert box(np.array([np.nan])) is None


def test_an_activity_of_zero_is_the_implants_fault_not_a_reading() -> None:
    assert real_activity(np.array([0.0, 14.0, 255.0, np.nan])).tolist() == [
        False,
        True,
        True,
        False,
    ]


def test_day_follows_the_sun_at_the_place() -> None:
    # on the equator at the prime meridian the sun is up at noon UTC and down at midnight
    noon = datetime(2026, 3, 21, 12, tzinfo=UTC).timestamp()
    midnight = datetime(2026, 3, 21, 0, tzinfo=UTC).timestamp()
    assert daylight(np.array([noon, midnight]), 0.0, 0.0).tolist() == [True, False]
    # the same noon UTC is night on the other side of the world
    assert daylight(np.array([noon]), 0.0, 180.0).tolist() == [False]


def test_day_by_the_clock_is_six_to_eighteen() -> None:
    assert fixed_daylight(np.array([5, 6, 17, 18])).tolist() == [False, True, True, False]


def test_a_reading_after_midnight_belongs_to_the_night_before() -> None:
    evening = datetime(2026, 8, 1, 22, tzinfo=UTC).timestamp()
    small_hours = datetime(2026, 8, 2, 3, tzinfo=UTC).timestamp()
    nights = night_days(np.array([evening, small_hours]), np.zeros(2))
    assert nights[0] == nights[1]


def test_restless_minutes_count_readings_above_the_threshold() -> None:
    nights = np.zeros(20, dtype=int)
    activity = np.array([20.0] * 14 + [150.0] * 6)
    assert restless_nights(nights, activity, 100, FIVE_MIN) == [(0, 30.0, 20)]
    # a night heard too little is left out rather than read as a quiet one
    thin = restless_nights(np.zeros(MIN_READINGS - 1, dtype=int), np.full(11, 150.0), 100, 300)
    assert thin == []


def test_the_report_step_is_the_median_spacing() -> None:
    assert report_step_s(np.array([0.0, 300.0, 600.0, 1500.0])) == 300.0
    assert report_step_s(np.array([0.0])) is None


def test_before_and_after_an_event() -> None:
    times = np.arange(40, dtype=float) * FIVE_MIN
    values = np.where(times < 20 * FIVE_MIN, 80.0, 90.0)
    change = before_after(times, values, 20 * FIVE_MIN)
    assert change is not None
    assert change["difference"] == 10.0
    # a side too thin for a baseline gives no change
    thin = before_after(times, values, 3 * FIVE_MIN)
    assert thin is not None and thin["before"] is None and thin["difference"] is None


def readings_over(days: int) -> cardiac.Readings:
    """Days of five-minute reports with a plain rhythm: a faster, more active heart by day, a
    cooler night, and the implant's 0 at the top of every hour."""
    readings = cardiac.Readings()
    for step in range(days * 24 * 12):
        at = START + timedelta(seconds=step * FIVE_MIN)
        awake = 7 <= at.hour < 17  # well inside daylight at the equator
        later = at >= START + timedelta(days=days // 2)
        readings.add(cardiac.HEART_RATE, at, (110.0 if awake else 70.0) + (5 if later else 0))
        readings.add(cardiac.HRV, at, 6.0 if awake else 4.0)
        readings.add(cardiac.ACTIVITY, at, 0.0 if at.minute == 0 else 210.0 if awake else 25.0)
        readings.add(cardiac.TAG_TEMPERATURE, at, 37.0)
        readings.add(cardiac.SUCCESS, at, 1.0)
    return readings


def params(**extra: object) -> cardiac.CardiacParameters:
    return cardiac.CardiacParameters(
        entity_ids=[uuid.uuid4()],
        time_from=START,
        time_to=START + timedelta(days=6),
        **extra,  # type: ignore[arg-type]
    )


def test_an_event_outside_the_period_is_refused() -> None:
    with pytest.raises(ValidationError, match="inside the period"):
        params(event_at=START - timedelta(days=1))


def test_a_subject_is_read_in_every_part_of_the_day() -> None:
    chosen = params(event_at=START + timedelta(days=3))
    period = Period(key="main", time_from=chosen.time_from, time_to=chosen.time_to)
    # the equator at the prime meridian: the sun is up from about 06:00 to 18:00 UTC
    figures = cardiac.subject_figures(
        readings_over(6), period, UTC, chosen, FIVE_MIN, (0.0, 0.0, "sun"), chosen.event_at
    )
    assert figures["day_night_from"] == "sun"
    assert set(figures["metrics"]) == {"heart_rate", "hrv", "activity", "temperature"}
    # every hourly 0 is set aside and counted, and never reaches a figure
    assert figures["activity_faults"] == 6 * 24
    activity = figures["metrics"]["activity"]
    assert activity["parts"]["day"]["median"] == 210.0
    assert activity["parts"]["night"]["median"] == 25.0
    # six nights, none restless at a score of 25
    assert figures["restless"]["median_minutes"] == 0.0
    assert len(figures["restless"]["nights"]) >= 5
    # the heart beats five faster after the event, by day and by night
    change = figures["metrics"]["heart_rate"]["event"]["night"]
    assert change["difference"] == 5.0
    assert len(figures["metrics"]["heart_rate"]["rhythm"]) == 24


def test_the_document_draws_the_four_views() -> None:
    subject = Subject(id=uuid.uuid4(), name="GAG", type="Baboon")
    chosen = params(event_at=START + timedelta(days=3))
    period = Period(key="main", time_from=chosen.time_from, time_to=chosen.time_to)
    figures = cardiac.subject_figures(
        readings_over(6), period, UTC, chosen, FIVE_MIN, None, chosen.event_at
    )
    assert figures["day_night_from"] == "fixed hours"
    warnings = cardiac.subject_warnings(subject, figures, period)
    assert "day_night_by_the_clock" in {w.code for w in warnings}
    document = cardiac.build_document(
        [subject], [period], {(subject.id, "main"): figures}, chosen, warnings, 0, 0
    )
    charts = {chart.key: chart for chart in document.charts}
    for metric in ("heart_rate", "hrv", "activity", "temperature"):
        assert f"rhythm_{metric}" in charts and f"parts_{metric}" in charts
    assert "restless" in charts
    rhythm = charts["rhythm_heart_rate"].series[0]
    # the series is `data` with a label per hour, which the page and the report both read
    assert len(rhythm["data"]) == 24 and rhythm["data"][0][0] == "00"
    parts = charts["parts_activity"]
    assert parts.kind == "box"
    assert [row[0] for row in parts.series[0]["data"]] == ["day", "night", "resting"]
    assert len(parts.series[0]["data"][0][1]) == 5
    daily = charts["daily_heart_rate"]
    assert {s["part"] for s in daily.series} == {"day", "night"}
    assert daily.marks and daily.marks[0]["label"] == "event_at"
    tables = {table.key: table for table in document.tables}
    assert {"cardiac", "parts", "event", "coverage"} <= set(tables)
    # the summary keeps the boxes and the changes, not a second copy of every hour and date
    stored = document.summary["subjects"][str(subject.id)]["metrics"]["heart_rate"]
    assert "rhythm" not in stored and "daily" not in stored and "parts" in stored


def test_the_report_has_a_cardiac_section_of_its_own() -> None:
    """The PDF read a cardiac run with the movement module's labels, figures and limitations
    until phase 35; it now carries its own, with the box plots and the event drawn."""
    from shared.analysis.report.charts import chart_svg
    from shared.analysis.report.render import (
        CARDIAC_LIMITATIONS,
        MOVEMENT_LIMITATIONS,
        ReportInput,
        labels_for,
        render_html,
    )

    subject = Subject(id=uuid.uuid4(), name="GAG", type="Baboon")
    chosen = params(event_at=START + timedelta(days=3))
    period = Period(key="main", time_from=chosen.time_from, time_to=chosen.time_to)
    figures = cardiac.subject_figures(
        readings_over(6), period, UTC, chosen, FIVE_MIN, (0.0, 0.0, "sun"), chosen.event_at
    )
    document = cardiac.build_document(
        [subject], [period], {(subject.id, "main"): figures}, chosen, [], 0, 0
    ).model_dump(mode="json")
    inp = ReportInput(
        document=document,
        parameters=chosen.model_dump(mode="json"),
        module="cardiac",
        run_name="A week of GAG",
        project_name="Demo park",
        timezone="UTC",
        created_by="Ada",
        created_at=START,
        computed_at=START,
        version="v2.9.0",
    )
    labels = labels_for("cardiac", document)
    box_chart = next(c for c in document["charts"] if c["key"] == "parts_activity")
    assert "<svg" in chart_svg(box_chart, labels, {})
    html = render_html(inp)
    assert "Cardiac monitoring" in html
    assert "Activity by day, night and resting" in html
    assert CARDIAC_LIMITATIONS[0][:40] in html
    assert MOVEMENT_LIMITATIONS[0][:40] not in html
    assert "no fixes" not in html
