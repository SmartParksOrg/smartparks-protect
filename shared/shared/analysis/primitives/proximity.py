"""Two subjects near each other, from the fixes they made (design section 4.2).

A proximity is not an observation. Nobody saw these two animals together: they each reported
where they were, at moments that do not line up, and the fixes happened to be close. Whether
that means anything depends entirely on how often they report, which is why this module returns
what it assumed along with what it found, and why the module above it turns those assumptions
into warnings a reader cannot miss.

The work is a sweep, not a cross product: both tracks are already in time order, so walking them
together costs about the length of the two put together rather than their product. A pair of
week-long tracks at a five-minute interval is four thousand fixes each, and the cross product of
those is sixteen million distances nobody needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from shared.analysis.primitives.trajectory import Trajectory, haversine_array


@dataclass(slots=True)
class Encounter:
    """A run of consecutive samples in which the pair stayed within the distance.

    One encounter, not one row per sample: two animals standing together at a water hole for an
    hour produce a dozen fixes each, and counting those as a dozen meetings would say the herd
    is twelve times as sociable as it is."""

    start: datetime
    end: datetime
    samples: int
    closest_m: float
    mean_m: float

    @property
    def seconds(self) -> float:
        """How long the pair was together. A single sample is a moment, not a duration: nothing
        says they stayed, so it counts as zero and the run reports the count beside the time."""
        return (self.end - self.start).total_seconds()


@dataclass(slots=True)
class PairProximity:
    """What the fixes of two subjects say about their being near each other."""

    encounters: list[Encounter] = field(default_factory=list)
    #: Samples compared: fixes of A that had a fix of B close enough in time to judge.
    compared: int = 0
    #: Fixes of A with no fix of B within the time limit; the pair simply was not observed then.
    unpaired: int = 0
    #: The widest gap in time between the two fixes of a sample that counted as a proximity.
    worst_pairing_s: float = 0.0

    @property
    def contacts(self) -> int:
        return len(self.encounters)

    @property
    def seconds(self) -> float:
        return sum(e.seconds for e in self.encounters)

    @property
    def closest_m(self) -> float | None:
        return min((e.closest_m for e in self.encounters), default=None)

    @property
    def first_at(self) -> datetime | None:
        return min((e.start for e in self.encounters), default=None)

    @property
    def last_at(self) -> datetime | None:
        return max((e.end for e in self.encounters), default=None)


def pair_proximity(
    a: Trajectory,
    b: Trajectory,
    *,
    max_distance_m: float,
    max_time_s: float,
    min_contact_s: float = 0.0,
) -> PairProximity:
    """Where two tracks put their subjects within `max_distance_m` of each other.

    For every fix of `a` the nearest fix of `b` in time is found, and the pair counts only when
    those two moments lie within `max_time_s`. Nearest in time and not merely within the limit:
    of two candidate fixes the closer one is the better evidence, and taking whichever came
    first would make the answer depend on the order the tracks arrived in.

    `min_contact_s` drops encounters shorter than it, for a reader who does not want a single
    passing sample counted as a meeting.
    """
    result = PairProximity()
    if len(a) == 0 or len(b) == 0:
        return result

    # for each time in a, where it would sit in b: the neighbour on either side is the only
    # candidate for "nearest in time", since b is sorted
    right = np.searchsorted(b.times, a.times)
    left = np.clip(right - 1, 0, len(b) - 1)
    right = np.clip(right, 0, len(b) - 1)
    d_left = np.abs(a.times - b.times[left])
    d_right = np.abs(a.times - b.times[right])
    nearest = np.where(d_left <= d_right, left, right)
    apart_s = np.minimum(d_left, d_right)

    in_time = apart_s <= max_time_s
    result.unpaired = int(np.count_nonzero(~in_time))
    if not np.any(in_time):
        return result

    index = np.flatnonzero(in_time)
    partner = nearest[index]
    distance = haversine_array(a.lat[index], a.lon[index], b.lat[partner], b.lon[partner])
    result.compared = int(index.size)

    close = distance <= max_distance_m
    if not np.any(close):
        return result
    result.worst_pairing_s = float(np.max(apart_s[index][close]))

    # positions within `index`, not indices into `a`: the distances are already in this order,
    # so a run reads its own slice and the sweep stays a sweep
    at = np.flatnonzero(close)
    for run in _runs(index[at], at, a.times, max_time_s):
        times = a.times[index[run]]
        metres = distance[run]
        encounter = Encounter(
            start=_at(float(times[0])),
            end=_at(float(times[-1])),
            samples=int(run.size),
            closest_m=round(float(np.min(metres)), 1),
            mean_m=round(float(np.mean(metres)), 1),
        )
        if encounter.seconds >= min_contact_s:
            result.encounters.append(encounter)
    return result


def _runs(
    fixes: NDArray[np.int64],
    at: NDArray[np.int64],
    times: NDArray[np.float64],
    max_time_s: float,
) -> list[NDArray[np.int64]]:
    """Split the indices of close samples into runs that describe one continuous meeting.

    `fixes` are the indices into `a` of the close samples, which say whether two of them are
    neighbours; `at` are their positions among the compared samples, which is how the caller
    reads their distances. The runs come back in the second.

    Two things end a run. A fix of `a` that was not close breaks it, which is the obvious one.
    So does a silence: two close samples further apart in time than `max_time_s` say nothing
    about the hours between them, and joining them would claim the pair stayed together through
    a stretch in which neither was observed. A pair together at dawn and together at noon is two
    meetings unless something saw them in between — they had all morning to wander apart and
    come back, and a figure that says "together for six hours" would be false of the animals
    while true of the record.

    The same window the pair is judged in is the window a meeting may have a hole in, because it
    already means "near enough in time to describe one moment"."""
    if fixes.size == 0:
        return []
    skipped = np.diff(fixes) != 1
    silent = np.diff(times[fixes]) > max_time_s
    breaks = np.flatnonzero(skipped | silent) + 1
    return [part for part in np.split(at, breaks) if part.size]


def _at(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def sampling_is_coarser_than(interval_s: float | None, max_time_s: float) -> bool:
    """Whether a subject reports too seldom for its proximities to mean much (design 4.2).

    Two animals an hour apart in the record may have been a kilometre apart in between. When the
    interval a subject is expected to report at is longer than the window a proximity is judged
    in, what the run finds is a coincidence of sampling and has to say so."""
    return interval_s is not None and interval_s > max_time_s


def distance_is_within_accuracy(max_distance_m: float, accuracy_m: float | None) -> bool:
    """Whether the distance asked for is inside the error of the fixes themselves.

    Asking for a hundred metres from fixes good to a hundred metres finds pairs that are an
    artefact of the receiver, not of the animals."""
    return accuracy_m is not None and accuracy_m >= max_distance_m
