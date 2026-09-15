"""The attribution job cuts its window into pieces of one transaction each (decision D206)."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from shared.domain.attribution import WINDOW_DAYS, windows


def test_windows_cover_the_span_once_in_order():
    start = datetime(2025, 5, 15, 21, 28, 47, tzinfo=UTC)
    end = datetime(2026, 9, 15, 10, 49, 30, tzinfo=UTC)
    cut = windows(start, end)
    assert cut[0][0] == start and cut[-1][1] == end
    assert all(a[1] == b[0] for a, b in pairwise(cut))
    assert all(upper - lower <= timedelta(days=WINDOW_DAYS) for lower, upper in cut)
    assert len(cut) == 17  # 488 days in windows of 30


def test_a_short_span_is_one_window_and_an_empty_one_none():
    start = datetime(2026, 9, 1, tzinfo=UTC)
    assert windows(start, start + timedelta(hours=3)) == [(start, start + timedelta(hours=3))]
    assert windows(start, start) == []
