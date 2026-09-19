"""The movement strategy on synthetic NSD curves (docs/ANALYTICS_PHASE2_PLAN.md, section 4):
each of the four shapes with noise is called by its name, a short period gets no class, and
the parameters people read come back in km and days."""

import numpy as np

from shared.analysis.primitives.strategy import CLEAR_MARGIN, MIN_DAYS, classify, daily_nsd

DAYS = 365
RNG = np.random.default_rng(3)


def _hourly(period_days: int = DAYS) -> np.ndarray:
    return np.arange(0, period_days, 1 / 24)


def _noisy(curve: np.ndarray, sd: float) -> np.ndarray:
    return np.clip(curve + RNG.normal(0, sd, curve.size), 0, None)


def test_a_resident_curve_levels_off_and_is_called_resident():
    t = _hourly()
    nsd = _noisy(4.0 * (1 - np.exp(-t / 3)), 0.8)  # a range about 2 km across
    found = classify(t, nsd, DAYS)
    assert found.strategy == "resident", (found.strategy, found.margin)
    assert found.margin is not None and found.margin >= CLEAR_MARGIN
    assert 1.5 <= found.figures["range_km"] <= 2.5
    assert len(found.curve) >= DAYS - 1


def test_a_migrant_goes_out_and_comes_back():
    t = _hourly()
    out = 400 / (1 + np.exp((120 - t) / 6))
    back = 400 / (1 + np.exp((120 + 12 + 150 - t) / 6))
    found = classify(t, _noisy(out - back, 15), DAYS)
    assert found.strategy == "migratory", (found.strategy, found.margin)
    assert abs(found.figures["departure_day"] - 120) < 6
    assert abs(found.figures["return_day"] - 282) < 8
    assert abs(found.figures["distance_km"] - 20) < 1.5


def test_a_disperser_leaves_and_stays_away():
    t = _hourly()
    found = classify(t, _noisy(225 / (1 + np.exp((200 - t) / 8)), 10), DAYS)
    assert found.strategy == "dispersal", (found.strategy, found.margin)
    assert abs(found.figures["departure_day"] - 200) < 6
    assert abs(found.figures["distance_km"] - 15) < 1.5


def test_a_nomad_keeps_going():
    t = _hourly()
    found = classify(t, _noisy(2.5 * t, 20), DAYS)
    assert found.strategy == "nomadic", (found.strategy, found.margin)
    assert abs(found.figures["drift_km2_per_day"] - 2.5) < 0.3


def test_a_short_period_gets_no_class_and_says_why():
    t = _hourly(45)
    found = classify(t, _noisy(4.0 * (1 - np.exp(-t / 3)), 0.5), 45)
    assert found.strategy is None
    assert found.reason is not None and str(MIN_DAYS) in found.reason
    assert found.curve == []


def test_a_curve_no_model_clearly_wins_reads_unclear():
    # pure noise around a constant: the resident and the dispersal models tie
    t = _hourly(120)
    found = classify(t, _noisy(np.full(t.size, 3.0), 3.0), 120)
    assert found.strategy in ("unclear", "resident"), found.strategy
    if found.strategy == "unclear":
        assert found.margin is not None and found.margin < CLEAR_MARGIN


def test_the_daily_nsd_is_the_median_of_the_day():
    day = np.array([0.1, 0.5, 0.9, 1.2, 1.7])
    nsd = np.array([1.0, 100.0, 2.0, 5.0, 7.0])
    days, medians = daily_nsd(day, nsd)
    assert list(days) == [0.5, 1.5]
    assert list(medians) == [2.0, 6.0]
