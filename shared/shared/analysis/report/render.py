"""The report document: a run's result laid out for A4 through a Jinja template and
WeasyPrint. The template knows nothing of the method; this module turns the document into
the blocks the template prints (title, settings, warnings, key figures, map, charts, tables,
limitations) with the same words as the interface."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from shared.analysis.report.charts import PALETTE, chart_svg
from shared.analysis.report.mapimage import PRESSURE_RAMP, MapPicture

TEMPLATES = Path(__file__).parent / "templates"
ASSETS = Path(__file__).parent / "assets"
CHART_WIDTH_IN = 3.4
CHART_HEIGHT_IN = 2.2

MODULE_LABELS = {
    "movement": "Movement",
    "grazing": "Grazing",
    "device_performance": "Device performance",
    "cardiac": "Cardiac monitoring",
}

#: The human names of the result keys, the frontend's `presentations.tsx` in English.
MOVEMENT_LABELS: dict[str, str] = {
    "subject": "Subject",
    "period": "Period",
    "main": "This period",
    "comparison": "Before",
    "mean": "Mean",
    "sd": "Standard deviation",
    "fixes": "Fixes",
    "days_with_data": "Days with data",
    "median_interval_min": "Sampling interval (min)",
    "distance_km": "Distance (km)",
    "daily_distance_km": "Daily distance (km)",
    "displacement_km": "Displacement (km)",
    "max_displacement_km": "Farthest from the start (km)",
    "mean_speed_mps": "Mean speed (m/s)",
    "median_speed_mps": "Median speed (m/s)",
    "p95_speed_mps": "95th percentile speed (m/s)",
    "stationary_share": "Stationary share",
    "moving_share": "Moving share",
    "stationary_periods": "Stationary periods",
    "day_distance_km": "Distance by day (km)",
    "night_distance_km": "Distance by night (km)",
    "mcp95_ha": "MCP 95% (ha)",
    "kde50_ha": "KDE 50% (ha)",
    "kde95_ha": "KDE 95% (ha)",
    "kde_bandwidth_m": "KDE bandwidth (m)",
    "akde50_ha": "Corrected KDE 50% (ha)",
    "akde95_ha": "Corrected KDE 95% (ha)",
    "akde_bandwidth_m": "Corrected KDE bandwidth (m)",
    "autocorrelation_h": "Autocorrelation time (h)",
    "effective_fixes": "Effective fixes",
    "strategy": "Strategy",
    "strategy_margin": "Strategy margin (AICc)",
    "strategy_distance_km": "Strategy distance (km)",
    "departure_day": "Departure (day of period)",
    "return_day": "Return (day of period)",
    "hotspot_count": "Hotspots",
    "cluster_count": "Clusters",
    "missing_share": "Missing fixes share",
    "excluded_fixes": "Excluded fixes",
    "daily_distance": "Daily distance",
    "speed_histogram": "Speed",
    "hour_profile": "Activity by hour",
    "turning": "Turning angles",
    "nsd": "Net squared displacement",
    "day_night": "Day and night",
    "summary": "Summary",
}
GRAZING_LABELS: dict[str, str] = {
    "area": "Area",
    "period": "Period",
    "herd": "Herd",
    "animal": "Animal",
    "metric": "Figure",
    "main": "This period",
    "comparison": "Before",
    "change_percent": "Change (%)",
    "area_a": "Area",
    "area_b": "Overlaps with",
    "hectares": "Hectares",
    "animal_hours": "Animal-hours",
    "animal_days": "Animal-days",
    "animal_hours_per_ha": "Use (animal-hours per ha)",
    "animal_days_per_ha": "Use (animal-days per ha)",
    "weighted_animal_days_per_ha": "Weighted use (per ha)",
    "relative_pressure": "Relative pressure",
    "pressure_rank": "Rank",
    "vegetation": "Use against vegetation",
    "ndvi_mean": "Vegetation index (NDVI)",
    "ndvi_change": "Vegetation change",
    "ndvi_valid_share": "Weeks with a clear view",
    "ndvi_level": "Level",
    "ndvi_weekly": "Vegetation index by week",
    "share_of_herd_time": "Share of herd time",
    "animals_used": "Animals that used it",
    "visits": "Visits",
    "mean_visit_hours": "Mean visit (hours)",
    "use_days": "Use days",
    "rest_days": "Rest days",
    "longest_rest_days": "Longest rest (days)",
    "last_use": "Last use",
    "hours_since_last_use": "Hours since last use",
    "hotspot_count": "Hotspots",
    "hours": "Hours",
    "weighted_hours": "Weighted hours",
    "first_use": "First use",
    "days_used": "Days used",
    "areas": "Areas",
    "animals": "Animals",
    "overlaps": "Overlaps",
    "changes": "Change against the period before",
    "timeline": "Daily animal-hours",
    "pressure": "Use per hectare",
    "summary": "Summary",
}
#: The device performance result's keys, the frontend's `devicePerformanceLabels` in English.
DEVICE_PERFORMANCE_LABELS: dict[str, str] = {
    "device": "Device",
    "period": "Period",
    "main": "This period",
    "comparison": "Before",
    "level": "Level",
    "source": "Data source",
    "channel": "Channel",
    "flag": "Error flag",
    "time": "Time",
    "reason": "Reason",
    "share": "Share",
    "sources": "Data sources",
    "statuses": "Statuses",
    "battery_v": "Battery (V)",
    "battery_min_v": "Lowest battery (V)",
    "battery_trend": "Battery trend",
    "battery_slope_mv_day": "Battery slope (mV/day)",
    "days_to_critical": "Days to critical",
    "expected_fixes": "Fixes expected",
    "missed_fix_network_share": "Missed fixes, lost on the network",
    "missed_fix_device_share": "Missed fixes, not made by the device",
    "details": "Details per device",
    "charging_days": "Charging days",
    "temperature_min_c": "Lowest temperature (°C)",
    "temperature_median_c": "Median temperature (°C)",
    "temperature_max_c": "Highest temperature (°C)",
    "hot_hours": "Hours above the warn temperature",
    "reboots": "Reboots",
    "reboots_per_week": "Reboots per week",
    "uptime_max_d": "Longest uptime (days)",
    "error_share": "Statuses with an error",
    "flash_used_percent": "Flash used (%)",
    "moving_share": "Statuses with movement",
    "firmware": "Firmware",
    "expected_fix_s": "Fix interval expected (s)",
    "expected_fix_source": "Expected interval from",
    "fix_regular_share": "Regular fixes",
    "declared_fix_s": "Fix interval set, stale (s)",
    "expected_status_source": "Status interval from",
    "override": "set by a person",
    "settings_frame": "the device's settings",
    "command": "an acknowledged command",
    "type_default": "the device type",
    "learned": "learned from the fixes",
    "unknown": "unknown",
    "expected_status_s": "Status interval set (s)",
    "fixes": "Fixes",
    "observed_fix_median_s": "Fix interval seen (s)",
    "observed_fix_p90_s": "Fix interval, 90th percentile (s)",
    "missed_fix_share": "Missed fixes",
    "observed_status_median_s": "Status interval seen (s)",
    "missed_status_share": "Missed statuses",
    "silences": "Silences",
    "longest_silence_h": "Longest silence (h)",
    "longest_silence_ended": "Longest silence ended",
    "messages": "Messages",
    "invalid_records": "Records held invalid",
    "invalid_share": "Share held invalid",
    "attempts": "GNSS attempts",
    "fix_success": "Fix success",
    "ttf_median_s": "Time to fix (s)",
    "ttf_p90_s": "Time to fix, 90th percentile (s)",
    "satellites_median": "Satellites",
    "few_satellites_share": "Fixes under four satellites",
    "accuracy_median_m": "Accuracy (m)",
    "accuracy_p90_m": "Accuracy, 90th percentile (m)",
    "poor_accuracy_share": "Fixes above the warn accuracy",
    "pdop_median": "PDOP",
    "rejected_fixes": "Rejected fixes",
    "rejected_share": "Rejected fixes share",
    "fixes_per_day": "Fixes per day",
    "per_day": "Messages per day",
    "lost_uplinks_share": "Lost uplinks",
    "gateways": "Gateways",
    "best_gateway": "Best gateway",
    "best_gateway_share": "Best gateway's share",
    "rssi_median_dbm": "RSSI (dBm)",
    "rssi_p10_dbm": "RSSI, 10th percentile (dBm)",
    "snr_median_db": "SNR (dB)",
    "snr_p10_db": "SNR, 10th percentile (dB)",
    "joins": "Joins",
    "joins_per_day": "Joins per day",
    "sessions": "Satellite sessions",
    "missed_sessions_share": "Missed sessions",
    "failed_sessions_share": "Failed sessions",
    "redeliveries": "Redeliveries",
    "bytes": "Bytes",
    "fleet": "Fleet",
    "health": "Health",
    "reporting": "Reporting",
    "gnss": "GNSS",
    "network": "Network",
    "errors": "Error flags",
    "battery": "Battery",
    "temperature": "Highest temperature per day",
    "time_to_fix": "Time to fix",
    "accuracy": "Accuracy of the fixes",
    "satellites": "Satellites per fix",
    "uplinks_per_day": "Messages per day",
    "rssi_per_day": "RSSI per day",
    "sessions_per_day": "Satellite sessions per day",
}
#: The fleet table's headline columns (the module's `FLEET_COLUMNS`), the key figures block.
DEVICE_KEY_FIGURES: list[str] = [
    "battery_v",
    "battery_slope_mv_day",
    "days_to_critical",
    "temperature_max_c",
    "reboots",
    "error_share",
    "missed_fix_device_share",
    "longest_silence_h",
    "fix_success",
    "ttf_p90_s",
    "accuracy_median_m",
    "lost_uplinks_share",
    "rssi_p10_dbm",
    "missed_sessions_share",
]
#: Short heads for the fleet table on paper, where the full labels break letter by letter.
DEVICE_SHORT_LABELS: dict[str, str] = {
    "battery_v": "Battery (V)",
    "battery_slope_mv_day": "Slope (mV/day)",
    "days_to_critical": "Days left",
    "temperature_max_c": "Max °C",
    "reboots": "Reboots",
    "error_share": "Errors",
    "missed_fix_device_share": "Missed (device)",
    "longest_silence_h": "Silence (h)",
    "fix_success": "Fix success",
    "ttf_p90_s": "TTF p90",
    "accuracy_median_m": "Accuracy (m)",
    "lost_uplinks_share": "Lost uplinks",
    "rssi_p10_dbm": "RSSI p10",
    "missed_sessions_share": "Missed sessions",
}
#: Up to this many devices the fleet table on paper stands on its side: a row per indicator.
FLEET_TRANSPOSE_MAX = 6
#: The device tables whose figures the key figures block and the area cards already carry.
DEVICE_TABLES_IN_CARDS = frozenset({"fleet", "health", "reporting", "gnss", "network"})

#: The indicators of each area's card in a device's section (the frontend's `AREA_CARDS`).
DEVICE_AREA_CARDS: list[tuple[str, list[str]]] = [
    (
        "health",
        [
            "battery_v",
            "battery_trend",
            "battery_slope_mv_day",
            "days_to_critical",
            "temperature_max_c",
            "hot_hours",
            "reboots",
            "uptime_max_d",
            "error_share",
            "flash_used_percent",
            "moving_share",
            "firmware",
        ],
    ),
    (
        "reporting",
        [
            "expected_fix_s",
            "expected_fix_source",
            "fix_regular_share",
            "declared_fix_s",
            "observed_fix_median_s",
            "missed_fix_share",
            "missed_fix_network_share",
            "missed_fix_device_share",
            "expected_status_s",
            "missed_status_share",
            "silences",
            "longest_silence_h",
            "messages",
            "invalid_records",
        ],
    ),
    (
        "gnss",
        [
            "attempts",
            "fixes",
            "fix_success",
            "ttf_median_s",
            "ttf_p90_s",
            "satellites_median",
            "few_satellites_share",
            "accuracy_median_m",
            "pdop_median",
            "rejected_share",
            "fixes_per_day",
        ],
    ),
    ("network", ["lost_uplinks_share", "rssi_p10_dbm", "missed_sessions_share", "sources"]),
]
DEVICE_PERFORMANCE_LIMITATIONS = [
    "A missed report is inferred from the device's settings and its messages; a device whose "
    "interval changed in the period, or whose settings Protect never read, shows a share to "
    "weigh, with the interval it assumed beside it.",
    "Lost uplinks come from the frame counter; a data source that does not deliver it shows no "
    "figure, not zero.",
    "The battery trend is a straight line through the daily medians, reported only when it "
    "stands clear of the noise over at least five days; a lithium cell sits on a plateau for "
    "most of its life, so a steady week predicts little and the days to critical are an "
    "indication, not a forecast.",
    "Missed fixes are split by the frame counter: the uplinks the network lost, scaled over "
    "the fixes that came, estimate the fixes that left the device; the rest is the device's "
    "own shortfall. Without a frame counter the device carries the whole share.",
    "Signal figures are the best gateway's per uplink; a moving device changes gateways, so "
    "they describe the network as the device met it.",
    "Levels come from the driver's thresholds and named defaults; they are not a verdict on "
    "the device, and a rank says only where a device stands among the chosen ones.",
    "Fix success counts the attempts the device reported; a device that never reports a failed "
    "attempt shows every attempt as a fix.",
    "Messages and the network figures count by the time a message reached Protect; a raw log "
    "uploaded later counts on the day of the upload, and its records on their own days.",
]
LEVEL_ORDER = {"critical": 0, "warn": 1, "ok": 2, None: 3}

#: The figures on a movement subject's card, with their unit (the frontend's card metrics).
MOVEMENT_KEY_FIGURES: list[tuple[str, str]] = [
    ("distance_km", "km"),
    ("daily_distance_km", "km/day"),
    ("median_speed_mps", "m/s"),
    ("stationary_share", "%"),
    ("mcp95_ha", "ha"),
    ("kde95_ha", "ha"),
    ("akde95_ha", "ha"),
    ("strategy", ""),
    ("fixes", ""),
]
GRAZING_KEY_FIGURES: list[tuple[str, str]] = [
    ("animal_days_per_ha", ""),
    ("relative_pressure", ""),
    ("pressure_rank", "#"),
    ("use_days", "days"),
    ("rest_days", "days"),
    ("longest_rest_days", "days"),
]
#: The cardiac study's keys (decisions D284 and D287 to D290), the frontend's `cardiacLabels`.
CARDIAC_LABELS: dict[str, str] = {
    "subject": "Subject",
    "cardiac": "Heart",
    "coverage": "What the device heard",
    "parts": "Day, night and resting",
    "event": "Before and after the event",
    "heart_rate": "Heart rate",
    "hrv": "Heart rate variability",
    "activity": "Activity",
    "temperature": "Tag temperature",
    "resting_heart_rate": "Resting heart rate",
    "restless": "Restless minutes per night",
    "day": "Day",
    "night": "Night",
    "resting": "Resting",
    "event_at": "Event",
    "metric": "Metric",
    "part": "Part of the day",
    "readings": "Readings",
    "median": "Median",
    "q1": "Lower quartile",
    "q3": "Upper quartile",
    "before": "Before",
    "after": "After",
    "change": "Difference",
    "rhythm_heart_rate": "Heart rate by hour of the day",
    "rhythm_hrv": "Heart rate variability by hour of the day",
    "rhythm_activity": "Activity by hour of the day",
    "rhythm_temperature": "Tag temperature by hour of the day",
    "parts_heart_rate": "Heart rate by day, night and resting",
    "parts_hrv": "Heart rate variability by day, night and resting",
    "parts_activity": "Activity by day, night and resting",
    "parts_temperature": "Tag temperature by day, night and resting",
    "daily_heart_rate": "Heart rate per day, by day and by night",
    "daily_hrv": "Heart rate variability per day, by day and by night",
    "daily_activity": "Activity per day, by day and by night",
    "daily_temperature": "Tag temperature per day, by day and by night",
}
CARDIAC_KEY_FIGURES: list[tuple[str, str]] = [
    ("heart_rate", "bpm"),
    ("resting_heart_rate", "bpm"),
    ("hrv", "ms"),
    ("activity", ""),
    ("temperature", "C"),
    ("restless", "min"),
]
CARDIAC_LIMITATIONS = [
    "What the device heard comes first: a quiet tag and a calm animal look the same in a heart "
    "rate chart, and only the coverage table tells them apart.",
    "There is no normal range. What a healthy heart rate is depends on the species, the age, "
    "the season and what the animal was doing, and none of that is in this data.",
    "The tag is sampled on the device's schedule, not the heart's; nothing is interpolated.",
    "Heart rates outside 15 to 300 bpm are the arithmetic of a byte, not a heartbeat, and are "
    "set aside and counted.",
    "Activity is the implant's own accelerometer score on a unitless scale of 0 to 255. It "
    "writes a 0 once an hour by a fault of its own; every 0 is set aside and counted.",
    "Day and night split at the horizon, by the sun at the animal's mean position in the "
    "period; without a position they fall back to 06:00 and 18:00 on the local clock, and the "
    "warnings say so. Resting is the run's quiet hours and overlaps the night.",
    "Restless minutes count the readings above the threshold at night, each standing for one "
    "report step; a night heard fewer than twelve times is left out.",
    "Before and after an event is descriptive: the medians and their middle half on each side, "
    "with no model and no p-value. One animal's record is not a sample.",
    "The tag's activity maximum, active minutes, impedance and mode sum are not interpreted.",
]
#: Options every run carries that a module does not read, left off its settings block: the
#: cardiac study has no fixes, so no gap between them.
UNUSED_OPTIONS: dict[str, tuple[str, ...]] = {"cardiac": ("gap_hours",)}
OPTION_LABELS: list[tuple[str, str]] = [
    ("gap_hours", "Gap threshold (hours)"),
    ("max_speed_mps", "Maximum plausible speed (m/s)"),
    ("cell_m", "Grid cell (m)"),
    ("revisit_hours", "Revisit after (hours)"),
    ("methods", "Home range methods"),
    ("kde_bandwidth_m", "KDE bandwidth (m)"),
    ("strategy", "Movement strategy"),
    ("weighting", "Weighting"),
    ("weight_key", "Attribute key"),
    ("min_absence_hours", "New visit after (hours away)"),
    ("rest_threshold_hours", "Rest day at or below (animal-hours)"),
    ("quiet_from_hour", "Quiet hours from"),
    ("quiet_to_hour", "Quiet hours to"),
    ("resting_quantile", "Resting quantile"),
    ("restless_activity", "Restless above (activity)"),
]
MOVEMENT_LIMITATIONS = [
    "Distance from fixes underestimates the path between them; a coarser sampling means a "
    "shorter apparent distance. The sampling interval stands next to the distance for that "
    "reason.",
    "Speed is the mean over a step, not an instantaneous speed.",
    "The KDE is an estimate of space use that depends on the bandwidth and the grid; its "
    "isopleths are unions of cells, not smooth contours.",
    "The MCP includes ground never visited between far fixes.",
    "The corrected KDE is our own approximation, not the AKDE of the reference implementation: "
    "a variogram of the fixes gives the time their position takes to decorrelate, the effective "
    "number of independent fixes follows, and the bandwidth widens with it. It needs the period "
    "to show the whole range; when the fixes are still spreading it reports that instead of an "
    "area.",
    "The movement strategy is the best of four curves fitted to the net squared displacement; a "
    "margin under two AICc units reads unclear, and a period under sixty days gets no class. "
    "The migratory curve keeps one pace for the way out and the way back.",
    "Residence time on a regular grid depends on the cell size and is biased by irregular "
    "sampling.",
    "Day and night follow the sun's elevation, not the animal's own rhythm or the cloud cover.",
    "The results describe the collared animals, not the population.",
]
GRAZING_LIMITATIONS = [
    "Time in an area is a proxy for potential grazing pressure, not measured feeding; the "
    "tables say use, not grazing.",
    "Only collared animals count; the herd is not extrapolated unless a weighting is chosen, "
    "and then the document names it.",
    "Fix sampling and gaps bias the hours; the missing fix share and the gaps are in the "
    "warnings next to the totals.",
    "Overlapping areas double-count by design; the overlap is listed.",
    "Areas are fixed polygons without validity in time; an area that changed during the "
    "period must be two features.",
    "The vegetation index is the weekly mean NDVI of Sentinel-2 over each area with clouds "
    "masked; a week without a clear view is left out, and a period with few clear weeks is "
    "marked. Greener is not more forage of the right kind; the index says how the vegetation "
    "moved, not what it is worth to the animals.",
]


@dataclass
class ReportInput:
    """Everything the template needs, gathered by the job."""

    document: dict[str, Any]
    parameters: dict[str, Any]
    module: str
    run_name: str | None
    project_name: str
    timezone: str
    created_by: str | None
    created_at: datetime
    computed_at: datetime | None
    version: str
    map: MapPicture | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def labels_for(module: str, document: dict[str, Any]) -> dict[str, str]:
    by_module = {
        "grazing": GRAZING_LABELS,
        "device_performance": DEVICE_PERFORMANCE_LABELS,
        "cardiac": CARDIAC_LABELS,
    }
    labels = dict(by_module.get(module, MOVEMENT_LABELS))
    for subject in document.get("subjects", []):
        labels[str(subject["id"])] = subject["name"]
    for area in document.get("summary", {}).get("areas") or []:
        labels[str(area["id"])] = area["name"]
    return labels


def subject_colors(document: dict[str, Any]) -> dict[str, str]:
    return {
        str(s["id"]): PALETTE[i % len(PALETTE)] for i, s in enumerate(document.get("subjects", []))
    }


def fmt_figure(value: Any, unit: str) -> str:
    """The cards' number format: a percentage, or two, one or no decimals by size."""
    if value is None or not isinstance(value, int | float):
        # a class rather than a figure (the movement strategy): a word, capitalised
        return "-" if value is None else str(value).capitalize()
    v = float(value)
    if unit == "%":
        return f"{round(v * 100)}%"
    if unit == "#":
        return f"#{int(v)}"
    text = f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}"
    return f"{text} {unit}".strip()


