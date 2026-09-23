"""What a run can say about a cardiac tag's readings (phase 34, decision D284).

Pure numpy over the arrays a module loads, so every figure here is testable without a database.
The arithmetic that turns a tag's bytes into a heart rate lives in the OpenCollar driver, not
here: by the time these functions see a value it is already beats per minute.

Phase 35 (decisions D287 to D290) reads every metric of the record the same way: in the day, the
night and the resting hours, as a rhythm over the hours of the day, as a course over the dates, and
before and after an event.

Two things shape the module and are worth stating once. A sighting without a cardiac reading is
normal, so every figure counts what it used and says what it set aside; and a tag is heard on
the collar's schedule, not the heart's, so a heart rate series is a sample of a fast signal by a
slow observer. Nothing here interpolates between readings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from shared.analysis.primitives.timeagg import sun_elevation_deg

#: Hours of the local day a resting heart rate is read from, when nobody says otherwise. The
#: quiet half of the night for most animals; it is a parameter because it is not true for all.
DEFAULT_QUIET_HOURS: tuple[int, int] = (0, 5)
#: The low quantile of those hours that is called the resting rate. Not the minimum: one bad
#: reading would then be the answer.
DEFAULT_RESTING_QUANTILE = 0.1
#: Below this many readings a distribution says more about luck than about the animal.
MIN_READINGS = 12
#: A heart rate outside this is not a heart rate. The tag reports an R-R median in one byte, so
#: 6000 / 255 is about 23 bpm at the low end and 6000 / 1 is 6000 at the high end; both ends of
#: that range are arithmetic, not physiology.
PLAUSIBLE_BPM: tuple[float, float] = (15.0, 300.0)
#: The implant's activity score is 0 to 255, and a real score never falls to 0: the implant writes
#: a 0 once an hour by a fault of its own (decision D287), so a 0 is set aside, never averaged in.
ACTIVITY_FAULT = 0.0
#: Activity above this counts as a restless moment at night; the implant's scale is unitless, so
#: it is a parameter of the run with this default.
DEFAULT_RESTLESS_ACTIVITY = 100
#: Day and night on the local clock when a subject has no position at all to read the sun at
#: (decision D288): the day from the first hour up to the second.
FALLBACK_DAY_HOURS: tuple[int, int] = (6, 18)
#: The three parts of a day every metric is read in.
PARTS = ("day", "night", "resting")
#: A night belongs to the evening it started on: its local date is read this many seconds back.
NIGHT_SHIFT_S = 12 * 3600


@dataclass(frozen=True, slots=True)
class Spread:
    """What a set of readings looks like. `n` is how many readings are behind it."""

    n: int
    mean: float
    median: float
    lowest: float
    highest: float
    p10: float
    p90: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "mean": round(self.mean, 1),
            "median": round(self.median, 1),
            "lowest": round(self.lowest, 1),
            "highest": round(self.highest, 1),
            "p10": round(self.p10, 1),
            "p90": round(self.p90, 1),
        }


def spread(values: NDArray[np.float64]) -> Spread | None:
    """The shape of a set of readings, or None when there is nothing to describe."""
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return None
    return Spread(
        n=int(clean.size),
        mean=float(np.mean(clean)),
        median=float(np.median(clean)),
        lowest=float(np.min(clean)),
        highest=float(np.max(clean)),
        p10=float(np.quantile(clean, 0.1)),
        p90=float(np.quantile(clean, 0.9)),
    )


@dataclass(frozen=True, slots=True)
class Box:
    """A box plot's five numbers: the middle half between `q1` and `q3`, the median, and the
    whiskers at the furthest readings within one and a half middle halves of the box (Tukey).
    Readings beyond the whiskers are not listed; `n` says how many readings are behind it."""

    n: int
    low: float
    q1: float
    median: float
    q3: float
    high: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "low": round(self.low, 2),
            "q1": round(self.q1, 2),
            "median": round(self.median, 2),
            "q3": round(self.q3, 2),
            "high": round(self.high, 2),
        }


def box(values: NDArray[np.float64]) -> Box | None:
    """The box of a set of readings, or None when there is nothing to draw."""
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return None
    q1, median, q3 = (float(q) for q in np.quantile(clean, [0.25, 0.5, 0.75]))
    reach = 1.5 * (q3 - q1)
    return Box(
        n=int(clean.size),
        low=float(np.min(clean[clean >= q1 - reach])),
        q1=q1,
        median=median,
        q3=q3,
        high=float(np.max(clean[clean <= q3 + reach])),
    )


def real_activity(values: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Which activity scores are readings: finite and not the implant's hourly 0 (D287)."""
    keep: NDArray[np.bool_] = np.isfinite(values) & (values != ACTIVITY_FAULT)
    return keep


