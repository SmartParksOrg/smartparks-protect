"""A device time ahead of its delivery (decision D119): beyond the tolerance it is reported,
within it or in the past it is not."""

from datetime import UTC, datetime, timedelta

from shared.timeutil import clock_ahead

RECEIVED = datetime(2026, 9, 7, 13, 0, tzinfo=UTC)


def test_within_the_tolerance_is_fine():
    assert clock_ahead(RECEIVED + timedelta(minutes=30), RECEIVED, 3600) == 0.0


def test_a_late_record_is_never_ahead():
    assert clock_ahead(RECEIVED - timedelta(days=50), RECEIVED, 3600) == 0.0


def test_years_ahead_is_reported_in_seconds():
    assert clock_ahead(RECEIVED + timedelta(days=1459), RECEIVED, 3600) == 1459 * 86400