def fmt_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        v = float(value)
        if v.is_integer() and abs(v) < 1e12:
            return f"{int(v)}"
        return f"{v:.3f}".rstrip("0").rstrip(".")
    text = str(value)
    if len(text) >= 19 and text[4] == "-" and text[10] == "T":
        try:
            return fmt_time(text, "UTC")
        except ValueError:
            return text
    return text


def fmt_time(value: str | datetime | None, timezone: str) -> str:
    if value is None:
        return ""
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        zone = ZoneInfo(timezone)
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")
    local = moment.astimezone(zone)
    suffix = "" if timezone in ("UTC", "Etc/UTC") else f" ({local.tzname()})"
    return local.strftime("%-d %b %Y, %H:%M") + suffix


def span(start: Any, end: Any, timezone: str) -> str:
    """A period as words: "1 May 2025, 00:00 to 29 Aug 2025, 00:00"."""
    return f"{fmt_time(start, timezone)} to {fmt_time(end, timezone)}"


def settings_rows(inp: ReportInput, labels: dict[str, str]) -> list[tuple[str, str]]:
    """What the run was asked, as the interface's settings block lists it."""
    p = inp.parameters
    rows: list[tuple[str, str]] = []

    def names(key: str) -> str | None:
        ids = p.get(key)
        if not isinstance(ids, list):
            return None
        return ", ".join(labels.get(str(i), str(i)) for i in ids)

    if subjects := names("entity_ids"):
        rows.append(("Subjects", subjects))
    if devices := names("device_ids"):
        rows.append(("Devices", devices))
    if herd_b := names("herd_b_entity_ids"):
        rows.append(("Second herd", herd_b))
    if areas := names("feature_ids"):
        rows.append(("Areas", areas))
    rows.append(("Period", span(p.get("time_from"), p.get("time_to"), inp.timezone)))
    comparison = p.get("comparison")
    if isinstance(comparison, dict):
        rows.append(
            (
                "Compared with",
                span(comparison.get("time_from"), comparison.get("time_to"), inp.timezone),
            )
        )
    if p.get("event_at"):
        rows.append(("Event", fmt_time(p["event_at"], inp.timezone)))
    if p.get("seasons") is True:
        rows.append(("Seasons", "rows per season"))
    for key, label in OPTION_LABELS:
        if key in UNUSED_OPTIONS.get(inp.module, ()):
            continue
        value = p.get(key)
        if value is None or value == "" or value == []:
            continue
        rows.append((label, ", ".join(map(str, value)) if isinstance(value, list) else str(value)))
    return rows


