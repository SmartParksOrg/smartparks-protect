"""A reboot from the uptime of status messages (Tim, 2026-09-14): a collar reports its uptime
in whole days, so an uptime lower than the one before it means the device started again.
The decoder writes a `device_reset` event with the reset reason the status carries and keeps
the time on the device's current state; the health line warns for a day after. Pure."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from shared.device_drivers.base import DecodedEvent, DecodedMeasurement, DecodedState
from shared.enums import Severity

REBOOT_WARN_HOURS = 24


def previous_uptime(latest_measurements: dict[str, Any] | None) -> tuple[float, datetime] | None:
    """The newest uptime the current state holds, in seconds, with its time."""
    entry = (latest_measurements or {}).get("uptime")
    if not isinstance(entry, dict) or not isinstance(entry.get("value"), int | float):
        return None
    if not entry.get("time"):
        return None
    return float(entry["value"]), datetime.fromisoformat(str(entry["time"]))


def reset_reason(state: dict[str, Any] | None) -> str | None:
    """The reset reason flags of a status state that are on, as words."""
    flags = (state or {}).get("reset_reason")
    if not isinstance(flags, dict):
        return None
    active = [k for k, v in flags.items() if v]
    return ", ".join(active) if active else None


def detect_reboots(
    measurements: Iterable[DecodedMeasurement],
    states: Iterable[DecodedState],
    previous: tuple[float, datetime] | None,
) -> list[DecodedEvent]:
    """A `device_reset` event for every uptime that is lower than the one before it, in time
    order, against the state's newest first; the reason comes from the status of the same
    moment when it carries one."""
    uptimes: list[tuple[datetime, float]] = []
    for m in measurements:
        if m.metric_key == "uptime" and isinstance(m.value, int | float):
            uptimes.append((m.time, float(m.value)))
    uptimes.sort()
    reasons = {s.time: reset_reason(s.state) for s in states}
    out: list[DecodedEvent] = []
    last = previous
    for time, value in uptimes:
        if last is not None and time > last[1] and value < last[0]:
            reason = reasons.get(time)
            out.append(
                DecodedEvent(
                    time=time,
                    event_type="device_reset",
                    title=f"Device rebooted ({reason})" if reason else "Device rebooted",
                    severity=Severity.WARNING,
                    context={
                        "uptime_before_seconds": last[0],
                        "uptime_seconds": value,
                        **({"reset_reason": reason} if reason else {}),
                    },
                    record_type="status",
                )
            )
        if last is None or time > last[1]:
            last = (value, time)
    return out


def reboot_note(
    last_reset_at: datetime | None, state: dict[str, Any] | None, now: datetime
) -> tuple[str | None, str | None]:
    """The words and the level the uptime line adds for a day after a reboot."""
    if last_reset_at is None or now - last_reset_at > timedelta(hours=REBOOT_WARN_HOURS):
        return None, None
    hours = int((now - last_reset_at).total_seconds() // 3600)
    ago = f"{hours} h ago" if hours else "less than an hour ago"
    reason = reset_reason(state)
    return (f"rebooted {ago} ({reason})" if reason else f"rebooted {ago}"), "warn"
