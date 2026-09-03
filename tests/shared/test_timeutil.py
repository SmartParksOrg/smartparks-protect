from datetime import UTC, datetime, timedelta, timezone

import pytest

from shared.timeutil import NaiveDatetimeError, require_aware, to_utc


def test_naive_datetime_raises():
    with pytest.raises(NaiveDatetimeError):
        require_aware(datetime(2026, 7, 15, 12, 0))


def test_to_utc_converts_offset():
    value = datetime(2026, 7, 15, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_utc(value) == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