def fmt_indicator(value: Any, key: str) -> str:
    """A device performance figure as words: shares as percentages, long seconds as minutes,
    the rest rounded by size; the frontend's `showFigure`."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if not isinstance(value, int | float):
        return str(value)
    if key.endswith("_share") or key == "fix_success":
        return f"{round(value * 100)}%"
    if key.endswith("_s") and abs(value) >= 120:
        return f"{round(value / 60)} min"
    if float(value).is_integer():
        return str(int(value))
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}" if abs(value) >= 10 else f"{value:.2f}"


def device_order(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The device subjects worst first: by headline level, then by the weight of their
    critical and warn indicators, then by name (the frontend's `orderedSubjects`)."""
    summary = document.get("summary", {})
    main = summary.get("main") or {}
    levels = summary.get("levels") or {}

    def key(subject: dict[str, Any]) -> tuple[int, int, str]:
        sid = str(subject["id"])
        headline = (main.get(sid) or {}).get("level")
        weight = sum(
            10 if level == "critical" else 1 if level == "warn" else 0
            for level in (levels.get(sid) or {}).values()
        )
        return (LEVEL_ORDER.get(headline, 3), -weight, str(subject.get("name", "")))

    return sorted(document.get("subjects", []), key=key)


#: What an empty slope or days figure says, by the trend the fit found (decision D232).
TREND_WORDS = {"steady": "steady", "rising": "rising", "falling": "over a year"}


