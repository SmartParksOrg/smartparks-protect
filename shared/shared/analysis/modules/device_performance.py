"""Device performance (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, decisions D213 to D220): how
the chosen devices perform as a fleet and one by one. Four areas, each a fixed catalogue of
indicators computed when the device reports the data and left out when it does not: the
device's own health, how regularly it reports against its settings, its GNSS fixes, and the
networks that carry it, per data source. Every indicator carries a level from the driver's
thresholds or the catalogue's defaults, and a rank inside the fleet."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from shapely.geometry import MultiPoint, mapping
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis.base import (
    AnalysisTooLarge,
    Chart,
    Geometry,
    Period,
    Provenance,
    ResultDocument,
    RunContext,
    RunResult,
    Subject,
    Table,
    Warning,
)
from shared.analysis.limits import MAX_FIXES_PER_SUBJECT, MAX_ROWS_PER_DEVICE
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.health import (
    DAY_S,
    FlagShares,
    Reboots,
    bucketed,
    days_to,
    flag_shares,
    is_status,
    percentile,
    reboots_from,
    share,
    slope_per_day,
    versions_seen,
)
from shared.analysis.primitives.intervals import (
    Expected,
    IntervalReport,
    interval_report,
    resolve_expected,
)
from shared.analysis.primitives.levels import (
    CRITICAL_FLAGS,
    DEFAULTS,
    Level,
    Threshold,
    ranks,
    thresholds_for,
    worst,
)
from shared.analysis.primitives.network import Receptions, fold_receptions, lost_share
from shared.analysis.primitives.trajectory import Trajectory, exclude_impossible, load_trajectory
from shared.connectivity.satellite import DELIVERED_STATUSES, SatelliteSession
from shared.curation.effective import effective_number, effective_time, in_window, visible
from shared.device_drivers.registry import DRIVERS
from shared.domain.reporting import Declared, declared_intervals
from shared.enums import AcquisitionChannel
from shared.models import (
    DataSource,
    Device,
    DeviceEntityAssignment,
    DeviceStateHistory,
    DeviceType,
    Entity,
    Event,
    Gateway,
    GatewayReception,
    Measurement,
    Position,
    SourceEvent,
)

METHOD_VERSION = "device_performance/1"
#: Daily figures up to this many days, weekly beyond (decision D218).
WEEKLY_ABOVE_DAYS = 120
METRIC_KEYS = (
    "battery_voltage",
    "charging_voltage",
    "device_temperature",
    "uptime",
    "activity",
    "gnss_fix",
    "gnss_time_to_fix",
    "gnss_satellites",
    "gnss_accuracy",
    "gnss_pdop",
    "flash_used_percent",
)
YIELD_PER = 5_000
MAX_REBOOT_ROWS = 200
FEW_SATELLITES = 4
TTF_EDGES = [0, 15, 30, 60, 120, 300, np.inf]
TTF_LABELS = ["<15 s", "15 s", "30 s", "60 s", "120 s", ">300 s"]
ACCURACY_EDGES = [0, 5, 10, 30, 100, np.inf]
ACCURACY_LABELS = ["<5 m", "5 m", "10 m", "30 m", ">100 m"]
SATELLITE_EDGES = [0, 4, 6, 8, 10, 13, np.inf]
SATELLITE_LABELS = ["<4", "4", "6", "8", "10", ">12"]
#: The headline columns of the fleet table, in order (plan, section 6).
FLEET_COLUMNS = [
    "battery_v",
    "battery_slope_mv_day",
    "days_to_critical",
    "temperature_max_c",
    "reboots",
    "error_share",
    "missed_fix_share",
    "longest_silence_h",
    "fix_success",
    "ttf_p90_s",
    "accuracy_median_m",
    "lost_uplinks_share",
    "rssi_p10_dbm",
    "missed_sessions_share",
]
HEALTH_COLUMNS = [
    "statuses",
    "battery_v",
    "battery_min_v",
    "battery_slope_mv_day",
    "days_to_critical",
    "charging_days",
    "temperature_min_c",
    "temperature_median_c",
    "temperature_max_c",
    "hot_hours",
    "reboots",
    "reboots_per_week",
    "uptime_max_d",
    "error_share",
    "flash_used_percent",
    "moving_share",
    "firmware",
]
REPORTING_COLUMNS = [
    "expected_fix_s",
    "expected_fix_source",
    "fix_regular_share",
    "declared_fix_s",
    "expected_status_s",
    "expected_status_source",
    "fixes",
    "observed_fix_median_s",
    "observed_fix_p90_s",
    "missed_fix_share",
    "observed_status_median_s",
    "missed_status_share",
    "silences",
    "longest_silence_h",
    "messages",
    "invalid_records",
    "invalid_share",
]
GNSS_COLUMNS = [
    "attempts",
    "fixes",
    "fix_success",
    "ttf_median_s",
    "ttf_p90_s",
    "satellites_median",
    "few_satellites_share",
    "accuracy_median_m",
    "accuracy_p90_m",
    "poor_accuracy_share",
    "pdop_median",
    "rejected_fixes",
    "rejected_share",
    "fixes_per_day",
]
NETWORK_COLUMNS = [
    "messages",
    "per_day",
    "lost_uplinks_share",
    "gateways",
    "best_gateway",
    "best_gateway_share",
    "rssi_median_dbm",
    "rssi_p10_dbm",
    "snr_median_db",
    "snr_p10_db",
    "joins",
    "sessions",
    "missed_sessions_share",
    "failed_sessions_share",
    "redeliveries",
    "bytes",
]


class DevicePerformanceParameters(CommonParameters):
    """The common parameters with device subjects; one option of its own: the speed above
    which a fix is impossible and counts as rejected."""

    max_speed_mps: float = Field(default=15, gt=0, le=100)


@dataclass(slots=True)
class DeviceInfo:
    id: uuid.UUID
    name: str
    type_label: str
    driver_key: str
    default_settings: dict[str, Any]
    attributes: dict[str, Any]
    tracked: str | None
    device: Device
    device_type: DeviceType


@dataclass(slots=True)
class SourceInfo:
    id: uuid.UUID
    name: str
    channel: str
    messages: int


@dataclass(slots=True)
class DeviceFigures:
    """One device in one period: the flat figures, the levels, the chart series, the table
    rows of the sub-tables, the warnings and the geometries."""

    summary: dict[str, Any] = field(default_factory=dict)
    levels: dict[str, Level] = field(default_factory=dict)
    charts: dict[str, list[list[Any]]] = field(default_factory=dict)
    source_charts: dict[str, dict[str, list[list[Any]]]] = field(default_factory=dict)
    network_rows: list[list[Any]] = field(default_factory=list)
    error_rows: list[list[Any]] = field(default_factory=list)
    reboot_rows: list[list[Any]] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    geometries: list[Geometry] = field(default_factory=list)


def _ms(seconds: float) -> float:
    return float(seconds) * 1000


def _minutes(seconds: float) -> str:
    """An interval as words: "5 min", "1.5 h", "2 d"."""
    if seconds >= 2 * DAY_S:
        return f"{seconds / DAY_S:.0f} d"
    if seconds >= 3600:
        return f"{seconds / 3600:g} h"
    return f"{seconds / 60:.0f} min"


def _level(thresholds: dict[str, Threshold], key: str, value: float | None) -> Level | None:
    threshold = thresholds.get(key)
    return threshold.level(value) if threshold else None


async def load_devices(
    session: AsyncSession, device_ids: list[uuid.UUID], period: Period
) -> list[DeviceInfo]:
    """The devices with their type and driver, and the entity each tracked in the period (the
    first and, when it changed, the last)."""
    rows = (
        await session.execute(
            select(Device, DeviceType)
            .join(DeviceType, DeviceType.id == Device.device_type_id)
            .where(Device.id.in_(device_ids))
            .order_by(Device.name)
        )
    ).all()
    window = func.tstzrange(period.time_from, period.time_to, "[)")
    assignments = (
        await session.execute(
            select(DeviceEntityAssignment.device_id, Entity.name)
            .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
            .where(
                DeviceEntityAssignment.device_id.in_(device_ids),
                DeviceEntityAssignment.validity.op("&&")(window),
            )
            .order_by(DeviceEntityAssignment.device_id, func.lower(DeviceEntityAssignment.validity))
        )
    ).all()
    tracked: dict[uuid.UUID, list[str]] = defaultdict(list)
    for device_id, name in assignments:
        if name not in tracked[device_id]:
            tracked[device_id].append(name)
    out = []
    for device, device_type in rows:
        type_label, driver_key, defaults = (
            device_type.label,
            device_type.driver_key,
            device_type.default_settings,
        )
        names = tracked.get(device.id, [])
        text = None
        if len(names) == 1:
            text = names[0]
        elif names:
            text = f"{names[0]}, then {names[-1]}"
        out.append(
            DeviceInfo(
                id=device.id,
                name=device.name,
                type_label=type_label,
                driver_key=driver_key,
                default_settings=dict(defaults or {}),
                attributes=dict(device.attributes or {}),
                tracked=text,
                device=device,
                device_type=device_type,
            )
        )
    return out


async def _metrics(
    session: AsyncSession, device_id: uuid.UUID, period: Period
) -> dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]]:
    """Every metric of the catalogue in one streamed read: `{key: (seconds, values)}`."""
    statement = (
        select(Measurement.metric_key, effective_time(Measurement).label("at"), effective_number())
        .where(
            Measurement.device_id == device_id,
            Measurement.metric_key.in_(METRIC_KEYS),
            in_window(Measurement, period.time_from, period.time_to),
            visible(Measurement),
        )
        .order_by(effective_time(Measurement))
        .execution_options(yield_per=YIELD_PER)
    )
    times: dict[str, list[float]] = defaultdict(list)
    values: dict[str, list[float]] = defaultdict(list)
    count = 0
    async for key, at, value in await session.stream(statement):
        count += 1
        if count > MAX_ROWS_PER_DEVICE:
            raise AnalysisTooLarge(
                f"more than {MAX_ROWS_PER_DEVICE} measurements for one device; "
                "choose a shorter period"
            )
        times[key].append(at.timestamp())
        values[key].append(float(value) if value is not None else np.nan)
    return {
        key: (np.asarray(times[key], dtype=np.float64), np.asarray(values[key], dtype=np.float64))
        for key in times
    }


async def _invalid_counts(
    session: AsyncSession, device_id: uuid.UUID, period: Period
) -> tuple[int, int]:
    """Records the pipeline or a curation holds invalid in the window (the clock-ahead rule
    D119 among them), and the valid ones, over positions and measurements."""
    invalid = valid = 0
    for model in (Position, Measurement):
        rows = (
            await session.execute(
                select(model.valid, func.count())
                .where(
                    model.device_id == device_id, in_window(model, period.time_from, period.time_to)
                )
                .group_by(model.valid)
            )
        ).all()
        for flag, count in rows:
            if flag:
                valid += int(count)
            else:
                invalid += int(count)
    return invalid, valid


async def _states(
    session: AsyncSession, device_id: uuid.UUID, period: Period
) -> list[tuple[float, dict[str, Any]]]:
    statement = (
        select(DeviceStateHistory.time, DeviceStateHistory.state)
        .where(
            DeviceStateHistory.device_id == device_id,
            DeviceStateHistory.time >= period.time_from,
            DeviceStateHistory.time < period.time_to,
        )
        .order_by(DeviceStateHistory.time)
        .execution_options(yield_per=YIELD_PER)
    )
    out: list[tuple[float, dict[str, Any]]] = []
    async for when, state in await session.stream(statement):
        out.append((when.timestamp(), dict(state or {})))
        if len(out) > MAX_ROWS_PER_DEVICE:
            raise AnalysisTooLarge(f"more than {MAX_ROWS_PER_DEVICE} states for one device")
    return out


async def _reboots(session: AsyncSession, device_id: uuid.UUID, period: Period) -> Reboots:
    rows = (
        await session.execute(
            select(Event.time, Event.context)
            .where(
                Event.device_id == device_id,
                Event.event_type == "device_reset",
                Event.time >= period.time_from,
                Event.time < period.time_to,
            )
            .order_by(Event.time)
        )
    ).all()
    return reboots_from([(when, context) for when, context in rows])


async def _sources(session: AsyncSession, device_id: uuid.UUID, period: Period) -> list[SourceInfo]:
    """The data sources that carried the device's messages in the period, with their channel."""
    rows = (
        await session.execute(
            select(SourceEvent.data_source_id, SourceEvent.acquisition_channel, func.count())
            .where(
                SourceEvent.device_id == device_id,
                SourceEvent.ingested_at >= period.time_from,
                SourceEvent.ingested_at < period.time_to,
            )
            .group_by(SourceEvent.data_source_id, SourceEvent.acquisition_channel)
        )
    ).all()
    if not rows:
        return []
    names = {
        s.id: s.name
        for s in await session.scalars(
            select(DataSource).where(DataSource.id.in_({r[0] for r in rows}))
        )
    }
    by_source: dict[tuple[uuid.UUID, str], int] = Counter()
    for source_id, channel, count in rows:
        by_source[(source_id, str(getattr(channel, "value", channel) or "api"))] += int(count)
    out = [
        SourceInfo(
            id=source_id, name=names.get(source_id, str(source_id)[:8]), channel=channel, messages=n
        )
        for (source_id, channel), n in by_source.items()
    ]
    out.sort(key=lambda s: s.name)
    return out


