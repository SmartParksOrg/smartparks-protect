"""GNSS outliers (Tim, 2026-09-16, decisions D221 to D224): a fix that would need an
impossible speed from the last valid fix, and lies far from it, is flagged and stored invalid
until a person approves it. The rule is deliberately loose: no animal moves at 180 km/h, and
the jump floor keeps GPS scatter over a short interval from ever triggering. A flagged fix
confirms itself when the next fix agrees with it (decision D360; Tim, 2026-10-27: the device
flew to Namibia and 51 fixes of the drive from the airport were flagged against a fix in
Utrecht): the device really moved, carried, and the run becomes valid at once; a single wild
fix whose successor returns to the old place stays flagged. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.geodesy import haversine_m

#: The defaults the settings carry (`OUTLIER_MAX_SPEED_MPS`, `OUTLIER_MIN_JUMP_M`).
DEFAULT_MAX_SPEED_MPS = 50.0
DEFAULT_MIN_JUMP_M = 1000.0
EVENT_TYPE = "position_outlier"
#: The event of a flagged fix the next fix confirmed (decision D360): the device moved.
CONFIRMED_EVENT_TYPE = "position_jump_confirmed"
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

    def _words(self) -> tuple[str, str]:
        km = f"{self.distance_m / 1000:.0f}"
        hours = self.seconds / 3600
        span = f"{hours:.1f} h" if hours >= 1 else f"{self.seconds / 60:.0f} min"
        return km, span

    def title(self) -> str:
        km, span = self._words()
        return f"Fix {km} km from the last one in {span}: flagged as an outlier"

    def confirmed_title(self) -> str:
        """The event of the jump once the next fix confirmed it (decision D360)."""
        km, span = self._words()
        return f"Jump of {km} km in {span} confirmed by the next fix: the device moved"

    @classmethod
    def from_attribute(cls, figures: dict[str, Any]) -> Outlier:
        """The figures a flagged row keeps under `attributes.outlier`, back as an Outlier."""
        return cls(
            distance_m=float(figures["distance_m"]),
            seconds=float(figures["seconds"]),
            speed_mps=float(figures["speed_mps"]),
            previous_time=datetime.fromisoformat(str(figures["previous_time"])),
        )


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


def agrees(
    flagged: tuple[float, float, datetime],
    current: tuple[float, float, datetime],
    *,
    max_speed_mps: float = DEFAULT_MAX_SPEED_MPS,
    min_jump_m: float = DEFAULT_MIN_JUMP_M,
) -> bool:
    """Whether `current` confirms the flagged fix `flagged` (decision D360): it comes after it
    and lies where the device could have gone from there under the same bounds, so the two
    agree with each other and disagree with the fix before them both. The device moved."""
    if (current[2] - flagged[2]).total_seconds() <= 0:
        return False
    return outlier_of(flagged, current, max_speed_mps=max_speed_mps, min_jump_m=min_jump_m) is None