def trend_word(figures: dict[str, Any], key: str) -> str | None:
    """The word in place of an empty battery slope or days-to-critical figure: "steady" when
    the fit proved nothing, "rising" when the battery charges, "over a year" when a proven
    fall reaches the critical voltage later than a year."""
    if key not in ("battery_slope_mv_day", "days_to_critical") or figures.get(key) is not None:
        return None
    trend = figures.get("battery_trend")
    if key == "battery_slope_mv_day" and trend == "falling":
        return None
    return TREND_WORDS.get(str(trend)) if trend else None


def _with_before(value: Any, before: dict[str, Any] | None, key: str, has_comparison: bool) -> str:
    """A figure, with the comparison period's in brackets when the run has one and the figure
    exists there."""
    text = fmt_indicator(value, key)
    if has_comparison and isinstance(before, dict) and before.get(key) is not None:
        text += f" ({fmt_indicator(before.get(key), key)})"
    return text


def _device_figures(inp: ReportInput, labels: dict[str, str]) -> dict[str, Any]:
    """The fleet table as the key figures: a row per device, worst first, a level dot beside
    every headline figure, the comparison in brackets. Up to `FLEET_TRANSPOSE_MAX` devices the
    table also comes on its side (`transposed`), a row per indicator, which the template
    prefers: fourteen columns do not fit A4 portrait."""
    document = inp.document
    summary = document.get("summary", {})
    has_comparison = any(p.get("key") == "comparison" for p in document.get("periods", []))
    main = summary.get("main") or {}
    before = summary.get("comparison") or {}
    levels = summary.get("levels") or {}
    rows = []
    for subject in device_order(document):
        sid = str(subject["id"])
        figures = main.get(sid) or {}
        cells = [
            {
                "text": trend_word(figures, key)
                or _with_before(figures.get(key), before.get(sid), key, has_comparison),
                "level": (levels.get(sid) or {}).get(key),
            }
            for key in DEVICE_KEY_FIGURES
        ]
        rows.append(
            {
                "name": subject["name"],
                "note": subject.get("tracked") or subject.get("type") or "",
                "level": figures.get("level"),
                "cells": cells,
            }
        )
    transposed = None
    if 0 < len(rows) <= FLEET_TRANSPOSE_MAX:
        transposed = {
            "columns": [row["name"] for row in rows],
            "levels": [row["level"] for row in rows],
            "rows": [
                {"label": labels.get(key, key), "cells": [row["cells"][i] for row in rows]}
                for i, key in enumerate(DEVICE_KEY_FIGURES)
            ],
        }
    return {
        "first": "Device",
        "columns": [DEVICE_SHORT_LABELS.get(k, labels.get(k, k)) for k in DEVICE_KEY_FIGURES],
        "rows": rows,
        "transposed": transposed,
        "note": ("The figure in brackets is the period before. " if has_comparison else "")
        + "A dot marks the level: green ok, amber warn, red critical.",
        "herd": None,
    }


