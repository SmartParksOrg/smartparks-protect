"""What a device's battery voltage means (decision D248). A voltage on its own says nothing:
3.60 V is a full primary lithium cell and a half-empty lithium-ion one, so one set of thresholds
for every device marks healthy devices as low and misses empty ones. A device carries a battery
type; the type gives the thresholds and a curve from voltage to a share of charge, and both the
map and the device page say which type they judged by.

The type is resolved per device: the type a person set on the device, else the default of the
device type, else none, and with none the driver's own thresholds stand as before. Pure: no
database access.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

#: The device attribute a person's choice lives under: `{key, set_by, set_at}`.
BATTERY_ATTRIBUTE = "battery_type"
#: The key of the device type's default, in `device_types.default_settings`.
DEFAULT_SETTING = "battery_type"
#: The metric these thresholds judge.
METRIC_KEY = "battery_voltage"


@dataclass(frozen=True, slots=True)
class BatteryProfile:
    """One battery chemistry: what full and empty mean, when to warn, and the voltage curve.

    `curve` runs from empty to full as (volts, share of charge); the share between two points is
    interpolated. Chemistries differ in how much the curve says: a lithium-ion cell's voltage
    tracks its charge closely, a primary lithium cell holds one voltage for most of its life and
    only falls at the end, so `reliable` tells the reader how much to trust the percentage.
    """

    key: str
    label: str
    full_v: float
    empty_v: float
    warn_v: float
    critical_v: float
    curve: tuple[tuple[float, float], ...]
    reliable: bool
    note: str

    def percent(self, volts: float) -> int:
        """The share of charge left, 0 to 100, interpolated on the curve and clamped."""
        points = self.curve
        if volts <= points[0][0]:
            return 0
        if volts >= points[-1][0]:
            return 100
        for (low_v, low_p), (high_v, high_p) in pairwise(points):
            if low_v <= volts <= high_v:
                span = high_v - low_v
                share = low_p if span <= 0 else low_p + (volts - low_v) * (high_p - low_p) / span
                return round(max(0.0, min(100.0, share)))
        return 100

    def level(self, volts: float) -> str:
        """`ok`, `warn` or `critical` for this chemistry."""
        if volts < self.critical_v:
            return "critical"
        if volts < self.warn_v:
            return "warn"
        return "ok"


PROFILES: dict[str, BatteryProfile] = {
    "primary_lithium": BatteryProfile(
        key="primary_lithium",
        label="Primary lithium (LiSOCl2, 3.6 V)",
        full_v=3.67,
        empty_v=3.30,
        warn_v=3.50,
        critical_v=3.35,
        curve=(
            (3.30, 0.0),
            (3.45, 10.0),
            (3.52, 25.0),
            (3.57, 50.0),
            (3.62, 80.0),
            (3.67, 100.0),
        ),
        reliable=False,
        note=(
            "A primary lithium cell holds about 3.6 V for almost its whole life and falls only "
            "near the end, so the percentage is a rough guide; the fall itself is the signal."
        ),
    ),
    "lithium_ion": BatteryProfile(
        key="lithium_ion",
        label="Lithium-ion or lithium-polymer (4.2 V)",
        # a device on an animal is serviced by catching the animal, so the warning comes with
        # weeks of margin: about 30 percent left warns, about 10 percent is critical
        full_v=4.20,
        empty_v=3.00,
        warn_v=3.65,
        critical_v=3.40,
        curve=(
            (3.00, 0.0),
            (3.30, 5.0),
            (3.50, 15.0),
            (3.65, 30.0),
            (3.75, 45.0),
            (3.87, 65.0),
            (4.00, 85.0),
            (4.20, 100.0),
        ),
        reliable=True,
        note=(
            "A lithium-ion cell is full at 4.2 V and empty near 3.0 V; most devices stop before "
            "3.0 V to spare the cell. The voltage follows the charge, so the percentage holds."
        ),
    ),
    "lifepo4": BatteryProfile(
        key="lifepo4",
        label="Lithium iron phosphate (LiFePO4, 3.2 V)",
        full_v=3.45,
        empty_v=2.50,
        warn_v=3.10,
        critical_v=2.90,
        curve=(
            (2.50, 0.0),
            (2.90, 5.0),
            (3.10, 15.0),
            (3.20, 40.0),
            (3.27, 70.0),
            (3.35, 90.0),
            (3.45, 100.0),
        ),
        reliable=False,
        note=(
            "A LiFePO4 cell sits near 3.2 V over most of its charge, so small differences mean "
            "a lot and the percentage is a rough guide."
        ),
    ),
    "alkaline_2s": BatteryProfile(
        key="alkaline_2s",
        label="Two alkaline cells (3.0 V)",
        full_v=3.10,
        empty_v=1.80,
        warn_v=2.20,
        critical_v=2.00,
        curve=(
            (1.80, 0.0),
            (2.00, 5.0),
            (2.20, 15.0),
            (2.50, 40.0),
            (2.75, 70.0),
            (2.95, 90.0),
            (3.10, 100.0),
        ),
        reliable=True,
        note="Two alkaline cells in series: 3.0 V fresh, falling steadily to about 1.8 V.",
    ),
}


def profile_of(key: str | None) -> BatteryProfile | None:
    return PROFILES.get(key) if key else None


def chosen_key(attributes: dict[str, Any] | None) -> str | None:
    """The battery type a person set on the device, if any."""
    entry = (attributes or {}).get(BATTERY_ATTRIBUTE)
    if isinstance(entry, dict):
        key = entry.get("key")
        return str(key) if key else None
    return str(entry) if isinstance(entry, str) and entry else None


def default_key(default_settings: dict[str, Any] | None) -> str | None:
    """The battery type the device type declares for the devices of its family."""
    key = (default_settings or {}).get(DEFAULT_SETTING)
    return str(key) if isinstance(key, str) and key else None


@dataclass(frozen=True, slots=True)
class BatteryChoice:
    """The battery type in force for one device and where it came from."""

    profile: BatteryProfile | None
    source: str  # "device", "device_type", "driver" or "none"


def driver_key(driver: Any) -> str | None:
    """The battery type a driver says its family usually carries, if it says one."""
    key = getattr(driver, "default_battery_type", None)
    return str(key) if isinstance(key, str) and key else None


def resolve(
    attributes: dict[str, Any] | None,
    default_settings: dict[str, Any] | None,
    driver: Any = None,
) -> BatteryChoice:
    """Narrowest first: the type a person set on this device, then the device type's default,
    then what the driver says its family usually carries. None of the three leaves the driver's
    own `HealthField` thresholds in charge, as before."""
    chosen = profile_of(chosen_key(attributes))
    if chosen is not None:
        return BatteryChoice(chosen, "device")
    per_type = profile_of(default_key(default_settings))
    if per_type is not None:
        return BatteryChoice(per_type, "device_type")
    per_driver = profile_of(driver_key(driver))
    if per_driver is not None:
        return BatteryChoice(per_driver, "driver")
    return BatteryChoice(None, "none")
