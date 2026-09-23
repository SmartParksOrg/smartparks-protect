"""How an animal's heart was doing (docs/CARDIAC_MONITORING_PLAN.md, section 4).

The readings come from a LINQII cardiac tag on the animal, heard over Bluetooth by the collar it
wears and relayed on port 15 (decision D282), so every figure here rests on two things going
right: the tag had something to say, and the collar was listening when it said it. That is why
the run answers what was heard before it answers what the heart was doing. A quiet tag and a calm
animal look the same in a heart rate chart, and only the coverage block tells them apart.

Phase 35 reads the whole record the same way (decisions D287 to D290): the heart rate, its
variability, the implant's activity and its temperature, each in the day, the night and the
resting hours, as a rhythm over the hours of the day, as a course over the dates, and before and
after an event; with the minutes of restless activity per night beside them.

What this module does not do is judge. There is no normal range for a heart rate here, because it
depends on the species, the age, the season and what the animal was doing a minute ago, and
nobody has given us those numbers. It reports what was measured, at what times of day, and how
much of it there was.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis.base import (
    Chart,
    Period,
    Provenance,
    ResultDocument,
    RunContext,
    RunResult,
    Subject,
    Table,
    Warning,
)
from shared.analysis.limits import MAX_ROWS_PER_DEVICE, MAX_SUBJECTS_CARDIAC
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.cardiac import (
    DEFAULT_QUIET_HOURS,
    DEFAULT_RESTING_QUANTILE,
    DEFAULT_RESTLESS_ACTIVITY,
    FALLBACK_DAY_HOURS,
    MIN_READINGS,
    PARTS,
    Coverage,
    Spread,
    before_after,
    box,
    coverage,
    daily_medians,
    daylight,
    fixed_daylight,
    hour_profile,
    local_days,
    local_hours,
    night_days,
    part_masks,
    plausible,
    real_activity,
    report_step_s,
    resting_rate,
    restless_nights,
    spread,
    temperature_disagreement,
)
from shared.curation.effective import (
    effective_geom,
    effective_number,
    effective_time,
    in_window,
    visible,
)
from shared.models import Entity, EntityCurrentState, EntityType, Measurement, Position, Project
from shared.models.settings import DeviceSetting

METHOD_VERSION = "cardiac-2.0.0"
YIELD_PER = 5_000

#: The heart rate and what stands beside it. `cmdq_success` says a sighting carried a reading at
#: all, which is how the coverage block tells a quiet tag from a calm animal.
HEART_RATE = "heart_rate"
HRV = "heart_rate_variability"
TAG_TEMPERATURE = "cmdq_temperature"
SUCCESS = "cmdq_success"
#: The implant's own accelerometer score, 0 to 255 without a unit (decision D287).
ACTIVITY = "cmdq_activity_average"
COLLAR_TEMPERATURE = "device_temperature"
CARDIAC_KEYS = (HEART_RATE, HRV, TAG_TEMPERATURE, SUCCESS, ACTIVITY)
LOADED_KEYS = (*CARDIAC_KEYS, COLLAR_TEMPERATURE)

#: How often the collar composes a port 15 message. The coverage block reads it per device to
#: say how much of what was promised actually arrived.
REPORTING_INTERVAL_SETTING = "cmdq_reporting_interval"
#: A tag reading this much colder than the collar has probably left the animal.
TEMPERATURE_GAP_C = 3.0

#: The four metrics read in every part of the day (decision D290), by the name the document
#: uses, with the measurement behind each and its unit.
METRICS: dict[str, tuple[str, str]] = {
    "heart_rate": (HEART_RATE, "bpm"),
    "hrv": (HRV, "ms"),
    "activity": (ACTIVITY, "score"),
    "temperature": (TAG_TEMPERATURE, "°C"),
}
#: The figures the charts are drawn from; the stored summary keeps the charts rather than a
#: second copy of every day and hour.
CHART_ONLY = ("rhythm", "daily")


class CardiacParameters(CommonParameters):
    """The subjects and the period, plus how a resting heart rate is read. Both are parameters
    rather than constants because the quiet hours of a rhino are not those of a bat, and a
    reader should be able to see which numbers produced the figure."""

    quiet_from_hour: int = Field(default=DEFAULT_QUIET_HOURS[0], ge=0, le=23)
    quiet_to_hour: int = Field(default=DEFAULT_QUIET_HOURS[1], ge=0, le=23)
    resting_quantile: float = Field(default=DEFAULT_RESTING_QUANTILE, ge=0.01, le=0.5)
    #: A moment inside the period to compare before and after (decision D289).
    event_at: datetime | None = None
    #: Activity above this is a restless moment at night, on the implant's 0 to 255 scale.
    restless_activity: int = Field(default=DEFAULT_RESTLESS_ACTIVITY, ge=1, le=254)

    @model_validator(mode="after")
    def _event_inside(self) -> CardiacParameters:
        if self.event_at is None:
            return self
        if self.event_at.tzinfo is None:
            raise ValueError("the event date needs a timezone")
        if not self.time_from < self.event_at < self.time_to:
            raise ValueError("the event date must fall inside the period")
        return self


class Readings:
    """One subject's readings in one period, as arrays keyed by metric."""

    def __init__(self) -> None:
        self.times: dict[str, list[float]] = defaultdict(list)
        self.values: dict[str, list[float]] = defaultdict(list)

    def add(self, key: str, at: datetime, value: float) -> None:
        self.times[key].append(at.timestamp())
        self.values[key].append(value)

    def array(self, key: str) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return (
            np.array(self.times.get(key, []), dtype=float),
            np.array(self.values.get(key, []), dtype=float),
        )

    @property
    def empty(self) -> bool:
        return not self.times


