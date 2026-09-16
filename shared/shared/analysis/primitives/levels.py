"""The level of a device performance indicator (decision D217): ok, warn or critical, from a
threshold the driver declares in its health fields where it has one, from the catalogue's
default otherwise. Every default is named here once, so the document and the docs can quote
them. Pure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from shared.device_drivers.base import HealthField

Level = Literal["ok", "warn", "critical"]
LEVELS: tuple[Level, ...] = ("ok", "warn", "critical")


@dataclass(frozen=True, slots=True)
class Threshold:
    """When a value is worrying: below a bound (strictly), at or above a bound, or as soon as
    it is positive at all (a count of things that should not happen)."""

    warn_below: float | None = None
    critical_below: float | None = None
    warn_at: float | None = None
    critical_at: float | None = None
    warn_when_positive: bool = False
    unit: str = ""

    def level(self, value: float | None) -> Level | None:
        if value is None:
            return None
        if self.critical_below is not None and value < self.critical_below:
            return "critical"
        if self.critical_at is not None and value >= self.critical_at:
            return "critical"
        if self.warn_below is not None and value < self.warn_below:
            return "warn"
        if self.warn_at is not None and value >= self.warn_at:
            return "warn"
        if self.warn_when_positive and value > 0:
            return "warn"
        return "ok"

    def describe(self) -> str:
        parts = []
        unit = f" {self.unit}" if self.unit else ""
        if self.warn_when_positive:
            parts.append("warn when any")
        if self.warn_below is not None:
            parts.append(f"warn below {self.warn_below:g}{unit}")
        if self.warn_at is not None:
            parts.append(f"warn at {self.warn_at:g}{unit}")
        if self.critical_below is not None:
            parts.append(f"critical below {self.critical_below:g}{unit}")
        if self.critical_at is not None:
            parts.append(f"critical at {self.critical_at:g}{unit}")
        return ", ".join(parts)


#: The catalogue's defaults (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, section 4), by the
#: indicator key of the result document. Shares are fractions of one.
DEFAULTS: dict[str, Threshold] = {
    "battery_v": Threshold(warn_below=3.6, critical_below=3.45, unit="V"),
    "battery_slope_mv_day": Threshold(warn_below=-5, critical_below=-15, unit="mV/day"),
    "days_to_critical": Threshold(warn_below=60, critical_below=14, unit="days"),
    "temperature_max_c": Threshold(warn_at=50, critical_at=60, unit="°C"),
    "reboots_per_week": Threshold(warn_at=1, critical_at=7),
    "error_share": Threshold(warn_at=0.10, critical_at=0.50),
    "flash_used_percent": Threshold(warn_at=80, critical_at=95, unit="%"),
    "missed_fix_share": Threshold(warn_at=0.10, critical_at=0.30),
    "missed_status_share": Threshold(warn_at=0.10, critical_at=0.30),
    "longest_silence_h": Threshold(warn_at=24, critical_at=168, unit="h"),
    "invalid_share": Threshold(warn_when_positive=True, critical_at=0.10),
    "fix_success": Threshold(warn_below=0.80, critical_below=0.50),
    "ttf_p90_s": Threshold(warn_at=120, unit="s"),
    "few_satellites_share": Threshold(warn_at=0.20),
    "accuracy_median_m": Threshold(warn_at=30, unit="m"),
    "pdop_median": Threshold(warn_at=5),
    "rejected_share": Threshold(warn_at=0.02),
    "lost_uplinks_share": Threshold(warn_at=0.05, critical_at=0.20),
    "rssi_p10_dbm": Threshold(warn_below=-120, unit="dBm"),
    "snr_p10_db": Threshold(warn_below=-15, unit="dB"),
    "joins_per_day": Threshold(warn_at=1),
    "missed_sessions_share": Threshold(warn_at=0.05, critical_at=0.20),
    "failed_sessions_share": Threshold(warn_at=0.10),
}

#: Error flags that are critical as soon as they are on at all.
CRITICAL_FLAGS = frozenset({"flash", "battery"})

#: Which indicator takes its bounds from which health field of the driver, when declared.
DRIVER_FIELDS: dict[str, str] = {
    "battery_v": "battery_voltage",
    "temperature_max_c": "device_temperature",
    "ttf_p90_s": "gnss_time_to_fix",
    "accuracy_median_m": "gnss_accuracy",
    "flash_used_percent": "flash_used_percent",
}

#: Indicators where a higher value is worse; the rest are worse when lower.
WORSE_WHEN_HIGH = frozenset(
    {
        "temperature_max_c",
        "reboots_per_week",
        "reboots",
        "error_share",
        "flash_used_percent",
        "missed_fix_share",
        "missed_status_share",
        "longest_silence_h",
        "invalid_share",
        "ttf_p90_s",
        "few_satellites_share",
        "accuracy_median_m",
        "pdop_median",
        "rejected_share",
        "lost_uplinks_share",
        "joins_per_day",
        "missed_sessions_share",
        "failed_sessions_share",
    }
)


def _from_field(field: HealthField, default: Threshold) -> Threshold:
    declared = (field.warn_below, field.critical_below, field.warn_above, field.critical_above)
    if all(v is None for v in declared):
        return default
    return Threshold(
        warn_below=field.warn_below,
        critical_below=field.critical_below,
        warn_at=field.warn_above,
        critical_at=field.critical_above,
        unit=field.unit or default.unit,
    )


def thresholds_for(fields: Iterable[HealthField] | None) -> dict[str, Threshold]:
    """The catalogue's defaults, with the driver's own bounds where it declares them."""
    out = dict(DEFAULTS)
    by_key = {f.key: f for f in fields or ()}
    for indicator, field_key in DRIVER_FIELDS.items():
        field = by_key.get(field_key)
        if field is not None:
            out[indicator] = _from_field(field, DEFAULTS[indicator])
    return out


def worst(levels: Iterable[Level | None]) -> Level | None:
    """The highest level among them, None when none is set."""
    found = [LEVELS.index(level) for level in levels if level is not None]
    return LEVELS[max(found)] if found else None


def ranks(values: dict[str, float | None], indicator: str) -> dict[str, int]:
    """The rank of every device for one indicator, 1 the worst; a device without a value has
    no rank. Ties share a rank."""
    known = [(k, v) for k, v in values.items() if v is not None]
    reverse = indicator in WORSE_WHEN_HIGH
    known.sort(key=lambda kv: kv[1], reverse=reverse)
    out: dict[str, int] = {}
    rank = 0
    previous: float | None = None
    for i, (key, value) in enumerate(known, start=1):
        if value != previous:
            rank = i
            previous = value
        out[key] = rank
    return out