def device_sections(
    inp: ReportInput, labels: dict[str, str], colors: dict[str, str]
) -> list[dict[str, Any]]:
    """One section per device: the four area cards with the figures and their levels, and
    the device's own charts."""
    document = inp.document
    summary = document.get("summary", {})
    has_comparison = any(p.get("key") == "comparison" for p in document.get("periods", []))
    main = summary.get("main") or {}
    before = summary.get("comparison") or {}
    levels = summary.get("levels") or {}
    sections = []
    for subject in device_order(document):
        sid = str(subject["id"])
        figures = main.get(sid) or {}
        cards = []
        for area, keys in DEVICE_AREA_CARDS:
            rows = []
            for key in keys:
                value = figures.get(key)
                word = trend_word(figures, key)
                if word is None and (value is None or value == []):
                    continue
                rows.append(
                    {
                        "label": labels.get(key, key),
                        "text": word or _with_before(value, before.get(sid), key, has_comparison),
                        "level": (levels.get(sid) or {}).get(key),
                    }
                )
            if rows:
                cards.append({"title": labels.get(area, area), "rows": rows})
        charts = []
        for chart in document.get("charts", []):
            series = [s for s in chart.get("series", []) if s.get("subject") == sid]
            if not series:
                continue
            own = {**chart, "series": series}
            charts.append(
                {
                    "title": labels.get(chart["key"], chart["key"]),
                    "svg": _data_uri(
                        chart_svg(
                            own, labels, colors, width_in=CHART_WIDTH_IN, height_in=CHART_HEIGHT_IN
                        ),
                        "image/svg+xml",
                    ),
                }
            )
        sections.append(
            {
                "name": subject["name"],
                "color": colors.get(sid, PALETTE[0]),
                "type": subject.get("type") or "",
                "tracked": subject.get("tracked") or "",
                "level": figures.get("level"),
                "cards": cards,
                "charts": charts,
            }
        )
    return sections