async def _receptions(
    session: AsyncSession, device_id: uuid.UUID, source_id: uuid.UUID, period: Period
) -> Receptions:
    statement = (
        select(
            GatewayReception.gateway_id,
            GatewayReception.source_event_id,
            GatewayReception.rssi,
            GatewayReception.snr,
            GatewayReception.time,
        )
        .where(
            GatewayReception.device_id == device_id,
            GatewayReception.data_source_id == source_id,
            GatewayReception.time >= period.time_from,
            GatewayReception.time < period.time_to,
        )
        .execution_options(yield_per=YIELD_PER)
    )
    rows: list[tuple[str, int, float | None, float | None, float]] = []
    async for gateway_id, event_id, rssi, snr, when in await session.stream(statement):
        rows.append((str(gateway_id), int(event_id), rssi, snr, when.timestamp()))
        if len(rows) > MAX_ROWS_PER_DEVICE:
            raise AnalysisTooLarge(f"more than {MAX_ROWS_PER_DEVICE} receptions for one device")
    return fold_receptions(rows)


async def _frame_counters(
    session: AsyncSession, device_id: uuid.UUID, source_id: uuid.UUID, period: Period
) -> list[int]:
    counter = SourceEvent.provider_metadata["f_cnt"].as_integer()
    rows = (
        await session.execute(
            select(counter)
            .where(
                SourceEvent.device_id == device_id,
                SourceEvent.data_source_id == source_id,
                SourceEvent.event_type == "uplink",
                SourceEvent.ingested_at >= period.time_from,
                SourceEvent.ingested_at < period.time_to,
                counter.is_not(None),
            )
            .order_by(SourceEvent.ingested_at)
            .limit(MAX_ROWS_PER_DEVICE)
        )
    ).all()
    return [int(c) for (c,) in rows]


