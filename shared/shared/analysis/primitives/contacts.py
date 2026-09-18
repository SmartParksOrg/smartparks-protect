"""Two subjects near each other, from the sightings a device reported (design section 4.2).

The other half of the evidence, and the better half: a sighting is an observation. One device
heard another, at a moment it chose, and said so. No inference from sampling is needed and none
is made here.

What it cannot do is measure. RSSI is not converted to metres and never will be by this module:
that needs a calibration per device, per antenna and per what stands between them, which nobody
has. A signal is banded — near, middling, far — and the dBm is carried through so a reader can
judge for themselves (design 4.4).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: A sighting is a moment, so a run of them is one meeting only if they are close enough in
#: time. Longer than this between two sightings of the same pair and they are two meetings.
DEFAULT_GAP_S = 900.0

#: What a signal says about distance, in the only terms it honestly can (design 4.4).
BANDS: tuple[tuple[str, int], ...] = (("near", -70), ("middling", -85), ("far", -128))


def band_of(rssi_dbm: int | None) -> str | None:
    """The band a signal falls in, or none when the device did not report one."""
    if rssi_dbm is None:
        return None
    for name, floor in BANDS:
        if rssi_dbm >= floor:
            return name
    return BANDS[-1][0]


@dataclass(slots=True)
class Sighting:
    """One device heard another, once. The module's own view of a `device_contacts` row."""

    time: datetime
    observer: uuid.UUID
    seen: uuid.UUID
    rssi_dbm: int | None = None
    sightings: int = 1


@dataclass(slots=True)
class Meeting:
    """Consecutive sightings of one pair, close enough in time to be one encounter."""

    start: datetime
    end: datetime
    sightings: int
    strongest_dbm: int | None
    #: Which way round it was heard: a reader that does not move hearing a tag is not the same
    #: event as two collars hearing each other, and the pair figures must not blur them.
    observers: set[uuid.UUID] = field(default_factory=set)

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def band(self) -> str | None:
        return band_of(self.strongest_dbm)


@dataclass(slots=True)
class PairContacts:
    """What the sightings of two subjects say about their having been near each other."""

    meetings: list[Meeting] = field(default_factory=list)
    #: Sightings left out because they were weaker than the floor the run asked for.
    below_floor: int = 0

    @property
    def contacts(self) -> int:
        return len(self.meetings)

    @property
    def seconds(self) -> float:
        return sum(m.seconds for m in self.meetings)

    @property
    def sightings(self) -> int:
        return sum(m.sightings for m in self.meetings)

    @property
    def strongest_dbm(self) -> int | None:
        seen = [m.strongest_dbm for m in self.meetings if m.strongest_dbm is not None]
        return max(seen) if seen else None

    @property
    def first_at(self) -> datetime | None:
        return min((m.start for m in self.meetings), default=None)

    @property
    def last_at(self) -> datetime | None:
        return max((m.end for m in self.meetings), default=None)

    @property
    def band(self) -> str | None:
        """What the strongest signal of the pair says about distance, in the only terms it can."""
        return band_of(self.strongest_dbm)

    @property
    def mutual(self) -> bool:
        """Whether each heard the other. Two collars that both report are stronger evidence
        than one that reports and one that cannot."""
        return len({o for m in self.meetings for o in m.observers}) > 1


def pair_key(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """A pair named the same way whichever of the two reported it."""
    return (a, b) if str(a) <= str(b) else (b, a)


def by_pair(
    sightings: Iterable[Sighting],
    *,
    min_rssi_dbm: int | None = None,
    gap_s: float = DEFAULT_GAP_S,
    min_contact_s: float = 0.0,
) -> dict[tuple[uuid.UUID, uuid.UUID], PairContacts]:
    """Group sightings into meetings per pair.

    A pair is unordered: A hearing B and B hearing A are the same two animals together, and the
    meeting keeps both observers so the run can say whether it was heard both ways."""
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[Sighting]] = defaultdict(list)
    dropped: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    for sighting in sightings:
        key = pair_key(sighting.observer, sighting.seen)
        if (
            min_rssi_dbm is not None
            and sighting.rssi_dbm is not None
            and sighting.rssi_dbm < min_rssi_dbm
        ):
            dropped[key] += 1
            continue
        grouped[key].append(sighting)

    out: dict[tuple[uuid.UUID, uuid.UUID], PairContacts] = {}
    for key, rows in grouped.items():
        pair = PairContacts(meetings=meetings_of(rows, gap_s=gap_s, min_contact_s=min_contact_s))
        pair.below_floor = dropped.pop(key, 0)
        if pair.meetings or pair.below_floor:
            out[key] = pair
    for key, count in dropped.items():
        out[key] = PairContacts(below_floor=count)
    return out


def meetings_of(
    sightings: Sequence[Sighting], *, gap_s: float = DEFAULT_GAP_S, min_contact_s: float = 0.0
) -> list[Meeting]:
    """Sightings of one pair, in time order, cut into meetings wherever the silence is long.

    The cut matters: without it a tag heard by the same reader every five minutes for a week is
    one contact lasting seven days, which is true of the record and false of the animal."""
    rows = sorted(sightings, key=lambda s: s.time)
    if not rows:
        return []
    gap = timedelta(seconds=gap_s)
    meetings: list[Meeting] = []
    current: Meeting | None = None
    for row in rows:
        if current is None or row.time - current.end > gap:
            if current is not None:
                meetings.append(current)
            current = Meeting(
                start=row.time,
                end=row.time,
                sightings=row.sightings,
                strongest_dbm=row.rssi_dbm,
                observers={row.observer},
            )
            continue
        current.end = row.time
        current.sightings += row.sightings
        current.observers.add(row.observer)
        if row.rssi_dbm is not None and (
            current.strongest_dbm is None or row.rssi_dbm > current.strongest_dbm
        ):
            current.strongest_dbm = row.rssi_dbm
    if current is not None:
        meetings.append(current)
    # a meeting of one sighting has no duration, and dropping it on `min_contact_s` would throw
    # away the very evidence that is not an inference; only ask of it what was asked
    return [m for m in meetings if m.seconds >= min_contact_s or m.sightings == 1]
