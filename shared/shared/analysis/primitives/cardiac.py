"""What a run can say about a cardiac tag's readings (phase 34, decision D284).

Pure numpy over the arrays a module loads, so every figure here is testable without a database.
The arithmetic that turns a tag's bytes into a heart rate lives in the OpenCollar driver, not
here: by the time these functions see a value it is already beats per minute.

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
    start, end = quiet
    inside = (
        (hours >= start) & (hours <= end) if start <= end else (hours >= start) | (hours <= end)
    )
    chosen = values[inside & np.isfinite(values)]
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


def temperature_disagreement(
    tag: NDArray[np.float64], collar: NDArray[np.float64], limit_c: float
) -> float | None:
    """How far the tag's temperature sits from the collar's own, as the median difference, or
    None when one of them has nothing. A tag that has fallen off the animal reads the air while
    the collar still reads the animal, so a large steady difference is the sign worth showing.

    `limit_c` is not applied here: the caller decides what counts as far, because the answer
    depends on where on the animal both sit."""
    if tag.size == 0 or collar.size == 0:
        return None
    return float(np.median(tag) - np.median(collar))
