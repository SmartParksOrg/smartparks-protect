"""A subject's fixes as arrays, and the steps between them (plan, section 8.2). Fixes are the
device's own (never the network's estimates), valid, at their effective time and geometry,
attributed to the entity by the assignment history the rows already carry."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis.base import AnalysisTooLarge
from shared.curation.effective import device_fix, effective_geom, effective_time, visible
from shared.geodesy import EARTH_RADIUS_M, haversine_m
from shared.models import Position

YIELD_PER = 5_000


@dataclass(slots=True)
class Trajectory:
    """Arrays over the fixes in time order: seconds since the epoch, degrees, metres."""

    entity_id: uuid.UUID
    times: NDArray[np.float64]
    lat: NDArray[np.float64]
    lon: NDArray[np.float64]
    accuracy_m: NDArray[np.float64]  # nan when unknown
    satellites: NDArray[np.float64]  # nan when unknown
    device_ids: list[uuid.UUID]
    duplicates: int = 0

    def __len__(self) -> int:
        return int(self.times.shape[0])

    @property
    def first_at(self) -> datetime | None:
        return _at(self.times[0]) if len(self) else None

    @property
    def last_at(self) -> datetime | None:
        return _at(self.times[-1]) if len(self) else None


def _at(seconds: float) -> datetime:
    from datetime import UTC

    return datetime.fromtimestamp(float(seconds), tz=UTC)


async def load_trajectory(
    session: AsyncSession,
    entity_id: uuid.UUID,
    time_from: datetime,
    time_to: datetime,
    *,
    max_fixes: int,
) -> Trajectory:
    """The entity's device fixes in the window, streamed in time order; two fixes at the same
    effective time keep the first and count the other as a duplicate."""
    statement = (
        select(
            effective_time(Position).label("t"),
            func.ST_Y(effective_geom()).label("lat"),
            func.ST_X(effective_geom()).label("lon"),
            Position.accuracy_m,
            Position.satellites,
            Position.device_id,
        )
        .where(
            Position.entity_id == entity_id,
            effective_time(Position) >= time_from,
            effective_time(Position) < time_to,
            visible(Position),
            device_fix(),
        )
        .order_by(effective_time(Position))
        .execution_options(yield_per=YIELD_PER)
    )
    times: list[float] = []
    lat: list[float] = []
    lon: list[float] = []
    acc: list[float] = []
    sats: list[float] = []
    devices: list[uuid.UUID] = []
    duplicates = 0
    last = None
    async for row in await session.stream(statement):
        seconds = row.t.timestamp()
        if last is not None and seconds == last:
            duplicates += 1
            continue
        last = seconds
        times.append(seconds)
        lat.append(float(row.lat))
        lon.append(float(row.lon))
        acc.append(float(row.accuracy_m) if row.accuracy_m is not None else np.nan)
        sats.append(float(row.satellites) if row.satellites is not None else np.nan)
        devices.append(row.device_id)
        if len(times) > max_fixes:
            raise AnalysisTooLarge(
                f"more than {max_fixes} fixes for one subject; choose a shorter period"
            )
    return Trajectory(
        entity_id=entity_id,
        times=np.asarray(times, dtype=np.float64),
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        accuracy_m=np.asarray(acc, dtype=np.float64),
        satellites=np.asarray(sats, dtype=np.float64),
        device_ids=devices,
        duplicates=duplicates,
    )


def trajectory_from(
    entity_id: uuid.UUID,
    times: list[float],
    lat: list[float],
    lon: list[float],
) -> Trajectory:
    """A trajectory from plain lists, for tests and synthetic checks."""
    n = len(times)
    return Trajectory(
        entity_id=entity_id,
        times=np.asarray(times, dtype=np.float64),
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        accuracy_m=np.full(n, np.nan),
        satellites=np.full(n, np.nan),
        device_ids=[],
    )


@dataclass(slots=True)
class Steps:
    """Between consecutive fixes: the duration, the distance, the speed, the bearing, and
    whether the interval is a gap (longer than the threshold) rather than movement."""

    dt_s: NDArray[np.float64]
    dist_m: NDArray[np.float64]
    speed_mps: NDArray[np.float64]
    bearing_deg: NDArray[np.float64]
    gap: NDArray[np.bool_]

    def __len__(self) -> int:
        return int(self.dt_s.shape[0])


def haversine_array(
    lat1: NDArray[np.float64],
    lon1: NDArray[np.float64],
    lat2: NDArray[np.float64],
    lon2: NDArray[np.float64],
) -> NDArray[np.float64]:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2 - lon1)
    h = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    out: NDArray[np.float64] = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
    return out


def bearing_array(
    lat1: NDArray[np.float64],
    lon1: NDArray[np.float64],
    lat2: NDArray[np.float64],
    lon2: NDArray[np.float64],
) -> NDArray[np.float64]:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlmb = np.radians(lon2 - lon1)
    x = np.sin(dlmb) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dlmb)
    out: NDArray[np.float64] = (np.degrees(np.arctan2(x, y)) + 360) % 360
    return out


def steps(trajectory: Trajectory, gap_seconds: float) -> Steps:
    """The steps of a trajectory; a step longer than `gap_seconds` is a gap."""
    if len(trajectory) < 2:
        empty = np.zeros(0, dtype=np.float64)
        return Steps(empty, empty, empty, empty, np.zeros(0, dtype=np.bool_))
    dt = np.diff(trajectory.times)
    dist = haversine_array(
        trajectory.lat[:-1], trajectory.lon[:-1], trajectory.lat[1:], trajectory.lon[1:]
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(dt > 0, dist / np.where(dt > 0, dt, 1), np.nan)
    bearing = bearing_array(
        trajectory.lat[:-1], trajectory.lon[:-1], trajectory.lat[1:], trajectory.lon[1:]
    )
    return Steps(dt, dist, speed, bearing, dt > gap_seconds)


def turning_angles(s: Steps) -> NDArray[np.float64]:
    """The change of bearing between consecutive non-gap steps, in degrees from -180 to 180
    (left negative, right positive)."""
    if len(s) < 2:
        return np.zeros(0, dtype=np.float64)
    both = ~s.gap[:-1] & ~s.gap[1:]
    change = (s.bearing_deg[1:] - s.bearing_deg[:-1] + 540) % 360 - 180
    out: NDArray[np.float64] = change[both]
    return out


def time_weights(trajectory: Trajectory, gap_seconds: float) -> NDArray[np.float64]:
    """Seconds each fix stands for: half of the interval to the fix before and half to the fix
    after, each capped at the gap threshold, so a silent day puts no time anywhere."""
    n = len(trajectory)
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    dt = np.minimum(np.diff(trajectory.times), gap_seconds) if n > 1 else np.zeros(0)
    weights = np.zeros(n, dtype=np.float64)
    weights[:-1] += dt / 2
    weights[1:] += dt / 2
    return weights


def exclude_impossible(trajectory: Trajectory, max_speed_mps: float) -> tuple[Trajectory, int]:
    """Drop fixes that would need more than `max_speed_mps` from the last kept fix (so one
    outlier goes and the fix after it, measured from the fix before the outlier, stays);
    returns the trajectory without them and how many went."""
    n = len(trajectory)
    keep = np.ones(n, dtype=np.bool_)
    if n > 1:
        s = steps(trajectory, np.inf)
        suspect = np.where((s.speed_mps > max_speed_mps) & (s.dt_s > 0))[0] + 1
        if suspect.size:
            anchor = 0
            for i in range(1, n):
                dt = trajectory.times[i] - trajectory.times[anchor]
                dist = haversine_m(
                    trajectory.lat[anchor],
                    trajectory.lon[anchor],
                    trajectory.lat[i],
                    trajectory.lon[i],
                )
                if dt > 0 and dist / dt > max_speed_mps:
                    keep[i] = False
                else:
                    anchor = i
    if keep.all():
        return trajectory, 0
    kept = Trajectory(
        entity_id=trajectory.entity_id,
        times=trajectory.times[keep],
        lat=trajectory.lat[keep],
        lon=trajectory.lon[keep],
        accuracy_m=trajectory.accuracy_m[keep],
        satellites=trajectory.satellites[keep],
        device_ids=[d for d, k in zip(trajectory.device_ids, keep, strict=False) if k]
        if trajectory.device_ids
        else [],
        duplicates=trajectory.duplicates,
    )
    return kept, int((~keep).sum())
