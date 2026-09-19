"""A fence line's status from the FenceEdge devices on it (phase 32, decisions D263 to D265).

A fence voltage is measured at one point; the question is about a stretch of fence. A line is
cut where its monitors stand, each section reads the worse of the monitors at its ends, and the
line reads the worst of its sections. Everything above `recompute_fence` is pure and works in
metres along the line on a local flat frame, which is right for a fence and wrong for a
continent; a fence line is kilometres.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.geodesy import EARTH_RADIUS_M

#: The levels, worst last. A section's level is the worse of its ends by this order.
LEVELS: tuple[str, ...] = ("ok", "low", "unknown", "down")
RANK = {level: i for i, level in enumerate(LEVELS)}

#: What a fence line assumes when its attributes say nothing: an energiser puts out kilovolts,
#: an animal respects about four, and a wire reading under two is as good as dead.
DEFAULT_OK_V = 4000.0
DEFAULT_DOWN_V = 2000.0
#: The FenceEdge's own default `fence_interval` (research, setting 0x40).
DEFAULT_INTERVAL_S = 60.0
#: A monitor is stale when its newest reading is older than this many intervals.
STALE_INTERVALS = 2.0

FENCE_STATUS_EVENT = "FENCE_STATUS"
SEVERITY_OF = {"ok": "info", "low": "warning", "unknown": "warning", "down": "critical"}


@dataclass(frozen=True, slots=True)
class Thresholds:
    ok_v: float = DEFAULT_OK_V
    down_v: float = DEFAULT_DOWN_V
    interval_s: float = DEFAULT_INTERVAL_S

    @classmethod
    def of(cls, attributes: dict[str, Any] | None) -> Thresholds:
        """The thresholds a fence line's attributes carry under `fence`, else the defaults."""
        raw = (attributes or {}).get("fence") or {}
        return cls(
            ok_v=_number(raw.get("ok_v"), DEFAULT_OK_V),
            down_v=_number(raw.get("down_v"), DEFAULT_DOWN_V),
            interval_s=_number(raw.get("interval_s"), DEFAULT_INTERVAL_S),
        )


def _number(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, int | float) and value > 0 else fallback


@dataclass(slots=True)
class MonitorReading:
    """What one monitor last said, and where it stands along the line."""

    entity_id: uuid.UUID
    name: str
    position_m: float | None
    device_id: uuid.UUID | None = None
    voltage_v: float | None = None
    pulses: float | None = None
    measured_at: datetime | None = None
    failed: bool = False
    level: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "name": self.name,
            "device_id": str(self.device_id) if self.device_id else None,
            "position_m": round(self.position_m, 1) if self.position_m is not None else None,
            "voltage_v": self.voltage_v,
            "pulses": self.pulses,
            "measured_at": self.measured_at.isoformat() if self.measured_at else None,
            "failed": self.failed,
            "level": self.level,
        }


@dataclass(slots=True)
class Section:
    from_m: float
    to_m: float
    level: str
    monitor_ids: list[uuid.UUID] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_m": round(self.from_m, 1),
            "to_m": round(self.to_m, 1),
            "level": self.level,
            "monitor_ids": [str(m) for m in self.monitor_ids],
        }


def monitor_level(
    voltage_v: float | None,
    pulses: float | None,
    failed: bool,
    measured_at: datetime | None,
    now: datetime,
    thresholds: Thresholds,
) -> str:
    """One monitor's level from its newest reading (decision D264).

    Unknown when nothing was measured, the measurement failed, or the reading is older than
    twice the interval: a silent monitor says nothing about the wire. Down when no pulse was
    counted — a wire without pulses is dead whatever voltage the noise reads — or the voltage
    is under the down threshold. Low under the ok threshold. Ok otherwise."""
    if measured_at is None or failed or voltage_v is None:
        return "unknown"
    if (now - measured_at).total_seconds() > STALE_INTERVALS * thresholds.interval_s:
        return "unknown"
    if (pulses is not None and pulses <= 0) or voltage_v < thresholds.down_v:
        return "down"
    if voltage_v < thresholds.ok_v:
        return "low"
    return "ok"


def worse(a: str, b: str) -> str:
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def line_level(sections: list[Section]) -> str:
    level = "unknown" if not sections else "ok"
    for section in sections:
        level = worse(level, section.level)
    return level


def _flat(coordinates: list[list[float]]) -> list[tuple[float, float]]:
    """The line's vertices in metres on a frame around its middle."""
    lat0 = math.radians(sum(c[1] for c in coordinates) / len(coordinates))
    lon0 = sum(c[0] for c in coordinates) / len(coordinates)
    scale_x = EARTH_RADIUS_M * math.cos(lat0) * math.pi / 180
    scale_y = EARTH_RADIUS_M * math.pi / 180
    return [((c[0] - lon0) * scale_x, (c[1] - math.degrees(lat0)) * scale_y) for c in coordinates]