async def _uplink_days(
    session: AsyncSession,
    device_id: uuid.UUID,
    source_id: uuid.UUID,
    period: Period,
    bucket_s: float,
) -> tuple[list[list[Any]], int]:
    """Messages per bucket for one source, and the joins in the period."""
    bucket = func.floor(func.extract("epoch", SourceEvent.ingested_at) / bucket_s) * bucket_s
    rows = (
        await session.execute(
            select(bucket.label("bucket"), func.count())
            .where(
                SourceEvent.device_id == device_id,
                SourceEvent.data_source_id == source_id,
                SourceEvent.ingested_at >= period.time_from,
                SourceEvent.ingested_at < period.time_to,
            )
            .group_by("bucket")
            .order_by("bucket")
        )
    ).all()
    joins = await session.scalar(
        select(func.count()).where(
            SourceEvent.device_id == device_id,
            SourceEvent.data_source_id == source_id,
            SourceEvent.event_type == "join",
            SourceEvent.ingested_at >= period.time_from,
            SourceEvent.ingested_at < period.time_to,
        )
    )
    return [[_ms(float(b)), int(n)] for b, n in rows], int(joins or 0)


async def _satellite_sessions(
    session: AsyncSession, device_id: uuid.UUID, source_id: uuid.UUID, period: Period
) -> list[tuple[float, dict[str, Any]]]:
    info = SourceEvent.provider_metadata["satellite_session"]
    rows = (
        await session.execute(
            select(SourceEvent.ingested_at, info)
            .where(
                SourceEvent.device_id == device_id,
                SourceEvent.data_source_id == source_id,
                SourceEvent.acquisition_channel == AcquisitionChannel.IRIDIUM,
                SourceEvent.ingested_at >= period.time_from,
                SourceEvent.ingested_at < period.time_to,
                info.is_not(None),
            )
            .order_by(SourceEvent.ingested_at)
            .limit(MAX_ROWS_PER_DEVICE)
        )
    ).all()
    return [(when.timestamp(), data) for when, data in rows if isinstance(data, dict)]


async def _gateway_points(
    session: AsyncSession, source_id: uuid.UUID, external_ids: list[str]
) -> dict[str, tuple[str, float, float]]:
    """The gateways of a source by external id: their name and location, when known."""
    if not external_ids:
        return {}
    rows = (
        await session.execute(
            select(
                Gateway.external_id,
                Gateway.name_override,
                Gateway.name,
                func.ST_X(Gateway.geom),
                func.ST_Y(Gateway.geom),
            ).where(Gateway.data_source_id == source_id, Gateway.external_id.in_(external_ids))
        )
    ).all()
    out: dict[str, tuple[str, float, float]] = {}
    for external_id, override, name, lon, lat in rows:
        if lon is None or lat is None:
            continue
        out[str(external_id)] = (str(override or name or external_id), float(lon), float(lat))
    return out


