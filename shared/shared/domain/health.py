"""Device health (decision D104): what a driver declares as the lines of a device's health,
read from the current state the decoder keeps (the newest value per metric, the merged state,
the times), with a level per line and for the device. Pure: no database access."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.device_drivers.base import HealthField
from shared.domain.battery import METRIC_KEY as BATTERY_METRIC
from shared.domain.battery import BatteryProfile
from shared.domain.movement import movement_text
from shared.domain.reboot import reboot_note
from shared.timeutil import utc_now

LEVELS = ("ok", "warn", "critical")


class HealthValue(BaseModel):
    key: str
    label: str
    kind: str
    unit: str | None = None
    value: Any = None
    text: str | None = None
    level: str | None = None
    at: datetime | None = None
    #: The share of charge left, on the battery line of a device with a battery type (D248).
    percent: int | None = None


class DeviceHealth(BaseModel):
    level: str | None = None
    last_seen_at: datetime | None = None
    last_status_at: datetime | None = None
    fields: list[HealthValue] = []


def _level_of(field: HealthField, value: Any) -> str | None:
    if field.kind == "flags" and isinstance(value, dict):
        active = [k for k, v in value.items() if v]
        if not active:
            return "ok"
        return "warn" if field.flags_are_problems else None
    if field.kind in ("number", "duration") and isinstance(value, int | float):
        if field.critical_below is not None and value < field.critical_below:
            return "critical"
        if field.critical_above is not None and value > field.critical_above:
            return "critical"
        if field.warn_below is not None and value < field.warn_below:
            return "warn"
        if field.warn_above is not None and value > field.warn_above:
            return "warn"
        if any(
            t is not None
            for t in (
                field.warn_below,
                field.warn_above,
                field.critical_below,
                field.critical_above,
            )
        ):
            return "ok"
    return None


def _text_of(field: HealthField, value: Any) -> str | None:
    if value is None:
        return None
    if field.kind == "flags" and isinstance(value, dict):
        active = [k.replace("_", " ") for k, v in value.items() if v]
        return ", ".join(active) if active else "none"
    if field.kind == "duration" and isinstance(value, int | float):
        days, rest = divmod(int(value), 86400)
        hours = rest // 3600
        return f"{days} d {hours} h" if days else f"{hours} h"
    if field.kind == "bool":
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def device_health(
    fields: tuple[HealthField, ...] | None,
    *,
    latest_measurements: dict[str, Any] | None,
    latest_state: dict[str, Any] | None,
    latest_state_time: datetime | None,
    last_seen_at: datetime | None,
    last_movement_at: datetime | None = None,
    last_reset_at: datetime | None = None,
    battery: BatteryProfile | None = None,
    now: datetime | None = None,
) -> DeviceHealth:
    """The health of one device from what its driver declares and the current state holds:
    the device's own status, never the network's (architecture 20, decision D161). A device
    that reports `activity` gets a movement line: moving, or still for so long. With a battery
    type known for the device (decision D248) that chemistry's thresholds judge the battery
    line instead of the driver's one-size ones, and the line carries the share of charge."""
    health = DeviceHealth(last_seen_at=last_seen_at, last_status_at=latest_state_time)
    if not fields:
        return health
    measurements = latest_measurements or {}
    state = latest_state or {}
    worst = -1
    if "activity" in measurements:
        move_text, move_level, move_at = movement_text(
            last_movement_at, latest_state_time, now or utc_now()
        )
        if move_level in LEVELS:
            worst = max(worst, LEVELS.index(move_level))
        health.fields.append(
            HealthValue(
                key="movement",
                label="Movement",
                kind="text",
                text=move_text,
                level=move_level,
                at=move_at,
            )
        )
    for field in fields:
        if field.source == "state":
            value, at = state.get(field.key), latest_state_time
        else:
            entry = measurements.get(field.key)
            value = entry.get("value") if isinstance(entry, dict) else None
            at = None
            if isinstance(entry, dict) and entry.get("time"):
                at = datetime.fromisoformat(str(entry["time"]))
        if value is None:
            continue
        level = _level_of(field, value)
        text = _text_of(field, value)
        percent: int | None = None
        if field.key == BATTERY_METRIC and battery is not None and isinstance(value, int | float):
            level = battery.level(float(value))
            percent = battery.percent(float(value))
            text = f"{float(value):g} V, {percent}%"
        if field.key == "uptime":
            # a reboot in the last day warns on the uptime line (Tim, 2026-09-14)
            note, note_level = reboot_note(last_reset_at, state, now or utc_now())
            if note:
                text = f"{text}, {note}" if text else note
                level = note_level
        if level in LEVELS:
            worst = max(worst, LEVELS.index(level))
        health.fields.append(
            HealthValue(
                key=field.key,
                label=field.label,
                kind=field.kind,
                unit=field.unit,
                value=value if not isinstance(value, dict) else None,
                text=text,
                level=level,
                at=at,
                percent=percent,
            )
        )
    health.level = LEVELS[worst] if worst >= 0 else None
    return health