def key_figures(inp: ReportInput, labels: dict[str, str]) -> dict[str, Any]:
    """The cards as one table: a row per subject (movement) or per area (grazing), a column
    per figure, the comparison in brackets when the run has one; for device performance the
    fleet table with its level dots."""
    document = inp.document
    summary = document.get("summary", {})
    has_comparison = any(p.get("key") == "comparison" for p in document.get("periods", []))
    main = summary.get("main") or {}
    before = summary.get("comparison") or {}
    if inp.module == "device_performance":
        return _device_figures(inp, labels)
    if inp.module == "cardiac":
        return _cardiac_figures(inp, labels)
    if inp.module == "grazing":
        metrics = GRAZING_KEY_FIGURES
        rows_source = [
            (str(a["id"]), a["name"], f"{float(a.get('hectares', 0)):.1f} ha")
            for a in summary.get("areas") or []
        ]
        first = "Area"
    else:
        metrics = MOVEMENT_KEY_FIGURES
        rows_source = [
            (str(s["id"]), s["name"], s.get("type") or "") for s in document.get("subjects", [])
        ]
        first = "Subject"
    rows = []
    for key, name, note in rows_source:
        figures = main.get(key) if isinstance(main, dict) else None
        cells = []
        for metric, unit in metrics:
            if not isinstance(figures, dict):
                cells.append("no fixes")
                continue
            text = fmt_figure(figures.get(metric), unit)
            if has_comparison and isinstance(before.get(key), dict):
                text += f" ({fmt_figure(before[key].get(metric), unit)})"
            cells.append(text)
        rows.append({"name": name, "note": note, "cells": cells})
    herd = (summary.get("herd") or {}).get("main") if inp.module == "grazing" else None
    return {
        "first": first,
        "columns": [labels.get(m, m) for m, _ in metrics],
        "rows": rows,
        "note": "The figure in brackets is the period before." if has_comparison else "",
        "herd": herd,
    }


