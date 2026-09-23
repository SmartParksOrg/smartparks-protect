"""The cardiac primitives (phase 34, decision D284) on synthetic series, so every figure is
checked without a database. The module's own path through the API is
`tests/api/test_analysis_cardiac_run.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from shared.analysis.primitives.cardiac import (
    MIN_READINGS,
    PLAUSIBLE_BPM,
    coverage,
    hour_profile,
    local_hours,
    plausible,
    resting_rate,
    spread,
    temperature_disagreement,
)

DAY = 24 * 3600


def day_of_readings(
    start: datetime, per_hour: int = 2, night_bpm: float = 40.0, day_bpm: float = 70.0
) -> tuple[np.ndarray, np.ndarray]:
    """A day of readings with a plain rhythm: slow at night, faster by day."""
    times, values = [], []
    for hour in range(24):
        for index in range(per_hour):
            times.append((start + timedelta(hours=hour, minutes=index * 30)).timestamp())
            values.append(night_bpm if hour < 6 else day_bpm)
    return np.array(times, dtype=float), np.array(values, dtype=float)


def test_spread_describes_a_set_and_says_how_many() -> None:
    values = np.array([60.0, 62.0, 64.0, 66.0, 100.0])
    described = spread(values)
    assert described is not None
    assert described.n == 5
    assert described.median == 64.0
    assert described.highest == 100.0
    assert described.p10 < described.median < described.p90


def test_spread_of_nothing_is_nothing() -> None:
    assert spread(np.array([], dtype=float)) is None
    assert spread(np.array([np.nan, np.nan])) is None


def test_a_rate_outside_what_a_heart_does_is_not_a_reading() -> None:
    low, high = PLAUSIBLE_BPM
    values = np.array([low - 1, low, 70.0, high, high + 1, np.nan])
    assert list(plausible(values)) == [False, True, True, True, False, False]


def test_the_local_hour_follows_the_zone_and_not_utc() -> None:
    # 23:30 UTC in Amsterdam is half past one the next morning
    moment = datetime(2026, 7, 1, 23, 30, tzinfo=UTC)
    zone = ZoneInfo("Europe/Amsterdam")
    offset = zone.utcoffset(moment).total_seconds()  # type: ignore[union-attr]
    hours = local_hours(np.array([moment.timestamp()]), np.array([offset]))
    assert list(hours) == [1]


def test_the_rhythm_is_a_median_per_hour_and_skips_hours_without_readings() -> None:
    times, values = day_of_readings(datetime(2026, 7, 1, tzinfo=UTC))
    hours = local_hours(times, np.zeros_like(times))
    profile = hour_profile(hours, values)
    assert len(profile) == 24
    assert dict((h, v) for h, v, _ in profile)[3] == 40.0
    assert dict((h, v) for h, v, _ in profile)[12] == 70.0
    # an hour with nothing in it is absent rather than zero
    thin = hour_profile(np.array([5, 5, 7]), np.array([50.0, 52.0, 80.0]))
    assert [h for h, _, _ in thin] == [5, 7]


def test_the_resting_rate_is_a_low_quantile_of_the_quiet_hours() -> None:
    times, values = day_of_readings(datetime(2026, 7, 1, tzinfo=UTC), per_hour=6)
    hours = local_hours(times, np.zeros_like(times))
    rest = resting_rate(hours, values, quiet=(0, 5))
    assert rest is not None
    resting, readings = rest
    assert resting == 40.0  # the night value, not the day's
    assert readings == 6 * 6


def test_the_quiet_hours_may_wrap_past_midnight() -> None:
    times, values = day_of_readings(datetime(2026, 7, 1, tzinfo=UTC), per_hour=6)
    hours = local_hours(times, np.zeros_like(times))
    # 22:00 to 04:00 inclusive is seven hours: two evening ones at the day rate and five
    # night ones, so a low quantile still lands on the night
    rest = resting_rate(hours, values, quiet=(22, 4))
    assert rest is not None
    assert rest[0] == 40.0
    assert rest[1] == 7 * 6


def test_too_few_quiet_readings_is_no_resting_rate_rather_than_a_bad_one() -> None:
    hours = np.array([1] * (MIN_READINGS - 1))
    values = np.full(MIN_READINGS - 1, 45.0)
    assert resting_rate(hours, values, quiet=(0, 5)) is None


def test_coverage_counts_what_was_heard_and_what_carried_a_reading() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    times = np.array([start, start + 3600, start + 2 * 3600, start + 12 * 3600])
    had = np.array([True, True, False, True])
    seen = coverage(times, had, period_s=DAY, reporting_interval_s=3600)
    assert seen.heard == 4
    assert seen.with_reading == 3
    assert seen.expected == 24
    assert seen.reading_share == 0.75
    assert seen.heard_share is not None and round(seen.heard_share, 3) == round(4 / 24, 3)
    assert seen.longest_gap_s == 10 * 3600


def test_coverage_without_a_known_interval_reports_no_share() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    seen = coverage(
        np.array([start, start + 60]), np.array([True, True]), DAY, reporting_interval_s=None
    )
    assert seen.expected is None
    assert seen.heard_share is None
    assert seen.reading_share == 1.0


def test_coverage_never_reports_more_than_everything() -> None:
    """The reporting interval bounds messages, not sightings, so a device that was heard more
    often than the interval promises reads as complete rather than as 400 percent."""
    start = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    times = np.array([start + i * 60 for i in range(100)], dtype=float)
    seen = coverage(times, np.ones(100, dtype=bool), period_s=DAY, reporting_interval_s=3600)
    assert seen.heard_share == 1.0


def test_coverage_of_one_reading_has_no_gap() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    seen = coverage(np.array([start]), np.array([True]), DAY, 3600)
    assert seen.longest_gap_s is None
    assert seen.first_at == seen.last_at


def test_coverage_reads_times_in_any_order() -> None:
    start = datetime(2026, 7, 1, tzinfo=UTC).timestamp()
    times = np.array([start + 3600, start, start + 7200])
    seen = coverage(times, np.array([True, False, True]), DAY, None)
    assert seen.first_at is not None and seen.first_at.timestamp() == start
    assert seen.longest_gap_s == 3600


def test_the_two_temperatures_are_compared_by_their_medians() -> None:
    tag = np.array([38.0, 38.2, 38.4])
    collar = np.array([25.0, 25.5, 26.0])
    assert temperature_disagreement(tag, collar) == pytest.approx(12.7)
    assert temperature_disagreement(np.array([]), collar) is None
    assert temperature_disagreement(tag, np.array([])) is None
