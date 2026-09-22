"""How an animal's heart was doing (docs/CARDIAC_MONITORING_PLAN.md, section 4).

The readings come from a LINQII cardiac tag on the animal, heard over Bluetooth by the collar it
wears and relayed on port 15 (decision D282), so every figure here rests on two things going
right: the tag had something to say, and the collar was listening when it said it. That is why
the run answers what was heard before it answers what the heart was doing. A quiet tag and a calm
animal look the same in a heart rate chart, and only the coverage block tells them apart.

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
from pydantic import BaseModel, Field
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
    MIN_READINGS,
    Coverage,
    Spread,
    coverage,
    hour_profile,
    local_hours,
    plausible,
    resting_rate,
    spread,
    temperature_disagreement,
)
from shared.curation.effective import effective_number, effective_time, in_window, visible
from shared.models import Entity, EntityType, Measurement, Project
from shared.models.settings import DeviceSetting

METHOD_VERSION = "cardiac-1.0.0"
YIELD_PER = 5_000

#: The heart rate and what stands beside it. `cmdq_success` says a sighting carried a reading at
#: all, which is how the coverage block tells a quiet tag from a calm animal.
HEART_RATE = "heart_rate"
HRV = "heart_rate_variability"
TAG_TEMPERATURE = "cmdq_temperature"
SUCCESS = "cmdq_success"
COLLAR_TEMPERATURE = "device_temperature"
CARDIAC_KEYS = (HEART_RATE, HRV, TAG_TEMPERATURE, SUCCESS)
LOADED_KEYS = (*CARDIAC_KEYS, COLLAR_TEMPERATURE)

#: How often the collar composes a port 15 message. The coverage block reads it per device to
#: say how much of what was promised actually arrived.
REPORTING_INTERVAL_SETTING = "cmdq_reporting_interval"
#: A tag reading this much colder than the collar has probably left the animal.
TEMPERATURE_GAP_C = 3.0


class CardiacParameters(CommonParameters):
    """The subjects and the period, plus how a resting heart rate is read. Both are parameters
    rather than constants because the quiet hours of a rhino are not those of a bat, and a
    reader should be able to see which numbers produced the figure."""

    quiet_from_hour: int = Field(default=DEFAULT_QUIET_HOURS[0], ge=0, le=23)
    quiet_to_hour: int = Field(default=DEFAULT_QUIET_HOURS[1], ge=0, le=23)
    resting_quantile: float = Field(default=DEFAULT_RESTING_QUANTILE, ge=0.01, le=0.5)


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


def subject_figures(
    readings: Readings,
    period: Period,
    offsets_s: NDArray[np.float64],
    params: CardiacParameters,
    reporting_interval_s: float | None,
) -> dict[str, Any]:
    """Every figure of one subject in one period. Times are in UTC seconds; `offsets_s` gives
    the project's offset at each heart rate reading, so the rhythm is read on the local clock
    the way the movement and grazing modules read theirs."""
    times, bpm = readings.array(HEART_RATE)
    keep = plausible(bpm)
    dropped = int(bpm.size - np.count_nonzero(keep))
    times, bpm = times[keep], bpm[keep]
    offsets_s = offsets_s[keep] if offsets_s.size == keep.size else offsets_s

    success_times, success = readings.array(SUCCESS)
    seen = coverage(
        success_times,
        success.astype(bool),
        (period.time_to - period.time_from).total_seconds(),
        reporting_interval_s,
    )

    figures: dict[str, Any] = {
        "coverage": seen.as_dict(),
        "dropped_implausible": dropped,
    }
    rate = spread(bpm)
    if rate:
        figures["heart_rate"] = rate.as_dict()
    hours = local_hours(times, offsets_s) if times.size else np.array([], dtype=int)
    if times.size:
        figures["by_hour"] = [
            {"hour": hour, "median": round(median, 1), "n": n}
            for hour, median, n in hour_profile(hours, bpm)
        ]
        rest = resting_rate(
            hours,
            bpm,
            (params.quiet_from_hour, params.quiet_to_hour),
            params.resting_quantile,
        )
        if rest:
            figures["resting_heart_rate"] = round(rest[0], 1)
            figures["resting_readings"] = rest[1]
    hrv = spread(readings.array(HRV)[1])
    if hrv:
        figures["hrv"] = hrv.as_dict()
    tag_temperature = readings.array(TAG_TEMPERATURE)[1]
    tag = spread(tag_temperature)
    if tag:
        figures["tag_temperature"] = tag.as_dict()
    collar = readings.array(COLLAR_TEMPERATURE)[1]
    difference = temperature_disagreement(tag_temperature, collar, TEMPERATURE_GAP_C)
    if difference is not None:
        figures["temperature_difference"] = round(difference, 2)
    return figures


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
    charts: list[Chart] = []
    rhythm: list[dict[str, Any]] = []
    for subject in subjects:
        figures = per_subject.get((subject.id, "main"))
        if figures is None:
            continue
        summary["subjects"][str(subject.id)] = figures
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
                (figures.get("tag_temperature") or {}).get("median"),
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
        for point in figures.get("by_hour", []):
            rhythm.append(
                {"subject": str(subject.id), "hour": point["hour"], "value": point["median"]}
            )
    if rhythm:
        charts.append(
            Chart(
                key="rhythm",
                kind="line",
                unit="bpm",
                series=[
                    {
                        "key": str(subject.id),
                        "name": subject.name,
                        "points": [
                            [point["hour"], point["value"]]
                            for point in rhythm
                            if point["subject"] == str(subject.id)
                        ],
                    }
                    for subject in subjects
                    if any(p["subject"] == str(subject.id) for p in rhythm)
                ],
            )
        )
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
                "Median tag temperature (C)",
                "Readings",
            ],
            rows=rows,
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
    comparison = {
        str(subject.id): per_subject[(subject.id, "comparison")]
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
            sources=["measurements (cardiac tag, port 15)", "device_settings"],
        ),
    )


def _settings(params: CardiacParameters) -> dict[str, Any]:
    """The numbers behind the figures, so a reader never has to guess what "resting" meant."""
    return {
        "quiet_hours": [params.quiet_from_hour, params.quiet_to_hour],
        "resting_quantile": params.resting_quantile,
        "minimum_readings": MIN_READINGS,
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
                times = readings.array(HEART_RATE)[0]
                offsets = zone_offsets(times, zone)
                figures = subject_figures(
                    readings, period, offsets, params, intervals.get(subject.id)
                )
                per_subject[(subject.id, period.key)] = figures
                if period.key == "main":
                    warnings.extend(subject_warnings(subject, figures, period))
                done += 1

        await ctx.progress(95, "writing the result")
        excluded = sum(int(f.get("dropped_implausible", 0)) for f in per_subject.values())
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
    "subject_figures",
    "subject_warnings",
]
