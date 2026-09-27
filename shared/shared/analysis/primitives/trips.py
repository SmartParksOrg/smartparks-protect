"""Trips and speeding episodes read off a vehicle's fixes (phase 39, decisions D303 and D304).

A trip starts when the vehicle moves and ends when it has stood still for the stop time; a gap
in the record closes it too, and says so. Movement is read off the folded track (`fold_stops`):
a step whose fixes stand apart after the fold left the stop radius, and a fix whose receiver
reported a speed above the moving threshold moved even when the next fix has not arrived yet.
Speeding is read off the reported speed alone: the mean over a step at hourly fixes says
nothing about a moment, and a device that reports a speed gives a better one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from shared.analysis.primitives.trajectory import Steps, Trajectory


@dataclass(slots=True)
class Trip:
    """From the fix before the first movement to the fix where the vehicle came to rest."""

    start_index: int
    end_index: int
    start_s: float
    end_s: float
    distance_m: float
    #: Still time inside the trip shorter than the stop time: a gate, a junction, a look.
    paused_s: float
    #: The fastest reported speed on the trip, or None when no fix on it carried one.
    top_reported_mps: float | None
    #: The fastest step speed, the fallback when nothing was reported.
    top_step_mps: float
    #: Fixes on the trip that carried a reported speed.
    reported: int
    #: The record fell silent before the vehicle stopped, so the trip is what was seen of it.
    cut_by_gap: bool

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def fixes(self) -> int:
        return self.end_index - self.start_index + 1

    @property
    def top_mps(self) -> float:
        return self.top_reported_mps if self.top_reported_mps is not None else self.top_step_mps

    @property
    def mean_mps(self) -> float:
        moving_s = self.duration_s - self.paused_s
        return self.distance_m / moving_s if moving_s > 0 else 0.0


@dataclass(slots=True)
class Speeding:
    """Consecutive fixes whose reported speed was above the limit."""

    start_index: int
    end_index: int
    start_s: float
    end_s: float
    top_mps: float
    top_index: int

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def moving_steps(track: Trajectory, s: Steps, moving_mps: float) -> NDArray[np.bool_]:
    """Which steps are movement: not a gap, and either the fixes stand apart (after the fold)
    or the fix the step starts from reported a speed above the threshold."""
    if len(s) == 0:
        return np.zeros(0, dtype=np.bool_)
    reported = track.speed_mps[:-1]
    fast = np.isfinite(reported) & (reported > moving_mps)
    out: NDArray[np.bool_] = (~s.gap) & ((s.dist_m > 0) | fast)
    return out


def segment_trips(track: Trajectory, s: Steps, *, moving_mps: float, stop_s: float) -> list[Trip]:
    """The trips of a folded track. A trip opens at the fix a movement starts from and closes
    at the fix where the vehicle last arrived once it has stood there for `stop_s`; a gap
    closes it at the last fix before the silence."""
    trips: list[Trip] = []
    moving = moving_steps(track, s, moving_mps)
    in_trip = False
    start = arrival = 0
    distance = paused = still_run = 0.0

    def close(cut: bool) -> None:
        if arrival <= start:
            return
        reported = track.speed_mps[start : arrival + 1]
        seen = reported[np.isfinite(reported)]
        step_speeds = s.speed_mps[start:arrival][moving[start:arrival]]
        trips.append(
            Trip(
                start_index=start,
                end_index=arrival,
                start_s=float(track.times[start]),
                end_s=float(track.times[arrival]),
                distance_m=float(distance),
                paused_s=float(paused),
                top_reported_mps=float(seen.max()) if seen.size else None,
                top_step_mps=float(step_speeds.max()) if step_speeds.size else 0.0,
                reported=int(seen.size),
                cut_by_gap=cut,
            )
        )

    for i in range(len(s)):
        if s.gap[i]:
            if in_trip:
                close(cut=True)
                in_trip = False
            continue
        if moving[i]:
            if not in_trip:
                in_trip = True
                start = i
                distance = paused = still_run = 0.0
            else:
                paused += still_run
            still_run = 0.0
            distance += float(s.dist_m[i])
            arrival = i + 1
        elif in_trip:
            still_run += float(s.dt_s[i])
            if still_run >= stop_s:
                close(cut=False)
                in_trip = False
    if in_trip:
        close(cut=False)
    return trips


def speeding_episodes(track: Trajectory, limit_mps: float) -> list[Speeding]:
    """Runs of consecutive fixes whose reported speed is above the limit; a fix without a
    reported speed ends a run, since nothing is known of that moment."""
    out: list[Speeding] = []
    speeds = track.speed_mps
    n = len(track)
    i = 0
    while i < n:
        if not (np.isfinite(speeds[i]) and speeds[i] > limit_mps):
            i += 1
            continue
        j = i
        while j + 1 < n and np.isfinite(speeds[j + 1]) and speeds[j + 1] > limit_mps:
            j += 1
        top = i + int(np.argmax(speeds[i : j + 1]))
        out.append(
            Speeding(
                start_index=i,
                end_index=j,
                start_s=float(track.times[i]),
                end_s=float(track.times[j]),
                top_mps=float(speeds[top]),
                top_index=top,
            )
        )
        i = j + 1
    return out
