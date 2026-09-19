"""Movement from the accelerometer sample every status message carries (Tim, 2026-09-14): a
device's `acceleration_x/y/z` is one snapshot of gravity plus motion, so the value says
little, but the change of the vector between two status messages says whether the device
moved at all. The decoder stores that change as the `activity` measurement (m/s²), keeps
the time of the last change above the threshold on the current state, and the health line,
the panels and the immobility rule read it. Pure: no database access."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from shared.device_drivers.base import DecodedMeasurement

AXES = ("acceleration_x", "acceleration_y", "acceleration_z")
#: What one step of an OpenCollar's accelerometer is worth: an 8-bit sample over ±100 m/s²,
#: reported in steps of two counts. A device bolted to a post still reports changes in
#: multiples of this as the temperature drifts, and those changes are the sensor's resolution
#: rather than anything that happened (Tim, 2026-09-19, of the PWN scanners reading "moving").
SENSOR_STEP_MPS2 = 0.784
#: Below this change of the acceleration vector between two status messages the device is taken
#: as still. Above the square root of three times the step, the 1.36 m/s2 a bolted-down device
#: shows when all three axes drift by one step at once, because below that a change cannot be
#: told from the sensor reading itself differently. A worn device moves by 1.5 to 6 m/s2 between
#: hourly messages.
MOVEMENT_THRESHOLD_MPS2 = 1.4
#: A change this large is movement on its own, without waiting for a second. A device on a post
#: crossed it 7 times in eleven days against 540 crossings of the threshold above, and a jump of
#: this size is a person handling the hardware or an animal getting up — either way something
#: happened. Without it a single clear jump between two quiet messages would be thrown away.
MOVEMENT_ALONE_MPS2 = 2.0
#: Hours without movement before the health line warns, and before it is critical.
STILL_WARN_HOURS = 12
STILL_CRITICAL_HOURS = 24

Sample = tuple[tuple[float, float, float], datetime]


def activity_between(
    previous: tuple[float, float, float], sample: tuple[float, float, float]
) -> float:
    """The length of the change of the acceleration vector, in m/s²."""
    return round(math.sqrt(sum((a - b) ** 2 for a, b in zip(sample, previous, strict=True))), 3)


def previous_sample(latest_measurements: dict[str, Any] | None) -> Sample | None:
    """The newest accelerometer sample the current state holds, when it holds all three axes
    at one time."""
    if not latest_measurements:
        return None
    entries = [latest_measurements.get(axis) for axis in AXES]
    if not all(isinstance(e, dict) and isinstance(e.get("value"), int | float) for e in entries):
        return None
    times = {str(e["time"]) for e in entries if e and e.get("time")}
    if len(times) != 1:
        return None
    return (
        tuple(float(e["value"]) for e in entries),  # type: ignore[index,return-value]
        datetime.fromisoformat(times.pop()),
    )


def derive_activity(
    measurements: Iterable[DecodedMeasurement], previous: Sample | None
) -> list[DecodedMeasurement]:
    """The `activity` measurements to add for the accelerometer samples among the decoded
    measurements: each sample against the one before it (the state's newest, then the
    earlier samples of the same delivery), in time order; a sample not later than the one
    before it (a replay) gets none."""
    by_time: dict[datetime, dict[str, float]] = {}
    kinds: dict[datetime, str] = {}
    for m in measurements:
        if m.metric_key in AXES and isinstance(m.value, int | float):
            by_time.setdefault(m.time, {})[m.metric_key] = float(m.value)
            kinds[m.time] = m.record_type
    out: list[DecodedMeasurement] = []
    last = previous
    for time in sorted(by_time):
        values = by_time[time]
        if any(axis not in values for axis in AXES):
            continue
        sample = (values[AXES[0]], values[AXES[1]], values[AXES[2]])
        if last is not None and time > last[1]:
            out.append(
                DecodedMeasurement(
                    time=time,
                    metric_key="activity",
                    value=activity_between(last[0], sample),
                    record_type=kinds[time],
                )
            )
        if last is None or time > last[1]:
            last = (sample, time)
    return out


def movement_times(
    activities: Iterable[tuple[datetime, float]], previous: float | None
) -> list[datetime]:
    """The moments a device is taken to have moved, from its activity samples in time order.

    One big change, or two moderate ones in a row. A device on a post drifts past any single
    moderate threshold now and then — the PWN scanners did it 540 times in eleven days, and 33 of
    the 45 read "moving" because of it — while an animal that moves produces a run. But a single
    clear jump is movement too: waiting for a second would throw away the moment a person picks
    the device up, and that is exactly what somebody looking at the record wants to find.

    Measured over those eleven days on the 45 devices bolted to posts: 540 crossings of the old
    single 1.0 threshold become about 25 under this rule, while samples from devices that really
    move are kept in full above the larger bar and in runs below it.

    `previous` is the newest activity the device already had, so a run that begins in one
    delivery and continues in the next is not missed.
    """
    out: list[datetime] = []
    last = previous
    for time, value in activities:
        alone = value >= MOVEMENT_ALONE_MPS2
        sustained = (
            value >= MOVEMENT_THRESHOLD_MPS2
            and last is not None
            and last >= MOVEMENT_THRESHOLD_MPS2
        )
        if alone or sustained:
            out.append(time)
        last = value
    return out


def still_level(hours: float) -> str:
    if hours >= STILL_CRITICAL_HOURS:
        return "critical"
    if hours >= STILL_WARN_HOURS:
        return "warn"
    return "ok"


def movement_text(
    last_movement_at: datetime | None, last_status_at: datetime | None, now: datetime
) -> tuple[str, str | None, datetime | None]:
    """The health line's text, level and time: "moving" while the last change is younger
    than the warning, "still for N h" after, and no level when no movement was seen yet."""
    if last_movement_at is None:
        return "no movement seen yet", None, last_status_at
    hours = (now - last_movement_at).total_seconds() / 3600
    level = still_level(hours)
    if level == "ok":
        return "moving", level, last_movement_at
    days, rest = divmod(int(hours), 24)
    text = f"still for {days} d {rest} h" if days else f"still for {rest} h"
    return text, level, last_movement_at