def _histogram(
    values: NDArray[np.float64], edges: list[float], labels: list[str]
) -> list[list[Any]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    hist, _ = np.histogram(clean, bins=edges)
    return [[labels[i], int(hist[i])] for i in range(len(labels))]


def health_figures(
    metrics: dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]],
    states: list[tuple[float, dict[str, Any]]],
    reboots: Reboots,
    thresholds: dict[str, Threshold],
    period: Period,
    bucket_s: float,
    out: DeviceFigures,
) -> None:
    """Section 4.1: the battery, the temperature, the reboots, the errors, the flash, the
    movement and the firmware, into the figures, levels and charts of one device."""
    s = out.summary
    window_s = (period.time_to - period.time_from).total_seconds()
    status_states = [state for _, state in states if is_status(state)]
    s["statuses"] = len(status_states)
    if "battery_voltage" in metrics:
        times, values = metrics["battery_voltage"]
        clean = ~np.isnan(values)
        if clean.any():
            now_v = float(values[clean][-1])
            s["battery_v"] = round(now_v, 3)
            s["battery_min_v"] = round(float(values[clean].min()), 3)
            slope = slope_per_day(times[clean], values[clean])
            s["battery_slope_mv_day"] = round(slope * 1000, 2) if slope is not None else None
            floor = thresholds["battery_v"].critical_below
            s["days_to_critical"] = days_to(now_v, slope, floor) if floor is not None else None
            out.charts["battery"] = bucketed(times[clean], values[clean], bucket_s)
    if "charging_voltage" in metrics and "battery_voltage" in metrics:
        c_times, c_values = metrics["charging_voltage"]
        b_times, b_values = metrics["battery_voltage"]
        charging_days = 0
        for day, charge in bucketed(c_times, c_values, DAY_S, "max"):
            battery = [v for d, v in bucketed(b_times, b_values, DAY_S, "median") if d == day]
            if battery and charge > battery[0]:
                charging_days += 1
        s["charging_days"] = charging_days
    if "device_temperature" in metrics:
        times, values = metrics["device_temperature"]
        clean = ~np.isnan(values)
        if clean.any():
            s["temperature_min_c"] = round(float(values[clean].min()), 1)
            s["temperature_median_c"] = round(float(np.median(values[clean])), 1)
            s["temperature_max_c"] = round(float(values[clean].max()), 1)
            warn_at = thresholds["temperature_max_c"].warn_at
            if warn_at is not None and clean.sum() > 1:
                hot = values[clean] >= warn_at
                # each reading stands for the interval to the next one
                dt = np.diff(times[clean], append=times[clean][-1])
                s["hot_hours"] = round(float(dt[hot].sum()) / 3600, 1)
            out.charts["temperature"] = bucketed(times[clean], values[clean], bucket_s, "max")
    s["reboots"] = reboots.count
    s["reboots_per_week"] = reboots.per_week(window_s)
    if "uptime" in metrics:
        _, values = metrics["uptime"]
        clean = values[~np.isnan(values)]
        if clean.size:
            s["uptime_max_d"] = round(float(clean.max()) / DAY_S, 1)
    flags: FlagShares = flag_shares(status_states)
    if flags.statuses:
        s["error_share"] = flags.any_share
        for name, count in sorted(flags.counts.items()):
            if name == "__any__":
                continue
            flag_share = flags.share_of(name)
            level: Level | None = (
                "critical"
                if name in CRITICAL_FLAGS
                else thresholds["error_share"].level(flag_share)
            )
            out.error_rows.append([name, count, flag_share, level])
            if level == "critical":
                out.levels["error_share"] = "critical"
    if "flash_used_percent" in metrics:
        _, values = metrics["flash_used_percent"]
        clean = values[~np.isnan(values)]
        if clean.size:
            s["flash_used_percent"] = round(float(clean[-1]), 1)
    if "activity" in metrics:
        _, values = metrics["activity"]
        clean = values[~np.isnan(values)]
        if clean.size:
            s["moving_share"] = round(float((clean > 0).mean()), 3)
    firmware = versions_seen(status_states, "firmware_version")
    s["firmware"] = ", ".join(firmware) if firmware else None
    out.reboot_rows = [
        [when.isoformat(), reason] for when, reason in reboots.entries[:MAX_REBOOT_ROWS]
    ]
    for key in (
        "battery_v",
        "battery_slope_mv_day",
        "days_to_critical",
        "temperature_max_c",
        "reboots_per_week",
        "error_share",
        "flash_used_percent",
    ):
        level = _level(thresholds, key, s.get(key))
        if level is not None and out.levels.get(key) != "critical":
            out.levels[key] = level


def reporting_figures(
    fix_times: NDArray[np.float64],
    status_times: NDArray[np.float64],
    declared: Declared,
    invalid: int,
    valid: int,
    messages: int,
    thresholds: dict[str, Threshold],
    period: Period,
    out: DeviceFigures,
) -> tuple[Expected, Expected]:
    """Section 4.2: expected against observed intervals, missed reports, silences, messages
    and the records held invalid. The expected intervals come from the declared sources and
    the data together (decisions D225 to D227): a declared one holds unless the data plainly
    disagrees, a confident learned one serves when nothing is declared, and the source is
    named beside the figure."""
    s = out.summary
    fix_expected = resolve_expected(declared.fix, fix_times)
    status_expected = resolve_expected(declared.status, status_times)
    s["expected_fix_s"] = fix_expected.seconds
    s["expected_fix_source"] = fix_expected.source
    s["fix_regular_share"] = (
        fix_expected.learned.regular_share if fix_expected.learned is not None else None
    )
    s["declared_fix_s"] = fix_expected.declared_seconds
    s["expected_status_s"] = status_expected.seconds
    s["expected_status_source"] = status_expected.source
    expected = {"fix": fix_expected.seconds, "status": status_expected.seconds}
    from_s, to_s = period.time_from.timestamp(), period.time_to.timestamp()
    fixes: IntervalReport = interval_report(fix_times, from_s, to_s, expected["fix"])
    statuses: IntervalReport = interval_report(status_times, from_s, to_s, expected["status"])
    s["fixes"] = fixes.messages
    s["observed_fix_median_s"] = fixes.observed_median_s
    s["observed_fix_p90_s"] = fixes.observed_p90_s
    s["missed_fix_share"] = fixes.missed_share
    s["observed_status_median_s"] = statuses.observed_median_s
    s["missed_status_share"] = statuses.missed_share
    # the silence figures follow the message kind that should come most often
    lead = fixes if (expected["fix"] or fixes.messages >= statuses.messages) else statuses
    s["silences"] = lead.silences
    s["longest_silence_h"] = (
        round(lead.longest_silence_s / 3600, 1) if lead.longest_silence_s is not None else None
    )
    s["longest_silence_ended"] = (
        datetime.fromtimestamp(lead.longest_silence_end, tz=UTC).isoformat()
        if lead.longest_silence_end is not None
        else None
    )
    s["messages"] = messages
    s["invalid_records"] = invalid
    s["invalid_share"] = share(invalid, invalid + valid)
    for key in ("missed_fix_share", "missed_status_share", "longest_silence_h", "invalid_share"):
        level = _level(thresholds, key, s.get(key))
        if level is not None:
            out.levels[key] = level
    return fix_expected, status_expected


