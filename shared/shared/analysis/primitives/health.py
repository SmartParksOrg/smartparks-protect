"""The health figures of one device over a period (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
section 4.1): a battery's slope and the days it leaves, a temperature's range, the error flags
per status and the reboots by reason. Pure: arrays and dicts in, figures out."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

DAY_S = 86_400.0


def bucket_starts(times_s: NDArray[np.float64], bucket_s: float) -> NDArray[np.float64]:
    """The start of the bucket (a day, a week) each time falls in, in seconds."""
    return np.floor(times_s / bucket_s) * bucket_s


def bucketed(
    times_s: NDArray[np.float64],
    values: NDArray[np.float64],
    bucket_s: float,
    reduce: str = "median",
) -> list[list[float]]:
    """One point per bucket, `[ms at the bucket's start, reduced value]`, buckets with no
    value left out; `reduce` is median, max, min, sum or count."""
    if times_s.size == 0:
        return []
    starts = bucket_starts(times_s, bucket_s)
    out: list[list[float]] = []
    for start in np.unique(starts):
        chosen = values[starts == start]
        chosen = chosen[~np.isnan(chosen)]
        if reduce == "count":
            value = float(chosen.size)
        elif chosen.size == 0:
            continue
        elif reduce == "max":
            value = float(chosen.max())
        elif reduce == "min":
            value = float(chosen.min())
        elif reduce == "sum":
            value = float(chosen.sum())
        else:
            value = float(np.median(chosen))
        out.append([float(start) * 1000, round(value, 4)])
    return out


def slope_per_day(times_s: NDArray[np.float64], values: NDArray[np.float64]) -> float | None:
    """The least-squares slope of the daily medians, in units per day; None with fewer than
    three days of values."""
    points = bucketed(times_s, values, DAY_S)
    if len(points) < 3:
        return None
    x = np.asarray([p[0] / 1000 / DAY_S for p in points], dtype=np.float64)
    y = np.asarray([p[1] for p in points], dtype=np.float64)
    slope = float(np.polyfit(x, y, 1)[0])
    return slope


#: A trend needs this many days of values before a slope is fitted at all.
MIN_TREND_DAYS = 5
#: Below this slope (units per day) a fit says "steady": a battery's readings step in 10 mV,
#: so a hair of slope over a flat week is noise.
MIN_TREND_SLOPE = 0.001
#: Beyond this many days a forecast is "over a year", not a number.
MAX_DAYS_TO = 365


@dataclass(slots=True)
class Trend:
    """A value's trend over the days (decision D232): the slope only when it is proven, and
    the word that says what the fit found."""

    #: Units per day, None unless the trend is proven.
    slope_per_day: float | None
    #: "falling", "rising", "steady" (a fit that is not proven) or "unknown" (too few days).
    kind: str
    #: The daily points the fit stood on.
    days: int


def battery_trend(times_s: NDArray[np.float64], values: NDArray[np.float64]) -> Trend:
    """The trend of the daily medians, proven or not: at least `MIN_TREND_DAYS` days, a slope
    of at least `MIN_TREND_SLOPE` per day that stands clear of its own standard error by a
    factor of two. A flat week with a hair of slope is "steady", not a forecast."""
    points = bucketed(times_s, values, DAY_S)
    if len(points) < MIN_TREND_DAYS:
        return Trend(None, "unknown", len(points))
    x = np.asarray([p[0] / 1000 / DAY_S for p in points], dtype=np.float64)
    y = np.asarray([p[1] for p in points], dtype=np.float64)
    coefficients, covariance = np.polyfit(x, y, 1, cov="unscaled")
    slope = float(coefficients[0])
    residuals = y - np.polyval(coefficients, x)
    # the slope's standard error from the residuals (polyfit's unscaled covariance times the
    # residual variance), zero for a perfectly straight line
    dof = max(len(points) - 2, 1)
    error = float(np.sqrt(covariance[0, 0] * (residuals @ residuals) / dof))
    if abs(slope) < MIN_TREND_SLOPE or abs(slope) < 2 * error:
        return Trend(None, "steady", len(points))
    return Trend(slope, "falling" if slope < 0 else "rising", len(points))


def days_to(value: float | None, slope_per_day_: float | None, floor: float) -> float | None:
    """The days until a falling value reaches `floor`; None when it is not falling or when
    the answer lies more than `MAX_DAYS_TO` days away, zero when it is there already."""
    if value is None or slope_per_day_ is None or slope_per_day_ >= 0:
        return None
    if value <= floor:
        return 0.0
    days = (value - floor) / -slope_per_day_
    return round(days, 1) if days <= MAX_DAYS_TO else None


def percentile(values: NDArray[np.float64], q: float) -> float | None:
    clean = values[~np.isnan(values)] if values.size else values
    if clean.size == 0:
        return None
    return round(float(np.percentile(clean, q)), 4)


def share(count: int, total: int) -> float | None:
    return round(count / total, 4) if total > 0 else None


@dataclass(slots=True)
class FlagShares:
    """Per error flag: how many statuses had it on, and the share of all statuses."""

    statuses: int
    counts: dict[str, int] = field(default_factory=dict)

    def share_of(self, flag: str) -> float | None:
        return share(self.counts.get(flag, 0), self.statuses)

    @property
    def any_share(self) -> float | None:
        """The share of statuses with at least one flag on."""
        return share(self.counts.get("__any__", 0), self.statuses)


def flag_shares(states: Iterable[dict[str, Any]], key: str = "errors") -> FlagShares:
    """The error flags of status states: `state[key]` is a dict of booleans."""
    out = FlagShares(statuses=0)
    for state in states:
        flags = state.get(key)
        if not isinstance(flags, dict):
            continue
        out.statuses += 1
        on = [name for name, value in flags.items() if value]
        for name in on:
            out.counts[name] = out.counts.get(name, 0) + 1
        if on:
            out.counts["__any__"] = out.counts.get("__any__", 0) + 1
    return out


def is_status(state: dict[str, Any]) -> bool:
    """A status state carries error flags or a reset reason; a settings state carries TLVs."""
    return "errors" in state or "reset_reason" in state


@dataclass(slots=True)
class Reboots:
    #: Every reboot with its reason, in time order.
    entries: list[tuple[datetime, str]]
    reasons: Counter[str]

    @property
    def times(self) -> list[datetime]:
        return [when for when, _ in self.entries]

    @property
    def count(self) -> int:
        return len(self.entries)

    def per_week(self, window_s: float) -> float | None:
        if window_s <= 0:
            return None
        return round(self.count / (window_s / (7 * DAY_S)), 3)


def reboots_from(events: Iterable[tuple[datetime, dict[str, Any] | None]]) -> Reboots:
    """The `device_reset` events with their reason (`context.reset_reason`, words separated
    by commas, "unknown" when none)."""
    entries: list[tuple[datetime, str]] = []
    reasons: Counter[str] = Counter()
    for when, context in events:
        reason = (context or {}).get("reset_reason")
        text = str(reason) if reason else "unknown"
        entries.append((when, text))
        reasons[text] += 1
    entries.sort(key=lambda e: e[0])
    return Reboots(entries=entries, reasons=reasons)


def versions_seen(states: Iterable[dict[str, Any]], key: str) -> list[str]:
    """The distinct values of a state key in the order first seen."""
    out: list[str] = []
    for state in states:
        value = state.get(key)
        if value is not None and str(value) not in out:
            out.append(str(value))
    return out


def at(seconds: float) -> datetime:
    return datetime.fromtimestamp(float(seconds), tz=UTC)