def plausible(values: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Which heart rates are within the range a heart can beat at. A value outside it is the
    arithmetic of a byte, not a measurement, and is left out of every figure and counted."""
    low, high = PLAUSIBLE_BPM
    return np.isfinite(values) & (values >= low) & (values <= high)


def local_hours(times_s: NDArray[np.float64], offsets_s: NDArray[np.float64]) -> NDArray[np.int_]:
    """The hour of the local day each reading falls in, from the UTC seconds and the zone's
    offset at that moment. The offset is passed in rather than computed here so this stays pure
    and one timezone lookup serves a whole array."""
    return ((times_s + offsets_s) // 3600 % 24).astype(int)


def hour_profile(
    hours: NDArray[np.int_], values: NDArray[np.float64]
) -> list[tuple[int, float, int]]:
    """The median reading per hour of the local day: `(hour, median, count)` for the hours that
    have a reading. Hours without one are absent rather than zero, because a heart rate of zero
    is a different statement from no reading."""
    out: list[tuple[int, float, int]] = []
    for hour in range(24):
        chosen = values[hours == hour]
        chosen = chosen[np.isfinite(chosen)]
        if chosen.size:
            out.append((hour, float(np.median(chosen)), int(chosen.size)))
    return out


def in_hours(hours: NDArray[np.int_], span: tuple[int, int]) -> NDArray[np.bool_]:
    """Which readings fall in the hours from the first to the second inclusive; the span may
    wrap past midnight, which quiet hours usually do."""
    start, end = span
    if start <= end:
        return (hours >= start) & (hours <= end)
    return (hours >= start) | (hours <= end)


def daylight(times_s: NDArray[np.float64], lat: float, lon: float) -> NDArray[np.bool_]:
    """Which moments had the sun above the horizon at one place (decision D288). One place for
    the whole period, the subject's mean position: sunrise moves by minutes over the tens of
    kilometres an animal ranges, and by hours over the seasons, which this follows."""
    if times_s.size == 0:
        return np.zeros(0, dtype=bool)
    elevation = sun_elevation_deg(
        times_s, np.full(times_s.shape, lat, dtype=float), np.full(times_s.shape, lon, dtype=float)
    )
    return np.asarray(elevation > 0, dtype=bool)


def fixed_daylight(hours: NDArray[np.int_]) -> NDArray[np.bool_]:
    """Day by the clock, for a subject with no position to read the sun at."""
    start, end = FALLBACK_DAY_HOURS
    return (hours >= start) & (hours < end)


def part_masks(
    is_day: NDArray[np.bool_], hours: NDArray[np.int_], quiet: tuple[int, int]
) -> dict[str, NDArray[np.bool_]]:
    """The readings of each part of the day. Resting is the quiet hours and overlaps the night;
    it is its own question (how low the animal goes), not a third of the day."""
    return {"day": is_day, "night": ~is_day, "resting": in_hours(hours, quiet)}


def local_days(times_s: NDArray[np.float64], offsets_s: NDArray[np.float64]) -> NDArray[np.int_]:
    """The local calendar day of each reading, as days since 1970-01-01."""
    return ((times_s + offsets_s) // 86_400).astype(int)


def night_days(times_s: NDArray[np.float64], offsets_s: NDArray[np.float64]) -> NDArray[np.int_]:
    """The night each reading belongs to, named by the local date of the evening it started on,
    so a reading at 02:00 counts to the night before and not to a night of its own."""
    return local_days(times_s - NIGHT_SHIFT_S, offsets_s)


def daily_medians(
    days: NDArray[np.int_], values: NDArray[np.float64]
) -> list[tuple[int, float, int]]:
    """`(day, median, count)` per day that has a reading, in date order."""
    out: list[tuple[int, float, int]] = []
    for day in np.unique(days):
        chosen = values[(days == day) & np.isfinite(values)]
        if chosen.size:
            out.append((int(day), float(np.median(chosen)), int(chosen.size)))
    return out


def report_step_s(times_s: NDArray[np.float64]) -> float | None:
    """How far apart the reports are, as the median step between consecutive readings; what one
    reading stands for when minutes are counted. None with fewer than two readings."""
    if times_s.size < 2:
        return None
    steps = np.diff(np.sort(times_s))
    steps = steps[steps > 0]
    return float(np.median(steps)) if steps.size else None


def restless_nights(
    nights: NDArray[np.int_],
    activity: NDArray[np.float64],
    threshold: float,
    step_s: float,
) -> list[tuple[int, float, int]]:
    """`(night, minutes, readings)`: per night, the minutes with activity above the threshold,
    each reading standing for one report step. A night with fewer than `MIN_READINGS` readings
    is left out rather than counted as a quiet one: too little of it was heard."""
    out: list[tuple[int, float, int]] = []
    for night in np.unique(nights):
        chosen = activity[(nights == night) & np.isfinite(activity)]
        if chosen.size < MIN_READINGS:
            continue
        minutes = float(np.count_nonzero(chosen > threshold)) * step_s / 60
        out.append((int(night), round(minutes, 1), int(chosen.size)))
    return out


def before_after(
    times_s: NDArray[np.float64], values: NDArray[np.float64], event_s: float
) -> dict[str, object] | None:
    """The readings before and after a moment (decision D289): each side's box and the change in
    the median. A side with fewer than `MIN_READINGS` readings has no box, and then there is no
    change either: a median of three readings is not a baseline."""
    finite = np.isfinite(values)
    sides = {
        "before": box(values[finite & (times_s < event_s)]),
        "after": box(values[finite & (times_s >= event_s)]),
    }
    if all(side is None for side in sides.values()):
        return None
    usable = {k: v for k, v in sides.items() if v is not None and v.n >= MIN_READINGS}
    return {
        "before": usable["before"].as_dict() if "before" in usable else None,
        "after": usable["after"].as_dict() if "after" in usable else None,
        "difference": (
            round(usable["after"].median - usable["before"].median, 2) if len(usable) == 2 else None
        ),
    }


def resting_rate(
    hours: NDArray[np.int_],
    values: NDArray[np.float64],
    quiet: tuple[int, int] = DEFAULT_QUIET_HOURS,
    quantile: float = DEFAULT_RESTING_QUANTILE,
) -> tuple[float, int] | None:
    """The resting heart rate: a low quantile of the readings taken in the quiet hours, with the
    number of readings it rests on. None when those hours hold too few readings to mean
    anything.

    The quiet hours run from the first to the second inclusive and may wrap past midnight, which
    is what they usually do."""
    chosen = values[in_hours(hours, quiet) & np.isfinite(values)]
    if chosen.size < MIN_READINGS:
        return None
    return float(np.quantile(chosen, quantile)), int(chosen.size)


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the collar managed to hear over a period, against what its settings promised.

    `expected` is None when the device never reported its reporting interval, which is the
    common case for a device nobody has read the settings of; the shares are then None as well
    rather than a ratio against a guess."""

    heard: int
    with_reading: int
    expected: int | None
    longest_gap_s: float | None
    first_at: datetime | None
    last_at: datetime | None

    @property
    def reading_share(self) -> float | None:
        return self.with_reading / self.heard if self.heard else None

    @property
    def heard_share(self) -> float | None:
        if not self.expected:
            return None
        return min(self.heard / self.expected, 1.0)

    def as_dict(self) -> dict[str, float | int | str | None]:
        return {
            "heard": self.heard,
            "with_reading": self.with_reading,
            "expected": self.expected,
            "reading_share": None if self.reading_share is None else round(self.reading_share, 3),
            "heard_share": None if self.heard_share is None else round(self.heard_share, 3),
            "longest_gap_hours": (
                None if self.longest_gap_s is None else round(self.longest_gap_s / 3600, 2)
            ),
            "first_at": self.first_at.isoformat() if self.first_at else None,
            "last_at": self.last_at.isoformat() if self.last_at else None,
        }


def coverage(
    times_s: NDArray[np.float64],
    had_reading: NDArray[np.bool_],
    period_s: float,
    reporting_interval_s: float | None,
) -> Coverage:
    """How often the tag was heard, how often it had something to say, and the longest silence.

    The expected count comes from the device's own `cmdq_reporting_interval`, which is how often
    the collar composes a message, not how often the tag advertises. It is an upper bound on
    messages and a lower bound on sightings, so it is used as an order of magnitude and the
    share is capped at one rather than reported as 130 percent."""
    order = np.argsort(times_s)
    times_s = times_s[order]
    had_reading = had_reading[order]
    gap = float(np.max(np.diff(times_s))) if times_s.size > 1 else None
    expected = (
        int(period_s // reporting_interval_s)
        if reporting_interval_s and reporting_interval_s > 0
        else None
    )
    return Coverage(
        heard=int(times_s.size),
        with_reading=int(np.count_nonzero(had_reading)),
        expected=expected,
        longest_gap_s=gap,
        first_at=_moment(times_s, 0),
        last_at=_moment(times_s, -1),
    )


def _moment(times_s: NDArray[np.float64], index: int) -> datetime | None:
    from datetime import UTC

    if times_s.size == 0:
        return None
    return datetime.fromtimestamp(float(times_s[index]), tz=UTC)


def temperature_disagreement(tag: NDArray[np.float64], device: NDArray[np.float64]) -> float | None:
    """How far the tag's temperature sits from the device's own, as the median difference, or
    None when one of them has nothing. An implant reads the body and the device the air on the
    animal's neck, so a living animal keeps them about ten degrees apart; the sign worth showing
    is the two agreeing, which is a tag reading the same air as the device, off the animal. The
    caller decides what counts as agreeing."""
    if tag.size == 0 or device.size == 0:
        return None
    return float(np.median(tag) - np.median(device))