def gnss_figures(
    metrics: dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]],
    track: Trajectory,
    rejected: int,
    thresholds: dict[str, Threshold],
    period: Period,
    bucket_s: float,
    out: DeviceFigures,
) -> None:
    """Section 4.3: fix success, time to fix, satellites, accuracy, PDOP, the rejected fixes
    and the fixes per day against the expected count."""
    s = out.summary
    n = len(track)
    if "gnss_fix" in metrics:
        _, values = metrics["gnss_fix"]
        clean = values[~np.isnan(values)]
        if clean.size:
            s["attempts"] = int(clean.size)
            s["fix_success"] = round(float(clean.mean()), 4)
    if "gnss_time_to_fix" in metrics:
        _, values = metrics["gnss_time_to_fix"]
        s["ttf_median_s"] = percentile(values, 50)
        s["ttf_p90_s"] = percentile(values, 90)
        out.charts["time_to_fix"] = _histogram(values, TTF_EDGES, TTF_LABELS)
    sats = track.satellites if n else np.zeros(0)
    if "gnss_satellites" in metrics:
        sats = metrics["gnss_satellites"][1]
    clean_sats = sats[~np.isnan(sats)] if sats.size else sats
    if clean_sats.size:
        s["satellites_median"] = round(float(np.median(clean_sats)), 1)
        s["few_satellites_share"] = round(float((clean_sats < FEW_SATELLITES).mean()), 4)
        out.charts["satellites"] = _histogram(clean_sats, SATELLITE_EDGES, SATELLITE_LABELS)
    accuracy = track.accuracy_m if n else np.zeros(0)
    if "gnss_accuracy" in metrics:
        accuracy = metrics["gnss_accuracy"][1]
    clean_acc = accuracy[~np.isnan(accuracy)] if accuracy.size else accuracy
    if clean_acc.size:
        s["accuracy_median_m"] = round(float(np.median(clean_acc)), 1)
        s["accuracy_p90_m"] = round(float(np.percentile(clean_acc, 90)), 1)
        warn_at = thresholds["accuracy_median_m"].warn_at
        if warn_at is not None:
            s["poor_accuracy_share"] = round(float((clean_acc >= warn_at).mean()), 4)
        out.charts["accuracy"] = _histogram(clean_acc, ACCURACY_EDGES, ACCURACY_LABELS)
    if "gnss_pdop" in metrics:
        s["pdop_median"] = percentile(metrics["gnss_pdop"][1], 50)
    s["rejected_fixes"] = rejected
    s["rejected_share"] = share(rejected, rejected + n)
    days = max((period.time_to - period.time_from).total_seconds() / DAY_S, 1e-9)
    s["fixes_per_day"] = round(n / days, 2)
    if n:
        out.charts["fixes_per_day"] = bucketed(track.times, np.ones(n), bucket_s, "count")
    for key in (
        "fix_success",
        "ttf_p90_s",
        "few_satellites_share",
        "accuracy_median_m",
        "pdop_median",
        "rejected_share",
    ):
        level = _level(thresholds, key, s.get(key))
        if level is not None:
            out.levels[key] = level


def coverage_geometry(subject: Subject, period: Period, track: Trajectory) -> Geometry | None:
    """The convex hull of the valid fixes as the device's coverage (decision D220)."""
    if len(track) < 3:
        return None
    hull = MultiPoint(list(zip(track.lon.tolist(), track.lat.tolist(), strict=True))).convex_hull
    if hull.geom_type != "Polygon" or hull.is_empty:
        return None
    return Geometry(
        kind="coverage",
        subject_id=subject.id,
        label=f"{subject.name}: {len(track)} fixes",
        geojson=mapping(hull),
        properties={"period": period.key, "fixes": len(track)},
    )


