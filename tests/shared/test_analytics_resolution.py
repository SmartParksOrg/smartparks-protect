"""The bucket ladder (decisions D41 and D148): an explicit bucket too fine for the range is
answered with the finest bucket that fits, and the resolution carries the note."""

from datetime import UTC, datetime, timedelta

import pytest

from shared.analytics import MAX_BUCKETS, AnalyticsError, choose_resolution

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_a_bucket_that_fits_is_kept():
    r = choose_resolution(T0, T0 + timedelta(days=1), "1m")
    assert (r.key, r.automatic, r.requested, r.note) == ("1m", False, None, None)


def test_a_bucket_too_fine_becomes_the_finest_that_fits():
    r = choose_resolution(T0, T0 + timedelta(days=30), "1s")
    assert r.key == "15m" and r.automatic and r.requested == "1s"
    assert r.note is not None and "1s" in r.note and str(MAX_BUCKETS) in r.note
    assert timedelta(days=30) / r.width <= MAX_BUCKETS


def test_automatic_has_no_note():
    r = choose_resolution(T0, T0 + timedelta(days=30), None)
    assert r.key == "15m" and r.automatic and r.note is None


def test_unknown_and_reversed_are_still_refused():
    with pytest.raises(AnalyticsError, match="Unknown bucket"):
        choose_resolution(T0, T0 + timedelta(days=1), "2h")
    with pytest.raises(AnalyticsError, match="after"):
        choose_resolution(T0, T0, None)
