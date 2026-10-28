"""Movement from two sources (Tim, 2026-09-14 and 2026-10-28). The accelerometer sample every
status message carries is one snapshot of gravity plus motion, so the value says little, but
the change of the vector between two status messages says whether the device changed its
posture. The decoder stores that change as the `activity` measurement (m/s²), keeps the time
of the last change above the threshold on the current state, and the health line, the panels
and the immobility rule read it. The fixes are the other source (decision D363): a valid fix
farther from the previous valid fix than the GPS jitter is movement whatever the accelerometer
saw, since a device lying flat in a car keeps its posture for a whole drive and one sample an
hour at a steady speed looks like a parked one. The current state keeps the newest of each,
and the line shows the newer of the two and names it. Pure: no database access."""

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
#: this size is a person handling the hardware or an animal getting up: either way something
#: happened. Without it a single clear jump between two quiet messages would be thrown away.
MOVEMENT_ALONE_MPS2 = 2.0
#: A valid fix at least this far from the previous valid fix is movement (decision D363). A
#: parked receiver wanders a few metres between fixes; SP051307 parked in Namibia on
#: 2026-10-28 summed 31 to 124 m over an hour of fixes five minutes apart, up to 22 m a step.
#: A fix whose own accuracy is worse than this bar must beat that accuracy instead.
FIX_MOVEMENT_MIN_M = 50.0
#: Hours without movement before the health line warns, and before it is critical.
STILL_WARN_HOURS = 12
STILL_CRITICAL_HOURS = 24
#: The words of the two sources on the health line.
SOURCE_POSITIONS = "positions"
SOURCE_ACCELEROMETER = "accelerometer"

Sample = tuple[tuple[float, float, float], datetime]


def activity_between(
    previous: tuple[float, float, float], sample: tuple[float, float, float]
) -> float:
    """The length of the change of the acceleration vector, in m/s²."""
    return round(math.sqrt(sum((a - b) ** 2 for a, b in zip(sample, previous, strict=True))), 3)


def complete_samples(rows: Iterable[tuple[datetime, str, Any]]) -> list[Sample]:
    """The accelerometer samples among measurement rows of (time, metric key, value), in time
    order, keeping only the times that carry all three axes as numbers."""
    by_time: dict[datetime, dict[str, float]] = {}
    for time, key, value in rows:
        if key in AXES and isinstance(value, int | float) and not isinstance(value, bool):
            by_time.setdefault(time, {})[key] = float(value)
    return [
        ((values[AXES[0]], values[AXES[1]], values[AXES[2]]), time)
        for time, values in sorted(by_time.items())
        if all(axis in values for axis in AXES)
    ]


def derive_activity(
    measurements: Iterable[DecodedMeasurement], previous: Sample | None
) -> list[DecodedMeasurement]:
    """The `activity` measurements to add for the accelerometer samples among the decoded
    measurements: each sample against the one before it (the newest sample the device has
    before the frame, then the earlier samples of the same delivery), in time order; a sample
    not later than the one before it gets none."""
    kinds: dict[datetime, str] = {}
    for m in measurements:
        if m.metric_key in AXES:
            kinds[m.time] = m.record_type
    out: list[DecodedMeasurement] = []
    last = previous
    for sample, time in complete_samples(
        (m.time, m.metric_key, m.value) for m in measurements if m.metric_key in AXES
    ):
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
    moderate threshold now and then (the PWN scanners did it 540 times in eleven days, and 33 of
    the 45 read "moving" because of it) while an animal that moves produces a run. But a single
    clear jump is movement too: waiting for a second would throw away the moment a person picks
    the device up, and that is exactly what somebody looking at the record wants to find.

    Measured over those eleven days on the 45 devices bolted to posts: 540 crossings of the old
    single 1.0 threshold become about 25 under this rule, while samples from devices that really
    move are kept in full above the larger bar and in runs below it.

    `previous` is the activity of the sample before the first one given, so a run that begins
    before these samples is not missed.
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


def fix_moved(distance_m: float, accuracy_m: float | None) -> bool:
    """Whether a valid fix this far from the previous valid fix counts as movement: farther
    than the jitter bar, and farther than its own accuracy when that is worse."""
    bar = max(FIX_MOVEMENT_MIN_M, accuracy_m or 0.0)
    return distance_m > bar


def last_movement(
    accelerometer_at: datetime | None, fix_at: datetime | None
) -> tuple[datetime | None, str | None]:
    """The newest movement of the two sources and which one saw it."""
    if fix_at is not None and (accelerometer_at is None or fix_at >= accelerometer_at):
        return fix_at, SOURCE_POSITIONS
    if accelerometer_at is not None:
        return accelerometer_at, SOURCE_ACCELEROMETER
    return None, None


def still_level(hours: float) -> str:
    if hours >= STILL_CRITICAL_HOURS:
        return "critical"
    if hours >= STILL_WARN_HOURS:
        return "warn"
    return "ok"


def movement_text(
    accelerometer_at: datetime | None,
    last_status_at: datetime | None,
    now: datetime,
    fix_at: datetime | None = None,
) -> tuple[str, str | None, datetime | None]:
    """The health line's text, level and time: "moving" while the newest movement of either
    source is younger than the warning, "still for N h" after, each naming the source that saw
    the movement last, and no level when no movement was seen yet."""
    at, source = last_movement(accelerometer_at, fix_at)
    if at is None or source is None:
        return "no movement seen yet", None, last_status_at
    hours = (now - at).total_seconds() / 3600
    level = still_level(hours)
    words = "positions" if source == SOURCE_POSITIONS else "accelerometer samples"
    if level == "ok":
        return f"moving ({words})", level, at
    days, rest = divmod(int(hours), 24)
    text = f"still for {days} d {rest} h" if days else f"still for {rest} h"
    return f"{text} ({words})", level, at