async def network_figures(
    session: AsyncSession,
    subject: Subject,
    device_id: uuid.UUID,
    sources: list[SourceInfo],
    thresholds: dict[str, Threshold],
    period: Period,
    bucket_s: float,
    out: DeviceFigures,
) -> None:
    """Section 4.4: one row per data source, LoRaWAN and Iridium with their own figures; the
    fleet-level network figures take the worst source."""
    s = out.summary
    days = max((period.time_to - period.time_from).total_seconds() / DAY_S, 1e-9)
    for source in sources:
        row: dict[str, Any] = {
            "source": source.name,
            "channel": source.channel,
            "messages": source.messages,
            "per_day": round(source.messages / days, 2),
        }
        levels: list[Level | None] = []
        if source.channel == AcquisitionChannel.LORAWAN:
            receptions = await _receptions(session, device_id, source.id, period)
            counters = await _frame_counters(session, device_id, source.id, period)
            per_bucket, joins = await _uplink_days(session, device_id, source.id, period, bucket_s)
            row["lost_uplinks_share"] = lost_share(counters)
            row["gateways"] = len(receptions.gateways)
            best = receptions.best
            row["best_gateway"] = best.gateway_id if best else None
            row["best_gateway_share"] = best.share if best else None
            row["rssi_median_dbm"] = percentile(receptions.best_rssi, 50)
            row["rssi_p10_dbm"] = percentile(receptions.best_rssi, 10)
            row["snr_median_db"] = percentile(receptions.best_snr, 50)
            row["snr_p10_db"] = percentile(receptions.best_snr, 10)
            row["joins"] = joins
            row["joins_per_day"] = round(joins / days, 3)
            levels.append(_level(thresholds, "lost_uplinks_share", row["lost_uplinks_share"]))
            levels.append(_level(thresholds, "rssi_p10_dbm", row["rssi_p10_dbm"]))
            levels.append(_level(thresholds, "snr_p10_db", row["snr_p10_db"]))
            levels.append(_level(thresholds, "joins_per_day", row["joins_per_day"]))
            if best and len(receptions.gateways) == 1 and receptions.uplinks >= 10:
                levels.append("warn")
                row["single_gateway"] = True
            out.source_charts.setdefault("uplinks_per_day", {})[source.name] = per_bucket
            if receptions.times_s.size:
                out.source_charts.setdefault("rssi_per_day", {})[source.name] = bucketed(
                    receptions.times_s, receptions.best_rssi, bucket_s
                )
            points = await _gateway_points(
                session, source.id, [g.gateway_id for g in receptions.gateways]
            )
            for gateway in receptions.gateways:
                located = points.get(gateway.gateway_id)
                if located is None:
                    continue
                name, lon, lat = located
                if gateway is best:
                    row["best_gateway"] = name
                out.geometries.append(
                    Geometry(
                        kind="gateway",
                        subject_id=subject.id,
                        label=f"{name}: {round(gateway.share * 100)}% of {subject.name}'s uplinks",
                        level=gateway.share,
                        geojson={"type": "Point", "coordinates": [lon, lat]},
                        properties={
                            "period": period.key,
                            "source": source.name,
                            "uplinks": gateway.uplinks,
                            "share": gateway.share,
                            "rssi_median": gateway.rssi_median,
                            "snr_median": gateway.snr_median,
                        },
                    )
                )
            # the worst figure over the sources heads the fleet table
            for key in ("lost_uplinks_share", "rssi_p10_dbm"):
                value = row.get(key)
                if value is None:
                    continue
                current = s.get(key)
                worse = current is None or (
                    value > current if key == "lost_uplinks_share" else value < current
                )
                if worse:
                    s[key] = value
        elif source.channel == AcquisitionChannel.IRIDIUM:
            sessions = await _satellite_sessions(session, device_id, source.id, period)
            parsed: list[SatelliteSession] = []
            redeliveries = 0
            times: list[float] = []
            for when, data in sessions:
                if data.get("duplicate_of") is not None:
                    redeliveries += 1
                    continue
                item = SatelliteSession.from_dict(data)
                if item is not None:
                    parsed.append(item)
                    times.append(when)
            row["sessions"] = len(parsed)
            row["redeliveries"] = redeliveries
            row["bytes"] = sum(p.bytes for p in parsed)
            sequences = [p.sequence for p in parsed if p.sequence is not None]
            row["missed_sessions_share"] = lost_share(sequences)
            failed = sum(
                1 for p in parsed if p.status not in DELIVERED_STATUSES and p.status != "unknown"
            )
            row["failed_sessions_share"] = share(failed, len(parsed))
            levels.append(_level(thresholds, "missed_sessions_share", row["missed_sessions_share"]))
            levels.append(_level(thresholds, "failed_sessions_share", row["failed_sessions_share"]))
            if times:
                out.source_charts.setdefault("sessions_per_day", {})[source.name] = bucketed(
                    np.asarray(times), np.ones(len(times)), bucket_s, "count"
                )
            value = row["missed_sessions_share"]
            if value is not None and (
                s.get("missed_sessions_share") is None or value > s["missed_sessions_share"]
            ):
                s["missed_sessions_share"] = value
        row["level"] = worst(levels)
        out.network_rows.append(
            [source.name, source.channel]
            + [row.get(k) for k in NETWORK_COLUMNS[2:]]
            + [row["level"]]
        )
    for key in ("lost_uplinks_share", "rssi_p10_dbm", "missed_sessions_share"):
        level = _level(thresholds, key, s.get(key))
        if level is not None:
            out.levels[key] = level


