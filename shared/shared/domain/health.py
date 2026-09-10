"""Device health (decision D104): what a driver declares as the lines of a device's health,
read from the current state the decoder keeps (the newest value per metric, the merged state,
the times), with a level per line and for the device. Pure: no database access."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.device_drivers.base import HealthField

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
) -> DeviceHealth:
    """The health of one device from what its driver declares and the current state holds:
    the device's own status, never the network's (architecture 20, decision D161)."""
    health = DeviceHealth(last_seen_at=last_seen_at, last_status_at=latest_state_time)
    if not fields:
        return health
    measurements = latest_measurements or {}
    state = latest_state or {}
    worst = -1
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
        if level in LEVELS:
            worst = max(worst, LEVELS.index(level))
        health.fields.append(
            HealthValue(
                key=field.key,
                label=field.label,
                kind=field.kind,
                unit=field.unit,
                value=value if not isinstance(value, dict) else None,
                text=_text_of(field, value),
                level=level,
                at=at,
            )
        )
    health.level = LEVELS[worst] if worst >= 0 else None
    return health