def _flat_point(coordinates: list[list[float]], lon: float, lat: float) -> tuple[float, float]:
    lat0 = math.radians(sum(c[1] for c in coordinates) / len(coordinates))
    lon0 = sum(c[0] for c in coordinates) / len(coordinates)
    scale_x = EARTH_RADIUS_M * math.cos(lat0) * math.pi / 180
    scale_y = EARTH_RADIUS_M * math.pi / 180
    return ((lon - lon0) * scale_x, (lat - math.degrees(lat0)) * scale_y)


def line_length_m(coordinates: list[list[float]]) -> float:
    """The line's length in metres, vertex to vertex."""
    flat = _flat(coordinates)
    return sum(math.dist(flat[i], flat[i + 1]) for i in range(len(flat) - 1))


def along_line(coordinates: list[list[float]], lon: float, lat: float) -> float:
    """The metres from the line's start to the nearest point of the line to (lon, lat): the
    monitor's place projected onto the fence it watches."""
    flat = _flat(coordinates)
    px, py = _flat_point(coordinates, lon, lat)
    best_d2 = math.inf
    best_at = 0.0
    walked = 0.0
    for i in range(len(flat) - 1):
        (ax, ay), (bx, by) = flat[i], flat[i + 1]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        cx, cy = ax + t * dx, ay + t * dy
        d2 = (px - cx) ** 2 + (py - cy) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_at = walked + t * math.sqrt(length2)
        walked += math.sqrt(length2)
    return best_at


def point_along(coordinates: list[list[float]], metres: float) -> tuple[float, float]:
    """The (lon, lat) on the line `metres` from its start, clamped to its ends: where an event
    about a stretch of fence is put on the map, since an event has a point and not a line."""
    flat = _flat(coordinates)
    walked = 0.0
    for i in range(len(flat) - 1):
        (ax, ay), (bx, by) = flat[i], flat[i + 1]
        step = math.dist((ax, ay), (bx, by))
        if step > 0 and walked + step >= metres:
            t = (metres - walked) / step
            lon_a, lat_a = coordinates[i][0], coordinates[i][1]
            lon_b, lat_b = coordinates[i + 1][0], coordinates[i + 1][1]
            return (lon_a + t * (lon_b - lon_a), lat_a + t * (lat_b - lat_a))
        walked += step
    return (coordinates[-1][0], coordinates[-1][1])


def sections_of(length_m: float, monitors: list[MonitorReading]) -> list[Section]:
    """The sections of a line from its monitors' places and levels (decision D264).

    No monitor: one unknown section over the whole line. One monitor: one section of its level.
    More: the monitors in order along the line, a section from the start to the first monitor
    with its level, one per gap with the worse of the two ends, and one from the last monitor
    to the end."""
    placed = sorted(
        (m for m in monitors if m.position_m is not None), key=lambda m: m.position_m or 0.0
    )
    if not placed:
        return [Section(0.0, length_m, "unknown")]
    if len(placed) == 1:
        only = placed[0]
        return [Section(0.0, length_m, only.level, [only.entity_id])]
    out: list[Section] = []
    first, last = placed[0], placed[-1]
    if (first.position_m or 0.0) > 0:
        out.append(Section(0.0, first.position_m or 0.0, first.level, [first.entity_id]))
    for a, b in pairwise(placed):
        out.append(
            Section(
                a.position_m or 0.0,
                b.position_m or 0.0,
                worse(a.level, b.level),
                [a.entity_id, b.entity_id],
            )
        )
    if (last.position_m or 0.0) < length_m:
        out.append(Section(last.position_m or 0.0, length_m, last.level, [last.entity_id]))
    return out


def changed_sections(before: list[dict[str, Any]], after: list[Section]) -> list[Section]:
    """The sections whose level differs from the stored ones, compared by their span."""
    old = {(round(s["from_m"], 1), round(s["to_m"], 1)): s["level"] for s in before}
    return [s for s in after if old.get((round(s.from_m, 1), round(s.to_m, 1))) != s.level]


@dataclass(slots=True)
class FenceReading:
    """A line's whole reading, freshly computed."""

    feature_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    level: str
    length_m: float
    sections: list[Section]
    monitors: list[MonitorReading]
    changed: list[Section]
    thresholds: Thresholds
    geometry: dict[str, Any]

    @property
    def where(self) -> tuple[float, float]:
        """The point on the line for an event about the change: the middle of the first
        changed section, or of the line."""
        coordinates = [list(c[:2]) for c in self.geometry["coordinates"]]
        first = self.changed[0] if self.changed else None
        middle = (first.from_m + first.to_m) / 2 if first else self.length_m / 2
        return point_along(coordinates, middle)