def _cardiac_figure(figures: dict[str, Any], key: str) -> Any:
    """One key figure of a subject: a median where the figure is a spread."""
    if key == "resting_heart_rate":
        return figures.get(key)
    if key == "restless":
        return (figures.get("restless") or {}).get("median_minutes")
    spread = figures.get("tag_temperature" if key == "temperature" else key)
    return spread.get("median") if isinstance(spread, dict) else None


def _cardiac_figures(inp: ReportInput, labels: dict[str, str]) -> dict[str, Any]:
    """The cardiac cards as one table: a row per subject, the median of each metric, the
    comparison period's in brackets."""
    summary = inp.document.get("summary", {})
    main = summary.get("subjects") or {}
    before = summary.get("comparison") or {}
    rows = []
    for subject in inp.document.get("subjects", []):
        key = str(subject["id"])
        figures = main.get(key)
        cells = []
        for metric, unit in CARDIAC_KEY_FIGURES:
            if not isinstance(figures, dict):
                cells.append("nothing heard")
                continue
            text = fmt_figure(_cardiac_figure(figures, metric), unit)
            if isinstance(before.get(key), dict):
                text += f" ({fmt_figure(_cardiac_figure(before[key], metric), unit)})"
            cells.append(text)
        rows.append({"name": subject["name"], "note": subject.get("type") or "", "cells": cells})
    return {
        "first": "Subject",
        "columns": [labels.get(m, m) for m, _ in CARDIAC_KEY_FIGURES],
        "rows": rows,
        "note": "The figure in brackets is the period before." if before else "",
        "herd": None,
    }


#: A table wider than this is turned on its side when it has few rows: a column per row.
WIDE_COLUMNS = 8
TRANSPOSE_MAX_ROWS = 6