async def analyse_device(
    session: AsyncSession,
    subject: Subject,
    info: DeviceInfo,
    params: DevicePerformanceParameters,
    period: Period,
    *,
    count: dict[str, int],
) -> DeviceFigures:
    """The four areas for one device in one period."""
    out = DeviceFigures()
    days = (period.time_to - period.time_from).total_seconds() / DAY_S
    bucket_s = DAY_S if days <= WEEKLY_ABOVE_DAYS else 7 * DAY_S
    driver = DRIVERS.get(info.driver_key)
    fields = getattr(driver, "health", None)
    thresholds = thresholds_for(fields)
    if not fields:
        out.warnings.append(
            Warning(
                code="no_health_fields",
                level="notice",
                subject_id=subject.id,
                text=f"{subject.name}'s driver declares no health thresholds; the defaults apply.",
            )
        )
    metrics = await _metrics(session, info.id, period)
    states = await _states(session, info.id, period)
    reboots = await _reboots(session, info.id, period)
    track = await load_trajectory(
        session,
        info.id,
        period.time_from,
        period.time_to,
        max_fixes=MAX_FIXES_PER_SUBJECT,
        by_device=True,
    )
    count["input"] += len(track) + track.duplicates + sum(len(v[0]) for v in metrics.values())
    track, rejected = exclude_impossible(track, params.max_speed_mps)
    count["excluded"] += rejected + track.duplicates
    invalid, valid = await _invalid_counts(session, info.id, period)
    sources = await _sources(session, info.id, period)
    messages = sum(s.messages for s in sources)
    if messages == 0 and len(track) == 0 and not states:
        main = period.key == "main"
        out.warnings.append(
            Warning(
                code="no_data" if main else "no_comparison_data",
                level="warning" if main else "notice",
                subject_id=subject.id,
                text=f"{subject.name} sent nothing in the "
                + ("period." if main else "comparison period."),
            )
        )
    # the declared intervals as of the period's end: a person's override, the newest settings
    # frame, an acknowledged command, the type's defaults (shared/domain/reporting.py)
    declared = await declared_intervals(session, info.device, info.device_type, period.time_to)
    health_figures(metrics, states, reboots, thresholds, period, bucket_s, out)
    status_times = np.asarray([t for t, state in states if is_status(state)], dtype=np.float64)
    if status_times.size == 0 and "battery_voltage" in metrics:
        # the state history is not curated (a clock repaired by a time offset moves the
        # measurements, not the states): the battery readings mark the statuses then
        status_times = metrics["battery_voltage"][0]
        out.summary["statuses"] = int(status_times.size)
    fix_expected, _ = reporting_figures(
        track.times, status_times, declared, invalid, valid, messages, thresholds, period, out
    )
    if fix_expected.disagrees and fix_expected.declared_seconds:
        out.warnings.append(
            Warning(
                code="interval_disagrees",
                subject_id=subject.id,
                text=(
                    f"{subject.name}'s settings say a fix every "
                    f"{_minutes(fix_expected.declared_seconds)} ({fix_expected.declared_source}), "
                    f"the collar reports every {_minutes(fix_expected.seconds or 0)}: the settings "
                    "Protect knows are stale; missed fixes are counted against what it does."
                ),
            )
        )
    elif fix_expected.seconds is None and len(track):
        seen = fix_expected.learned
        why = (
            f"the fixes are too irregular to learn it ({round(seen.regular_share * 100)} percent "
            f"near {_minutes(seen.seconds)})"
            if seen is not None
            else "too few fixes to learn it"
        )
        out.warnings.append(
            Warning(
                code="interval_unknown",
                level="notice",
                subject_id=subject.id,
                text=(
                    f"{subject.name}'s fix interval is not known and {why}; "
                    "missed fixes cannot be counted."
                ),
            )
        )
    expected = out.summary.get("expected_fix_s") or out.summary.get("expected_status_s")
    if expected and (period.time_to - period.time_from).total_seconds() < 3 * expected:
        out.warnings.append(
            Warning(
                code="short_period",
                level="notice",
                subject_id=subject.id,
                text=f"The period holds fewer than three expected reports of {subject.name}.",
            )
        )
    if invalid:
        out.warnings.append(
            Warning(
                code="invalid_records",
                subject_id=subject.id,
                text=(
                    f"{invalid} records of {subject.name} are held invalid "
                    "(a clock ahead, or curated out)."
                ),
            )
        )
    gnss_figures(metrics, track, rejected, thresholds, period, bucket_s, out)
    hull = coverage_geometry(subject, period, track)
    if hull is not None:
        out.geometries.append(hull)
    await network_figures(session, subject, info.id, sources, thresholds, period, bucket_s, out)
    out.summary["sources"] = [s.name for s in sources]
    out.summary["level"] = worst(out.levels.values())
    return out


#: The same warning over more devices than this folds into one line for the fleet.
FOLD_WARNINGS_ABOVE = 3
FOLDED_TEXTS = {
    "interval_unknown": "The fix interval of {n} devices is not known; their missed fixes cannot "
    "be counted.",
    "no_health_fields": "The driver of {n} devices declares no health thresholds; the defaults "
    "apply to them.",
    "short_period": "The period holds fewer than three expected reports of {n} devices.",
    "invalid_records": "{n} devices have records held invalid (a clock ahead, or curated out).",
    "no_data": "{n} devices sent nothing in the period.",
    "no_comparison_data": "{n} devices sent nothing in the comparison period.",
}


def fold_warnings(warnings: list[Warning]) -> list[Warning]:
    """A fleet's warnings: the same code over many devices becomes one line with the count,
    so a hundred collars without a known interval do not print a hundred lines."""
    by_code: dict[str, list[Warning]] = defaultdict(list)
    for w in warnings:
        by_code[w.code].append(w)
    out: list[Warning] = []
    for code, group in by_code.items():
        if len(group) > FOLD_WARNINGS_ABOVE and code in FOLDED_TEXTS:
            out.append(
                Warning(
                    code=code, level=group[0].level, text=FOLDED_TEXTS[code].format(n=len(group))
                )
            )
        else:
            out.extend(group)
    return out


