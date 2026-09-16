"""GNSS outliers (Tim, 2026-09-16, decisions D221 to D224): a fix that would need an
impossible speed from the last valid fix, and lies far from it, is flagged and stored invalid
until a person approves it. The rule is deliberately loose: no animal moves at 180 km/h, and
the jump floor keeps GPS scatter over a short interval from ever triggering. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.geodesy import haversine_m

#: The defaults the settings carry (`OUTLIER_MAX_SPEED_MPS`, `OUTLIER_MIN_JUMP_M`).
DEFAULT_MAX_SPEED_MPS = 50.0
DEFAULT_MIN_JUMP_M = 1000.0
EVENT_TYPE = "position_outlier"
#: The key under `positions.attributes` that marks a flagged fix and keeps the figures.
ATTRIBUTE = "outlier"


@dataclass(frozen=True, slots=True)
class Outlier:
    distance_m: float
    seconds: float
    speed_mps: float
    previous_time: datetime

    def attribute(self, *, max_speed_mps: float, min_jump_m: float) -> dict[str, Any]:
        return {
            "distance_m": round(self.distance_m),
            "seconds": round(self.seconds),
            "speed_mps": round(self.speed_mps, 1),
            "previous_time": self.previous_time.isoformat(),
            "max_speed_mps": max_speed_mps,
            "min_jump_m": min_jump_m,
        }

    def title(self) -> str:
        km = self.distance_m / 1000
        hours = self.seconds / 3600
        span = f"{hours:.1f} h" if hours >= 1 else f"{self.seconds / 60:.0f} min"
        return f"Fix {km:.0f} km from the last one in {span}: flagged as an outlier"


def outlier_of(
    previous: tuple[float, float, datetime],
    current: tuple[float, float, datetime],
    *,
    max_speed_mps: float = DEFAULT_MAX_SPEED_MPS,
    min_jump_m: float = DEFAULT_MIN_JUMP_M,
) -> Outlier | None:
    """Whether `current` (lat, lon, time) is an outlier against the last valid fix `previous`:
    farther than the jump floor and faster than the speed bound. A fix at the same moment or
    earlier is never judged (the caller compares against the fix before it in time)."""
    lat0, lon0, t0 = previous
    lat1, lon1, t1 = current
    seconds = (t1 - t0).total_seconds()
    if seconds <= 0:
        return None
    distance = haversine_m(lat0, lon0, lat1, lon1)
    if distance < min_jump_m:
        return None
    speed = distance / seconds
    if speed <= max_speed_mps:
        return None
    return Outlier(distance_m=distance, seconds=seconds, speed_mps=speed, previous_time=t0)