async def monitor_readings(
    session: AsyncSession,
    feature_id: uuid.UUID,
    coordinates: list[list[float]],
    now: datetime,
    thresholds: Thresholds,
) -> list[MonitorReading]:
    """What each monitor on the line last reported: its place along the line from its current
    position, its newest fence voltage and pulse count, and whether its newest measurement
    failed (the `fence_measurement` state)."""
    from sqlalchemy import func

    from shared.models import (
        DeviceStateHistory,
        Entity,
        EntityCurrentState,
        FenceMonitor,
        Measurement,
    )

    rows = (
        await session.execute(
            select(
                Entity.id,
                Entity.name,
                func.ST_X(EntityCurrentState.latest_position),
                func.ST_Y(EntityCurrentState.latest_position),
                EntityCurrentState.device_id,
            )
            .join(FenceMonitor, FenceMonitor.entity_id == Entity.id)
            .outerjoin(EntityCurrentState, EntityCurrentState.entity_id == Entity.id)
            .where(FenceMonitor.feature_id == feature_id)
            .order_by(Entity.name)
        )
    ).all()
    out: list[MonitorReading] = []
    for entity_id, name, lon, lat, device_id in rows:
        reading = MonitorReading(
            entity_id=entity_id,
            name=name,
            position_m=along_line(coordinates, float(lon), float(lat))
            if lon is not None and lat is not None
            else None,
            device_id=device_id,
        )
        if device_id is not None:
            newest = (
                await session.execute(
                    select(Measurement.metric_key, Measurement.value_num, Measurement.time)
                    .distinct(Measurement.metric_key)
                    .where(
                        Measurement.device_id == device_id,
                        Measurement.metric_key.in_(["fence_voltage", "fence_pulse_count"]),
                        Measurement.valid.is_(True),
                    )
                    .order_by(Measurement.metric_key, Measurement.time.desc())
                )
            ).all()
            for key, value, time in newest:
                if key == "fence_voltage":
                    reading.voltage_v = float(value) if value is not None else None
                    reading.measured_at = time
                elif key == "fence_pulse_count":
                    reading.pulses = float(value) if value is not None else None
            state = (
                await session.execute(
                    select(DeviceStateHistory.state, DeviceStateHistory.time)
                    .where(
                        DeviceStateHistory.device_id == device_id,
                        DeviceStateHistory.state.has_key("fence_measurement"),
                    )
                    .order_by(DeviceStateHistory.time.desc())
                    .limit(1)
                )
            ).first()
            if state is not None:
                result = state[0].get("fence_measurement")
                # a failure newer than the newest good reading means the wire is not known
                if result != "ok" and (
                    reading.measured_at is None or state[1] >= reading.measured_at
                ):
                    reading.failed = True
                    reading.measured_at = reading.measured_at or state[1]
        reading.level = monitor_level(
            reading.voltage_v, reading.pulses, reading.failed, reading.measured_at, now, thresholds
        )
        out.append(reading)
    # along the line, which is how a panel and a person read them; the unplaced last
    return sorted(out, key=lambda m: (m.position_m is None, m.position_m or 0.0))


async def recompute_fence(
    session: AsyncSession, feature_id: uuid.UUID, now: datetime
) -> FenceReading | None:
    """Read the line and its monitors again, store the reading, and say which sections changed
    level. None when the feature is not a fence line or has no line geometry."""
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping

    from shared.enums import FeatureType
    from shared.models import Feature, FenceStatus

    feature = await session.get(Feature, feature_id)
    if feature is None or feature.feature_type != FeatureType.FENCE:
        return None
    shape = to_shape(feature.geom)
    if shape.geom_type != "LineString":
        return None
    geometry = dict(mapping(shape))
    coordinates = [list(c[:2]) for c in geometry["coordinates"]]
    thresholds = Thresholds.of(feature.attributes)
    monitors = await monitor_readings(session, feature.id, coordinates, now, thresholds)
    length = line_length_m(coordinates)
    sections = sections_of(length, monitors)
    level = line_level(sections)
    status = await session.get(FenceStatus, feature.id)
    if status is None:
        status = FenceStatus(
            feature_id=feature.id, project_id=feature.project_id, level=level, changed_at=now
        )
        session.add(status)
        changed = sections
    else:
        changed = changed_sections(status.sections or [], sections)
        if changed or status.level != level:
            status.changed_at = now
    status.level = level
    status.sections = [s.as_dict() for s in sections]
    status.monitors = [m.as_dict() for m in monitors]
    status.updated_at = now
    await session.flush()
    return FenceReading(
        feature.id,
        feature.project_id,
        feature.name,
        level,
        length,
        sections,
        monitors,
        changed,
        thresholds,
        geometry,
    )


def changed_level(changed: list[Section]) -> str:
    """The worst level among the sections that changed: what the event is about."""
    level = "ok"
    for section in changed:
        level = worse(level, section.level)
    return level


def status_title(name: str, changed: list[Section], monitors: list[MonitorReading]) -> str:
    """The event's title: the line, what the changed stretch now reads, and which stretch when
    one section changed. The stretch's level and not the line's, because the line may read
    unknown for a monitor that has not spoken yet while the stretch that just reported is
    live, and the event is about what just happened."""
    words = {"ok": "live", "low": "low", "down": "down", "unknown": "unknown"}
    level = changed_level(changed)
    if len(changed) == 1 and changed[0].monitor_ids:
        names = [m.name for m in monitors if m.entity_id in changed[0].monitor_ids]
        stretch = " to ".join(names) if len(names) == 2 else (names[0] if names else "")
        if stretch:
            return f"Fence {name} reads {words[level]} near {stretch}"
    return f"Fence {name} reads {words[level]}"


def kilovolts(voltage_v: float | None) -> float | None:
    return None if voltage_v is None else round(voltage_v / 1000, 2)