def table_block(table: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    """A document table for the page: its cells as words, and a wide table with a handful of
    rows (the summary per subject and period) turned on its side so it fits A4 portrait."""
    columns = [labels.get(str(c), str(c)) for c in table.get("columns", [])]
    rows = [
        [labels.get(str(v), fmt_cell(v)) if isinstance(v, str) else fmt_cell(v) for v in r]
        for r in table.get("rows", [])
    ]
    title = labels.get(table["key"], table["key"])
    if len(columns) > WIDE_COLUMNS and 0 < len(rows) <= TRANSPOSE_MAX_ROWS:
        # the first cell names the row, and the second too when it is words (subject and
        # period, area and period); a figure in the second column stays a figure
        raw = table.get("rows", [])
        named = 2 if all(len(r) > 1 and isinstance(r[1], str) for r in raw) else 1
        heads = [" · ".join(c for c in r[:named] if c) for r in rows]
        body = [
            [columns[i], *[r[i] if i < len(r) else "" for r in rows]]
            for i in range(named, len(columns))
        ]
        return {"title": title, "columns": ["", *heads], "rows": body, "wide": True}
    return {"title": title, "columns": columns, "rows": rows, "wide": len(columns) > WIDE_COLUMNS}


#: What each kind of shape on the map means, for the legend under the picture.
KIND_LEGEND: dict[str, str] = {
    "area": "Areas by relative grazing pressure, from little use to heavy use",
    "mcp": "MCP 95% home range: the outline around 95% of the fixes, a faint fill",
    "kde": "KDE isopleths: the 50% core darker inside the 95% range",
    "akde": "KDE corrected for autocorrelation: the same two isopleths, wider where the fixes "
    "are few independent looks at the range",
    "hotspot": "Hotspots: the cells that hold most of the time",
    "cluster": "Clusters of fixes",
    "coverage": "Coverage of the fixes: the hull around a device's valid fixes, in its colour",
    "gateway": "Gateways heard: a marker per gateway, larger for a bigger share of the uplinks",
}
#: Above this many subjects the legend names the colours in the sections instead.
LEGEND_MAX_SUBJECTS = 12


def map_legend(document: dict[str, Any], colors: dict[str, str]) -> list[dict[str, Any]]:
    """The legend under the map: the subjects in their colours and one line per kind of shape
    the run drew (`document["geometries"]` counts them); the pressure ramp for the areas."""
    entries: list[dict[str, Any]] = []
    subjects = document.get("subjects", [])
    kinds = [k for k, n in (document.get("geometries") or {}).items() if n]
    coloured = {"mcp", "kde", "akde", "hotspot", "cluster", "coverage", "gateway"}
    if any(k in coloured for k in kinds):
        if len(subjects) <= LEGEND_MAX_SUBJECTS:
            entries.extend(
                {"kind": "swatch", "color": colors.get(str(s["id"]), PALETTE[0]), "text": s["name"]}
                for s in subjects
            )
        else:
            entries.append(
                {
                    "kind": "text",
                    "text": f"One colour per subject ({len(subjects)}); the sections name them.",
                }
            )
    for kind in kinds:
        if kind not in KIND_LEGEND:
            continue
        if kind == "area":
            entries.append(
                {"kind": "ramp", "colors": list(PRESSURE_RAMP), "text": KIND_LEGEND[kind]}
            )
        elif kind == "gateway":
            entries.append({"kind": "marker", "text": KIND_LEGEND[kind]})
        else:
            entries.append({"kind": "outline", "text": KIND_LEGEND[kind]})
    return entries


def render_html(inp: ReportInput) -> str:
    document = inp.document
    labels = labels_for(inp.module, document)
    colors = subject_colors(document)
    devices = inp.module == "device_performance"
    # the device report folds the charts into the device sections
    charts = (
        []
        if devices
        else [
            {
                "title": labels.get(c["key"], c["key"]),
                "svg": _data_uri(
                    chart_svg(
                        c, labels, colors, width_in=CHART_WIDTH_IN, height_in=CHART_HEIGHT_IN
                    ),
                    "image/svg+xml",
                ),
            }
            for c in document.get("charts", [])
        ]
    )
    # a device run prints the fleet table as its key figures and the area cards per device,
    # so of its tables only the details, the error flags and the reboots go on paper (D234)
    tables = [
        table_block(t, labels)
        for t in document.get("tables", [])
        if t.get("rows") and not (devices and t.get("key") in DEVICE_TABLES_IN_CARDS)
    ]
    defaults = document.get("summary", {}).get("defaults") if devices else None
    main = next((p for p in document.get("periods", []) if p.get("key") == "main"), None)
    module_label = MODULE_LABELS.get(inp.module, inp.module.title())
    logo = ASSETS / "logo-landscape.webp"
    environment = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
    )
    return environment.get_template("report.html").render(
        title=inp.run_name or f"{module_label} analysis",
        module_label=module_label,
        project_name=inp.project_name,
        period=span(main["time_from"], main["time_to"], inp.timezone) if main else "",
        subjects=[
            {"name": s["name"], "type": s.get("type") or "", "color": colors[str(s["id"])]}
            for s in document.get("subjects", [])
        ],
        created_by=inp.created_by,
        created_at=fmt_time(inp.created_at, inp.timezone),
        computed_at=fmt_time(inp.computed_at, inp.timezone) if inp.computed_at else "",
        method_version=document.get("method_version", ""),
        settings=settings_rows(inp, labels),
        warnings=[
            {
                "level": w.get("level", "warning"),
                "text": (
                    f"{labels.get(str(w.get('subject_id')), '')}: " if w.get("subject_id") else ""
                )
                + str(w.get("text", "")),
            }
            for w in document.get("warnings", [])
        ],
        figures=key_figures(inp, labels),
        map=(
            {
                "png": _data_uri(inp.map.png, "image/png"),
                "note": inp.map.note,
                "legend": map_legend(document, colors),
            }
            if inp.map
            else None
        ),
        charts=charts,
        sections=device_sections(inp, labels, colors) if devices else [],
        defaults=(
            [(labels.get(k, k), text) for k, text in defaults.items()]
            if isinstance(defaults, dict)
            else []
        ),
        tables=tables,
        limitations=(
            DEVICE_PERFORMANCE_LIMITATIONS
            if devices
            else GRAZING_LIMITATIONS
            if inp.module == "grazing"
            else CARDIAC_LIMITATIONS
            if inp.module == "cardiac"
            else MOVEMENT_LIMITATIONS
        ),
        version=inp.version,
        generated_at=fmt_time(inp.generated_at, inp.timezone),
        timezone=inp.timezone,
        logo=_data_uri(logo.read_bytes(), "image/webp") if logo.exists() else None,
    )


def render_document(inp: ReportInput) -> Any:
    """The laid-out document (WeasyPrint's, with its pages), before it is written as a PDF."""
    stylesheet = CSS(filename=str(TEMPLATES / "report.css"))
    return HTML(string=render_html(inp), base_url=str(TEMPLATES)).render(stylesheets=[stylesheet])


def render_pdf(inp: ReportInput) -> bytes:
    return bytes(render_document(inp).write_pdf())


def _data_uri(payload: bytes | str, media_type: str) -> str:
    raw = payload.encode() if isinstance(payload, str) else payload
    return f"data:{media_type};base64,{base64.b64encode(raw).decode()}"