def build_document(
    subjects: list[Subject],
    infos: dict[uuid.UUID, DeviceInfo],
    periods: list[Period],
    results: dict[tuple[str, uuid.UUID], DeviceFigures],
    params: DevicePerformanceParameters,
    *,
    input_count: int,
    excluded_count: int,
    geometries: dict[str, int],
) -> ResultDocument:
    """The result document: the summary per period and device, the levels and ranks, the
    fleet table first, the area tables, the charts and the warnings."""
    summary: dict[str, Any] = {
        "main": {},
        "comparison": {},
        "levels": {},
        "ranks": {},
        "devices": {},
    }
    warnings: list[Warning] = []
    fleet_rows: list[list[Any]] = []
    health_rows: list[list[Any]] = []
    reporting_rows: list[list[Any]] = []
    gnss_rows: list[list[Any]] = []
    network_rows: list[list[Any]] = []
    error_rows: list[list[Any]] = []
    reboot_rows: list[list[Any]] = []
    for subject in subjects:
        info = infos[subject.id]
        summary["devices"][str(subject.id)] = {
            "name": subject.name,
            "type": info.type_label,
            "driver": info.driver_key,
            "tracked": info.tracked,
        }
        for period in periods:
            m = results.get((period.key, subject.id))
            if m is None:
                continue
            summary[period.key][str(subject.id)] = m.summary
            for warning in m.warnings:
                if not any(
                    w.code == warning.code and w.subject_id == warning.subject_id for w in warnings
                ):
                    warnings.append(warning)
            health_rows.append(
                [subject.name, period.key] + [m.summary.get(k) for k in HEALTH_COLUMNS]
            )
            reporting_rows.append(
                [subject.name, period.key] + [m.summary.get(k) for k in REPORTING_COLUMNS]
            )
            gnss_rows.append([subject.name, period.key] + [m.summary.get(k) for k in GNSS_COLUMNS])
            network_rows.extend([subject.name, period.key, *row] for row in m.network_rows)
            if period.key == "main":
                summary["levels"][str(subject.id)] = m.levels
                fleet_rows.append(
                    [subject.name, m.summary.get("level")]
                    + [m.summary.get(k) for k in FLEET_COLUMNS]
                )
                error_rows.extend([subject.name, *row] for row in m.error_rows)
                reboot_rows.extend([subject.name, *row] for row in m.reboot_rows)
    warnings = fold_warnings(warnings)
    # the fleet's ranks per indicator, over the main period
    if len(subjects) > 1:
        for key in FLEET_COLUMNS:
            values = {
                str(s.id): results[("main", s.id)].summary.get(key)
                for s in subjects
                if ("main", s.id) in results
            }
            numeric = {
                k: (float(v) if isinstance(v, int | float) else None) for k, v in values.items()
            }
            for device_id, rank in ranks(numeric, key).items():
                summary["ranks"].setdefault(device_id, {})[key] = rank
    order = {"critical": 0, "warn": 1, "ok": 2, None: 3}
    fleet_rows.sort(key=lambda r: (order.get(r[1], 3), r[0]))
    summary["defaults"] = {key: threshold.describe() for key, threshold in DEFAULTS.items()}
    tables = [
        Table(key="fleet", columns=["device", "level", *FLEET_COLUMNS], rows=fleet_rows),
        Table(key="health", columns=["device", "period", *HEALTH_COLUMNS], rows=health_rows),
        Table(
            key="reporting", columns=["device", "period", *REPORTING_COLUMNS], rows=reporting_rows
        ),
        Table(key="gnss", columns=["device", "period", *GNSS_COLUMNS], rows=gnss_rows),
        Table(
            key="network",
            columns=["device", "period", "source", "channel", *NETWORK_COLUMNS[2:], "level"],
            rows=network_rows,
        ),
        Table(
            key="errors", columns=["device", "flag", "statuses", "share", "level"], rows=error_rows
        ),
        Table(key="reboots", columns=["device", "time", "reason"], rows=reboot_rows),
    ]
    charts: list[Chart] = []
    per_device = [
        ("battery", "line", "V"),
        ("temperature", "line", "°C"),
        ("fixes_per_day", "bar", "fixes"),
        ("time_to_fix", "bar", "attempts"),
        ("accuracy", "bar", "fixes"),
        ("satellites", "bar", "fixes"),
    ]
    for key, kind, unit in per_device:
        series = []
        for period in periods:
            for subject in subjects:
                m = results.get((period.key, subject.id))
                if m is None or key not in m.charts or not m.charts[key]:
                    continue
                series.append(
                    {"subject": str(subject.id), "period": period.key, "data": m.charts[key]}
                )
        if series:
            charts.append(Chart(key=key, kind=kind, unit=unit, series=series))
    per_source = [
        ("uplinks_per_day", "bar", "uplinks"),
        ("rssi_per_day", "line", "dBm"),
        ("sessions_per_day", "bar", "sessions"),
    ]
    for key, kind, unit in per_source:
        series = []
        for period in periods:
            for subject in subjects:
                m = results.get((period.key, subject.id))
                if m is None:
                    continue
                for source_name, data in m.source_charts.get(key, {}).items():
                    if data:
                        series.append(
                            {
                                "subject": str(subject.id),
                                "period": period.key,
                                "name": f"{subject.name} · {source_name}",
                                "data": data,
                            }
                        )
        if series:
            charts.append(Chart(key=key, kind=kind, unit=unit, series=series))
    return ResultDocument(
        module="device_performance",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=periods,
        summary=summary,
        tables=tables,
        charts=charts,
        geometries=geometries,
        warnings=warnings,
        provenance=Provenance(
            module="device_performance",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=[
                "positions (device fixes, effective time and geometry, valid rows)",
                "measurements (battery, temperature, uptime, activity, GNSS figures, flash)",
                "device state history (error flags, reset reasons, firmware, settings frames)",
                "events (device_reset)",
                "source events, gateway receptions and satellite sessions per data source",
            ],
        ),
    )


class DevicePerformanceModule:
    key = "device_performance"
    label = "Device performance"
    version = METHOD_VERSION
    subject_kind = "device"
    parameters: type[BaseModel] = DevicePerformanceParameters

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, DevicePerformanceParameters)
        session = ctx.session
        periods = [Period(key="main", time_from=params.time_from, time_to=params.time_to)]
        if params.comparison:
            periods.append(
                Period(
                    key="comparison",
                    time_from=params.comparison.time_from,
                    time_to=params.comparison.time_to,
                )
            )
        infos = {d.id: d for d in await load_devices(session, params.device_ids, periods[0])}
        subjects = [
            Subject(id=d.id, name=d.name, type=d.type_label, kind="device", tracked=d.tracked)
            for d in infos.values()
        ]
        results: dict[tuple[str, uuid.UUID], DeviceFigures] = {}
        geometries: list[Geometry] = []
        count = {"input": 0, "excluded": 0}
        total = max(1, len(subjects) * len(periods))
        done = 0
        for period in periods:
            for subject in subjects:
                await ctx.progress(int(done * 90 / total), f"{subject.name} ({period.key})")
                m = await analyse_device(
                    session, subject, infos[subject.id], params, period, count=count
                )
                results[(period.key, subject.id)] = m
                if period.key == "main":
                    geometries.extend(m.geometries)
                done += 1
        await ctx.progress(95, "document")
        counts: dict[str, int] = {}
        for g in geometries:
            counts[g.kind] = counts.get(g.kind, 0) + 1
        document = build_document(
            subjects,
            infos,
            periods,
            results,
            params,
            input_count=count["input"],
            excluded_count=count["excluded"],
            geometries=counts,
        )
        return RunResult(document=document, geometries=geometries)