async def load_readings(
    session: AsyncSession, entity_id: uuid.UUID, period: Period
) -> tuple[Readings, int]:
    """Every cardiac metric of one subject in one streamed read, through the effective value
    (decision D80), so a corrected time or value is the one the analysis sees."""
    statement = (
        select(
            Measurement.metric_key,
            effective_time(Measurement).label("at"),
            effective_number().label("value"),
            Measurement.value_bool,
        )
        .where(
            Measurement.entity_id == entity_id,
            Measurement.metric_key.in_(LOADED_KEYS),
            in_window(Measurement, period.time_from, period.time_to),
            visible(Measurement),
        )
        .order_by(effective_time(Measurement))
        .execution_options(yield_per=YIELD_PER)
    )
    readings = Readings()
    count = 0
    async for key, at, value, flag in await session.stream(statement):
        count += 1
        if count > MAX_ROWS_PER_DEVICE:
            raise ValueError(
                f"more than {MAX_ROWS_PER_DEVICE} cardiac readings for one subject; "
                "choose a shorter period"
            )
        # `cmdq_success` is a boolean measurement, so it has no numeric value of its own.
        readings.add(key, at, float(flag) if value is None and flag is not None else value or 0.0)
    return readings, count


async def reporting_intervals(
    session: AsyncSession, entity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """The `cmdq_reporting_interval` of the device each subject wears, where a device has ever
    reported it. A device nobody has read the settings of is simply absent, and the coverage
    block then reports what was heard without a share."""
    if not entity_ids:
        return {}
    rows = (
        await session.execute(
            select(Measurement.entity_id, DeviceSetting.value)
            .join(DeviceSetting, DeviceSetting.device_id == Measurement.device_id)
            .where(
                Measurement.entity_id.in_(entity_ids),
                Measurement.metric_key == SUCCESS,
                DeviceSetting.key == REPORTING_INTERVAL_SETTING,
            )
            .distinct()
        )
    ).all()
    out: dict[uuid.UUID, float] = {}
    for entity_id, value in rows:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            out[entity_id] = seconds
    return out


async def subject_place(
    session: AsyncSession, entity_id: uuid.UUID, period: Period
) -> tuple[float, float, str] | None:
    """Where to read the sun for one subject (decision D288): its mean position in the period,
    else where it stands now, as `(lat, lon, source)`; None when it has neither and day and night
    fall back to the clock. Any position counts, a place set by hand included: the question is
    where the animal is under the sky, not what made the fix."""
    geom = effective_geom()
    lat, lon = (
        await session.execute(
            select(func.avg(func.ST_Y(geom)), func.avg(func.ST_X(geom))).where(
                Position.entity_id == entity_id,
                in_window(Position, period.time_from, period.time_to),
                visible(Position),
            )
        )
    ).one()
    if lat is not None and lon is not None:
        return float(lat), float(lon), "sun"
    now = (
        await session.execute(
            select(
                func.ST_Y(EntityCurrentState.latest_position),
                func.ST_X(EntityCurrentState.latest_position),
            ).where(
                EntityCurrentState.entity_id == entity_id,
                EntityCurrentState.latest_position.is_not(None),
            )
        )
    ).first()
    if now is None:
        return None
    return float(now[0]), float(now[1]), "sun at the current position"


def zone_offsets(times_s: NDArray[np.float64], zone: tzinfo) -> NDArray[np.float64]:
    """The zone's offset in seconds at each moment, so the rhythm is read on the local clock and
    a period that crosses a daylight saving change is read on both sides of it."""
    return np.array(
        [
            (datetime.fromtimestamp(t, tz=zone).utcoffset() or timedelta()).total_seconds()
            for t in times_s
        ],
        dtype=np.float64,
    )


def metric_readings(
    readings: Readings, metric: str
) -> tuple[NDArray[np.float64], NDArray[np.float64], int]:
    """One metric's usable readings and how many were set aside: heart rates outside what a heart
    can do, and the implant's hourly 0 for activity (decision D287)."""
    times, values = readings.array(METRICS[metric][0])
    if metric == "heart_rate":
        keep = plausible(values)
    elif metric == "activity":
        keep = real_activity(values)
    else:
        keep = np.isfinite(values)
    return times[keep], values[keep], int(values.size - np.count_nonzero(keep))


def _rows(profile: list[tuple[int, float, int]]) -> list[list[float | int]]:
    return [[key, round(value, 2), n] for key, value, n in profile]


def metric_block(
    times: NDArray[np.float64],
    values: NDArray[np.float64],
    zone: tzinfo,
    params: CardiacParameters,
    place: tuple[float, float, str] | None,
    event_s: float | None,
) -> dict[str, Any]:
    """One metric of one subject read every way the module reads it (decision D290): its spread,
    a box per part of the day, the rhythm over the hours, the day and night medians per date,
    and, with an event, each part before and after it."""
    offsets = zone_offsets(times, zone)
    hours = local_hours(times, offsets)
    is_day = daylight(times, place[0], place[1]) if place else fixed_daylight(hours)
    masks = part_masks(is_day, hours, (params.quiet_from_hour, params.quiet_to_hour))
    days = local_days(times, offsets)
    whole = spread(values)
    block: dict[str, Any] = {
        "spread": whole.as_dict() if whole else None,
        "parts": {
            part: shape.as_dict()
            for part, mask in masks.items()
            if (shape := box(values[mask])) is not None
        },
        "rhythm": _rows(hour_profile(hours, values)),
        "daily": {
            part: _rows(daily_medians(days[masks[part]], values[masks[part]]))
            for part in ("day", "night")
        },
    }
    if event_s is not None:
        block["event"] = {
            part: change
            for part, mask in masks.items()
            if (change := before_after(times[mask], values[mask], event_s)) is not None
        }
    return block


def subject_figures(
    readings: Readings,
    period: Period,
    zone: tzinfo,
    params: CardiacParameters,
    reporting_interval_s: float | None,
    place: tuple[float, float, str] | None,
    event_at: datetime | None = None,
) -> dict[str, Any]:
    """Every figure of one subject in one period. Times are in UTC seconds and read on the
    project's clock through `zone`, the way the movement and grazing modules read theirs; day
    and night come from the sun at `place`, or from the clock when there is none."""
    success_times, success = readings.array(SUCCESS)
    seen = coverage(
        success_times,
        success.astype(bool),
        (period.time_to - period.time_from).total_seconds(),
        reporting_interval_s,
    )
    figures: dict[str, Any] = {
        "coverage": seen.as_dict(),
        "dropped_implausible": 0,
        "activity_faults": 0,
        "day_night_from": place[2] if place else "fixed hours",
        "metrics": {},
    }
    event_s = event_at.timestamp() if event_at else None
    for metric in METRICS:
        times, values, set_aside = metric_readings(readings, metric)
        if metric == "heart_rate":
            figures["dropped_implausible"] = set_aside
        elif metric == "activity":
            figures["activity_faults"] = set_aside
        if not times.size:
            continue
        figures["metrics"][metric] = metric_block(times, values, zone, params, place, event_s)
        if metric == "heart_rate":
            _heart_rate_figures(figures, times, values, zone, params)
        elif metric == "activity":
            _restless(figures, times, values, zone, params, place, reporting_interval_s)
    # the spreads under the names the cards and the older runs read
    legacy = (("hrv", "hrv"), ("temperature", "tag_temperature"), ("activity", "activity"))
    for metric, key in legacy:
        block = figures["metrics"].get(metric)
        if block and block["spread"]:
            figures[key] = block["spread"]
    tag_temperature = metric_readings(readings, "temperature")[1]
    collar = readings.array(COLLAR_TEMPERATURE)[1]
    difference = temperature_disagreement(tag_temperature, collar, TEMPERATURE_GAP_C)
    if difference is not None:
        figures["temperature_difference"] = round(difference, 2)
    return figures


def _heart_rate_figures(
    figures: dict[str, Any],
    times: NDArray[np.float64],
    bpm: NDArray[np.float64],
    zone: tzinfo,
    params: CardiacParameters,
) -> None:
    """The heart rate figures phase 34 wrote, which the cards and the older runs read."""
    rate = spread(bpm)
    if rate:
        figures["heart_rate"] = rate.as_dict()
    hours = local_hours(times, zone_offsets(times, zone))
    figures["by_hour"] = [
        {"hour": hour, "median": round(median, 1), "n": n}
        for hour, median, n in hour_profile(hours, bpm)
    ]
    rest = resting_rate(
        hours, bpm, (params.quiet_from_hour, params.quiet_to_hour), params.resting_quantile
    )
    if rest:
        figures["resting_heart_rate"] = round(rest[0], 1)
        figures["resting_readings"] = rest[1]


def _restless(
    figures: dict[str, Any],
    times: NDArray[np.float64],
    activity: NDArray[np.float64],
    zone: tzinfo,
    params: CardiacParameters,
    place: tuple[float, float, str] | None,
    reporting_interval_s: float | None,
) -> None:
    """Minutes of restless activity per night (decision D290): each reading above the threshold
    stands for one report step, measured from the readings themselves before the settings."""
    step = report_step_s(times) or reporting_interval_s
    if not step:
        return
    offsets = zone_offsets(times, zone)
    hours = local_hours(times, offsets)
    night = ~(daylight(times, place[0], place[1]) if place else fixed_daylight(hours))
    nights = restless_nights(
        night_days(times, offsets)[night], activity[night], params.restless_activity, step
    )
    figures["restless"] = {
        "nights": [[day, minutes, n] for day, minutes, n in nights],
        "median_minutes": (
            round(float(np.median([m for _, m, _ in nights])), 1) if nights else None
        ),
        "threshold": params.restless_activity,
        "step_minutes": round(step / 60, 2),
    }


def subject_warnings(subject: Subject, figures: dict[str, Any], period: Period) -> list[Warning]:
    """What a reader must know before believing the figures above."""
    out: list[Warning] = []
    seen: dict[str, Any] = figures.get("coverage", {})
    if not seen.get("heard"):
        out.append(
            Warning(
                code="nothing_heard",
                subject_id=subject.id,
                text=(
                    f"{subject.name} reported no cardiac tag at all in this period. Either the "
                    "collar was not scanning for one, or the tag was out of range the whole time."
                ),
            )
        )
        return out
    if not seen.get("with_reading"):
        out.append(
            Warning(
                code="heard_without_readings",
                subject_id=subject.id,
                text=(
                    f"The tag on {subject.name} was heard {seen['heard']} times and carried a "
                    "cardiac reading none of those times. The tag is alive and is measuring "
                    "nothing, which usually means it is not against the skin."
                ),
            )
        )
    share = seen.get("heard_share")
    if share is not None and share < 0.5:
        out.append(
            Warning(
                code="heard_less_than_promised",
                subject_id=subject.id,
                level="notice",
                text=(
                    f"{subject.name} was heard {seen['heard']} times against about "
                    f"{seen['expected']} the device's reporting interval promises. The rhythm "
                    "below rests on the hours the collar happened to be listening."
                ),
            )
        )
    gap = seen.get("longest_gap_hours")
    if gap is not None and gap > 24:
        out.append(
            Warning(
                code="long_silence",
                subject_id=subject.id,
                level="notice",
                text=(
                    f"The longest silence for {subject.name} was {gap:.0f} hours. A daily rhythm "
                    "read over a period with a gap that long is missing whole days."
                ),
            )
        )
    rate = figures.get("heart_rate") or {}
    if rate and rate.get("n", 0) < MIN_READINGS:
        out.append(
            Warning(
                code="few_readings",
                subject_id=subject.id,
                text=(
                    f"{subject.name} has {rate['n']} usable heart rate readings, which is too "
                    "few to describe a distribution. The figures are shown as measurements, not "
                    "as a summary of the animal."
                ),
            )
        )
    if figures.get("dropped_implausible"):
        out.append(
            Warning(
                code="implausible_dropped",
                subject_id=subject.id,
                level="notice",
                text=(
                    f"{figures['dropped_implausible']} readings of {subject.name} were outside "
                    "the range a heart can beat at and were left out of every figure."
                ),
            )
        )
    difference = figures.get("temperature_difference")
    if difference is not None and abs(difference) >= TEMPERATURE_GAP_C:
        out.append(
            Warning(
                code="temperature_disagrees",
                subject_id=subject.id,
                text=(
                    f"The tag on {subject.name} reads {difference:+.1f} C against the collar's "
                    "own temperature. A tag that has come off the animal reads the air while "
                    "the collar still reads the animal."
                ),
            )
        )
    if figures.get("day_night_from") == "fixed hours" and figures.get("metrics"):
        start, end = FALLBACK_DAY_HOURS
        out.append(
            Warning(
                code="day_night_by_the_clock",
                subject_id=subject.id,
                level="notice",
                text=(
                    f"{subject.name} has no position to read the sun at, so its day runs from "
                    f"{start:02d}:00 to {end:02d}:00 on the local clock and its night the rest."
                ),
            )
        )
    if "hrv" not in figures and figures.get("heart_rate"):
        out.append(
            Warning(
                code="no_hrv",
                subject_id=subject.id,
                level="notice",
                text=(
                    f"No heart rate variability for {subject.name}. The tag sends it only from "
                    "firmware 6.9.0 onwards."
                ),
            )
        )
    return out


HOURS = [f"{hour:02d}" for hour in range(24)]


def _day_ms(day: int) -> int:
    """A local date (days since 1970) as the epoch milliseconds of its noon, where a daily
    point sits on a time axis."""
    return (day * 86_400 + 43_200) * 1000


def metric_charts(
    subjects: list[Subject], figures_of: dict[uuid.UUID, dict[str, Any]], event_at: datetime | None
) -> list[Chart]:
    """The views of decision D290 for every metric that has readings: the rhythm over the hours,
    a box per part of the day, and the day and night course over the dates."""
    charts: list[Chart] = []
    marks = [{"at": int(event_at.timestamp() * 1000), "label": "event_at"}] if event_at else []
    for metric, (_, unit) in METRICS.items():
        blocks = {
            subject.id: block
            for subject in subjects
            if (block := (figures_of.get(subject.id) or {}).get("metrics", {}).get(metric))
        }
        if not blocks:
            continue
        rhythm = []
        parts = []
        daily = []
        for subject_id, block in blocks.items():
            by_hour = {int(hour): value for hour, value, _ in block["rhythm"]}
            rhythm.append(
                {
                    "subject": str(subject_id),
                    "data": [[label, by_hour.get(hour)] for hour, label in enumerate(HOURS)],
                }
            )
            parts.append(
                {
                    "subject": str(subject_id),
                    "data": [
                        [
                            part,
                            [shape[k] for k in ("low", "q1", "median", "q3", "high")]
                            if (shape := block["parts"].get(part))
                            else None,
                        ]
                        for part in PARTS
                    ],
                }
            )
            for part in ("day", "night"):
                points = [[_day_ms(day), value] for day, value, _ in block["daily"][part]]
                if points:
                    daily.append({"subject": str(subject_id), "part": part, "data": points})
        charts.append(Chart(key=f"rhythm_{metric}", kind="line", unit=unit, series=rhythm))
        charts.append(Chart(key=f"parts_{metric}", kind="box", unit=unit, series=parts))
        if daily:
            charts.append(
                Chart(key=f"daily_{metric}", kind="line", unit=unit, series=daily, marks=marks)
            )
    restless = [
        {
            "subject": str(subject.id),
            "data": [[_day_ms(day), minutes] for day, minutes, _ in nights],
        }
        for subject in subjects
        if (nights := ((figures_of.get(subject.id) or {}).get("restless") or {}).get("nights"))
    ]
    if restless:
        charts.append(Chart(key="restless", kind="line", unit="min", series=restless, marks=marks))
    return charts


def build_document(
    subjects: list[Subject],
    periods: list[Period],
    per_subject: dict[tuple[uuid.UUID, str], dict[str, Any]],
    params: CardiacParameters,
    warnings: list[Warning],
    input_count: int,
    excluded_count: int,
) -> ResultDocument:
    """The summary, the tables and the charts a run stores."""
    summary: dict[str, Any] = {
        "subjects": {},
        "settings": _settings(params),
    }
    rows: list[list[Any]] = []
    quality: list[list[Any]] = []
    part_rows: list[list[Any]] = []
    event_rows: list[list[Any]] = []
    main = {
        subject.id: per_subject[(subject.id, "main")]
        for subject in subjects
        if (subject.id, "main") in per_subject
    }
    for subject in subjects:
        figures = main.get(subject.id)
        if figures is None:
            continue
        summary["subjects"][str(subject.id)] = _stored(figures)
        rate = figures.get("heart_rate") or {}
        seen = figures.get("coverage") or {}
        rows.append(
            [
                subject.name,
                rate.get("median"),
                figures.get("resting_heart_rate"),
                rate.get("p10"),
                rate.get("p90"),
                (figures.get("hrv") or {}).get("median"),
                (figures.get("activity") or {}).get("median"),
                (figures.get("tag_temperature") or {}).get("median"),
                (figures.get("restless") or {}).get("median_minutes"),
                rate.get("n", 0),
            ]
        )
        quality.append(
            [
                subject.name,
                seen.get("heard", 0),
                seen.get("with_reading", 0),
                seen.get("expected"),
                _percent(seen.get("reading_share")),
                _percent(seen.get("heard_share")),
                seen.get("longest_gap_hours"),
            ]
        )
        for metric, block in figures.get("metrics", {}).items():
            for part in PARTS:
                shape = block["parts"].get(part)
                if shape:
                    part_rows.append(
                        [
                            subject.name,
                            metric,
                            part,
                            shape["n"],
                            shape["median"],
                            shape["q1"],
                            shape["q3"],
                        ]
                    )
                change = (block.get("event") or {}).get(part)
                if change:
                    event_rows.append(
                        [
                            subject.name,
                            metric,
                            part,
                            (change["before"] or {}).get("median"),
                            (change["after"] or {}).get("median"),
                            change["difference"],
                        ]
                    )
    charts = metric_charts(subjects, main, params.event_at)
    tables = [
        Table(
            key="cardiac",
            columns=[
                "Subject",
                "Median heart rate (bpm)",
                "Resting heart rate (bpm)",
                "Low (p10)",
                "High (p90)",
                "Median HRV (ms)",
                "Median activity (score)",
                "Median tag temperature (C)",
                "Restless minutes per night",
                "Readings",
            ],
            rows=rows,
        ),
        Table(
            key="parts",
            # keys rather than words: the page and the report name them from their labels
            columns=["subject", "metric", "part", "readings", "median", "q1", "q3"],
            rows=part_rows,
        ),
        Table(
            key="coverage",
            columns=[
                "Subject",
                "Times heard",
                "With a reading",
                "Expected",
                "Share with a reading",
                "Share heard",
                "Longest silence (hours)",
            ],
            rows=quality,
        ),
    ]
    if event_rows:
        tables.insert(
            2,
            Table(
                key="event",
                columns=["subject", "metric", "part", "before", "after", "change"],
                rows=event_rows,
            ),
        )
    comparison = {
        str(subject.id): _stored(per_subject[(subject.id, "comparison")])
        for subject in subjects
        if (subject.id, "comparison") in per_subject
    }
    if comparison:
        summary["comparison"] = comparison
    return ResultDocument(
        module="cardiac",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=periods,
        summary=summary,
        tables=tables,
        charts=charts,
        warnings=warnings,
        provenance=Provenance(
            module="cardiac",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=[
                "measurements (cardiac tag, port 15)",
                "device_settings",
                "positions (where the sun is read)",
            ],
        ),
    )


def _stored(figures: dict[str, Any]) -> dict[str, Any]:
    """A subject's figures as the summary keeps them: the charts already hold every hour and
    date, so the summary keeps the boxes, the changes and the spreads rather than a second copy."""
    out = dict(figures)
    out["metrics"] = {
        metric: {k: v for k, v in block.items() if k not in CHART_ONLY}
        for metric, block in figures.get("metrics", {}).items()
    }
    if "restless" in out:
        out["restless"] = {k: v for k, v in out["restless"].items() if k != "nights"}
    return out


def _settings(params: CardiacParameters) -> dict[str, Any]:
    """The numbers behind the figures, so a reader never has to guess what "resting" meant."""
    return {
        "quiet_hours": [params.quiet_from_hour, params.quiet_to_hour],
        "resting_quantile": params.resting_quantile,
        "minimum_readings": MIN_READINGS,
        "day_and_night": "the sun at the subject's mean position; fixed hours "
        f"{FALLBACK_DAY_HOURS[0]:02d}:00 to {FALLBACK_DAY_HOURS[1]:02d}:00 without one",
        "restless_activity": params.restless_activity,
        "event_at": params.event_at.isoformat() if params.event_at else None,
    }


def _percent(share: float | None) -> float | None:
    return None if share is None else round(share * 100, 1)


class CardiacModule:
    key = "cardiac"
    label = "Cardiac monitoring"
    version = METHOD_VERSION
    parameters: type[BaseModel] = CardiacParameters

    async def check(
        self, session: AsyncSession, project_id: uuid.UUID, params: BaseModel
    ) -> list[str]:
        """What the estimate can already say. The generic estimate counts fixes, and a cardiac
        tag has nothing to do with fixes: a scanner bolted to a post reads a heart every hour
        and never moves. So the count that matters is answered here, and a period without a
        single reading is refused before a run is queued rather than after it returns empty."""
        assert isinstance(params, CardiacParameters)
        if not params.entity_ids:
            return []
        readings = await session.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(
                Measurement.entity_id.in_(params.entity_ids),
                Measurement.metric_key.in_(CARDIAC_KEYS),
                in_window(Measurement, params.time_from, params.time_to),
                visible(Measurement),
            )
        )
        if not readings:
            return [
                "No cardiac readings for these subjects in this period. The collar reports them "
                "on port 15 when it is set to follow a tag (cmdq_enabled), so check the device's "
                "settings before the period."
            ]
        return []

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, CardiacParameters)
        session = ctx.session
        rows = (
            await session.execute(
                select(Entity.id, Entity.name, EntityType.label)
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(Entity.id.in_(params.entity_ids), Entity.project_id == ctx.project_id)
                .order_by(Entity.name)
            )
        ).all()
        subjects = [
            Subject(id=r.id, name=r.name, type=r.label) for r in rows[:MAX_SUBJECTS_CARDIAC]
        ]
        warnings: list[Warning] = []
        if len(rows) > MAX_SUBJECTS_CARDIAC:
            warnings.append(
                Warning(
                    code="subjects_capped",
                    text=(
                        f"{len(rows)} subjects were chosen and the first {MAX_SUBJECTS_CARDIAC} "
                        "by name were used."
                    ),
                )
            )
        if params.quiet_from_hour == params.quiet_to_hour:
            warnings.append(
                Warning(
                    code="quiet_hours_are_one_hour",
                    level="notice",
                    text=(
                        "The quiet hours start and end in the same hour, so the resting heart "
                        "rate rests on one hour of the day."
                    ),
                )
            )

        zone_name = await session.scalar(
            select(Project.timezone).where(Project.id == ctx.project_id)
        )
        zone = ZoneInfo(zone_name) if zone_name else UTC
        periods = [Period(key="main", time_from=params.time_from, time_to=params.time_to)]
        if params.comparison:
            periods.append(
                Period(
                    key="comparison",
                    time_from=params.comparison.time_from,
                    time_to=params.comparison.time_to,
                )
            )
        intervals = await reporting_intervals(session, [s.id for s in subjects])

        per_subject: dict[tuple[uuid.UUID, str], dict[str, Any]] = {}
        input_count = 0
        steps = max(1, len(subjects) * len(periods))
        done = 0
        for period in periods:
            for subject in subjects:
                if await ctx.cancelled():
                    break
                await ctx.progress(int(done * 90 / steps), f"{subject.name} ({period.key})")
                readings, count = await load_readings(session, subject.id, period)
                input_count += count
                figures = subject_figures(
                    readings,
                    period,
                    zone,
                    params,
                    intervals.get(subject.id),
                    await subject_place(session, subject.id, period),
                    params.event_at if period.key == "main" else None,
                )
                per_subject[(subject.id, period.key)] = figures
                if period.key == "main":
                    warnings.extend(subject_warnings(subject, figures, period))
                done += 1

        await ctx.progress(95, "writing the result")
        excluded = sum(
            int(f.get("dropped_implausible", 0)) + int(f.get("activity_faults", 0))
            for f in per_subject.values()
        )
        document = build_document(
            subjects, periods, per_subject, params, warnings, input_count, excluded
        )
        return RunResult(document=document, geometries=[])


__all__ = [
    "CardiacModule",
    "CardiacParameters",
    "Coverage",
    "Spread",
    "build_document",
    "load_readings",
    "metric_charts",
    "subject_figures",
    "subject_place",
    "subject_warnings",
]
