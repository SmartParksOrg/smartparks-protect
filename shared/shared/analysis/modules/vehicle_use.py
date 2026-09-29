"""Vehicle use (phase 39, decisions D301, D303 and D304; docs/VEHICLE_PLAN.md section 5): what
the vehicles did, per vehicle and per day. Trips with their distance, duration, mean and top
speed and where they started and ended, distance and driving hours per day, the speeding
episodes the reported speed shows, the time paused inside trips, and a map of the trips.
Everything comes from the positions and the speed a device reports with its fix; nothing new
is collected. Subjects are entities of the Vehicles type and its sub-types; the check refuses
anything else before a run is queued.

Phase 40 (decisions D306 to D308): the path is coloured by the speed itself in bands that
widen, a stretch over the limit is marked apart, and the charts are the ones a vehicle manager
reads: the speed over the period with the known limits as lines, distance and driving time
per day, use and speed by the hour of the day, the time per speed band and speeding per day."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.analysis.base import (
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
from shared.analysis.limits import MAX_FIXES_PER_SUBJECT
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.timeagg import local_days
from shared.analysis.primitives.trajectory import (
    Trajectory,
    exclude_impossible,
    fold_stops,
    load_trajectory,
    steps,
)
from shared.analysis.primitives.trips import (
    Speeding,
    Trip,
    moving_steps,
    segment_trips,
    speeding_episodes,
)
from shared.analysis.quality import quality_report
from shared.geodesy import haversine_m
from shared.models import Entity, EntityType, Project, Rule, RuleVersion

METHOD_VERSION = "vehicle_use/2"
#: The catalogue key of the type whose entities (and sub-types) are vehicles.
VEHICLE_TYPE_KEY = "vehicle"
KMH = 3.6
#: The speed bands in km/h, the same for the map, its legend and the chart (decision D306).
#: They widen as the speed rises, roughly doubling: a vehicle in a park spends its day under
#: 40 km/h and one on a highway above 80, and even steps gave the first one colour and the
#: second another (Tim, 2026-09-29: almost everything was red above 50 km/h). The last edge is
#: 120 and not 160 because that is where a highway's limit sits.
SPEED_BAND_EDGES_KMH = (10.0, 20.0, 40.0, 80.0, 120.0)
#: What each band starts at, as the legend shows it under its colour.
SPEED_BAND_LABELS = ["<10", "10", "20", "40", "80", ">120"]
#: Bucket widths of the speed over time, seconds; the finest that fits the points is taken.
SPEED_BUCKETS_S = (60, 300, 600, 900, 1800, 3600, 3 * 3600, 6 * 3600, 86_400)
#: Points of the speed over time in one document, shared by its vehicles and periods.
SPEED_POINTS = 4000
#: And per series, however few the vehicles.
SPEED_POINTS_PER_SERIES = 1000
#: Limit lines a chart carries: the run's and the lowest of the project's rules.
MAX_LIMITS = 6
FEW_FIXES = 10
#: Below this share of fixes with a reported speed the run says the speeds are mostly means.
FEW_SPEEDS_SHARE = 0.5
#: Trips and speeding rows a run keeps per subject; the rest is counted.
MAX_TRIP_ROWS = 500
#: Segment geometries per subject before a trip is drawn as one line in its top speed's band.
SEGMENT_BUDGET = 1500

#: The summary's keys in the order the table shows them.
METRICS: list[str] = [
    "fixes",
    "fixes_with_speed_share",
    "days_active",
    "trips",
    "distance_km",
    "driving_h",
    "mean_speed_kmh",
    "top_speed_kmh",
    "longest_trip_km",
    "paused_min",
    "speeding_episodes",
    "speeding_minutes",
    "speeding_top_kmh",
    "median_interval_min",
    "missing_share",
    "excluded_fixes",
    "folded_fixes",
]


class VehicleParameters(CommonParameters):
    """The options of the design's section 5 with their defaults."""

    #: Above this a fix's reported speed is movement even before the next fix arrives.
    moving_kmh: float = Field(default=5, gt=0, le=60)
    #: Standing still this long ends a trip; a shorter halt (fuel, a gate, a look) is a pause
    #: inside it. Twenty minutes, since ten cut a drive to Zeeland in two at a fuel stop (Tim,
    #: 2026-09-27).
    stop_minutes: float = Field(default=20, ge=1, le=720)
    #: A trip shorter than this is not a trip: moving the car in the yard, a fix that wandered.
    min_trip_m: float = Field(default=300, ge=0, le=50_000)
    #: The stop rule (decision D303): fixes within this radius of where a stop began are one
    #: place, so a parked vehicle's GNSS drift is neither distance nor a trip.
    stop_radius_m: float = Field(default=15, ge=0, le=500)
    #: A trip that starts or ends within this distance of a site is named after it.
    site_radius_m: float = Field(default=200, ge=10, le=5000)
    #: The speed limit a speeding episode is judged against.
    limit_kmh: float = Field(default=60, gt=0, le=300)
    #: A fix that would need more than this from the fix before it is left out (250 km/h).
    max_speed_mps: float = Field(default=70, gt=0, le=200)


@dataclass(slots=True)
class Site:
    name: str
    lat: float
    lon: float


@dataclass(slots=True)
class SubjectResult:
    """One vehicle in one period: the summary, the rows, the chart series, the geometries."""

    summary: dict[str, float | str | None]
    trips: list[list[Any]] = field(default_factory=list)
    days: list[list[Any]] = field(default_factory=list)
    speeding: list[list[Any]] = field(default_factory=list)
    daily_km: list[list[float]] = field(default_factory=list)
    daily_h: list[list[float]] = field(default_factory=list)
    daily_speeding_min: list[list[float]] = field(default_factory=list)
    speed_series: list[list[float | None]] = field(default_factory=list)
    hour_h: list[list[Any]] = field(default_factory=list)
    hour_typical_kmh: list[list[Any]] = field(default_factory=list)
    hour_top_kmh: list[list[Any]] = field(default_factory=list)
    band_min: list[list[Any]] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    geometries: list[Geometry] = field(default_factory=list)
    figures: dict[str, float] = field(default_factory=dict)


def _ms(seconds: float) -> float:
    return float(seconds) * 1000


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(float(seconds), tz=UTC).isoformat()


def _place(lat: float, lon: float, sites: list[Site], radius_m: float) -> str:
    """The nearest site within the radius, else the coordinates."""
    best: tuple[float, str] | None = None
    for site in sites:
        d = haversine_m(lat, lon, site.lat, site.lon)
        if d <= radius_m and (best is None or d < best[0]):
            best = (d, site.name)
    return best[1] if best else f"{lat:.4f}, {lon:.4f}"


@dataclass(slots=True)
class Limit:
    """A speed limit the charts draw as a line: the run's own, or one a rule of the project
    judges by (decision D307). A rule's limit inside an area holds only there."""

    value: float
    label: str
    source: str  # "run" or "rule"
    zone: bool = False

    def document(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "label": self.label,
            "source": self.source,
            "zone": self.zone,
        }


def speed_class(kmh: float) -> int:
    """The band of a speed in km/h, 0 to 5 (`SPEED_BAND_EDGES_KMH`)."""
    for index, edge in enumerate(SPEED_BAND_EDGES_KMH):
        if kmh < edge:
            return index
    return len(SPEED_BAND_EDGES_KMH)


def speed_bucket_s(period_s: float, series: int) -> int:
    """The width of a bucket of the speed over time: the finest of the ladder that keeps a
    series within its share of the document's points."""
    points = max(100, min(SPEED_POINTS_PER_SERIES, SPEED_POINTS // max(1, series)))
    for width in SPEED_BUCKETS_S:
        if period_s / width <= points:
            return width
    return SPEED_BUCKETS_S[-1]


def _step_kmh(track: Trajectory, s: Any, i: int) -> float:
    """The speed of step i in km/h: the faster of the speeds its two fixes reported (a step
    that leaves a parked fix reporting zero is as fast as its arrival says), else the mean over
    the step."""
    ends = [float(v) for v in (track.speed_mps[i], track.speed_mps[i + 1]) if np.isfinite(v)]
    # rounded, so a speed that came in as 60 km/h is 60 again and not a hair over the limit
    if ends:
        return round(max(ends) * KMH, 3)
    return round(float(s.speed_mps[i]) * KMH, 3) if np.isfinite(s.speed_mps[i]) else 0.0


def trip_segments(
    track: Trajectory, s: Any, moving: NDArray[np.bool_], trip: Trip, limit_kmh: float
) -> list[tuple[int, int, float, int, bool]]:
    """The trip cut into runs of one speed band on one side of the limit:
    `(start_index, end_index, top_kmh, band, over)` per run, consecutive moving steps alike in
    both joined, still steps folded into the run around them. The limit cuts as well as the
    band, so the stretch drawn as over the limit is the stretch that was."""
    runs: list[tuple[int, int, float, int, bool]] = []
    current: list[Any] | None = None
    for i in range(trip.start_index, trip.end_index):
        if not moving[i]:
            if current is not None:
                current[1] = i + 1
            continue
        kmh = _step_kmh(track, s, i)
        klass = speed_class(kmh)
        over = kmh > limit_kmh
        if current is not None and current[3] == klass and current[4] == over:
            current[1] = i + 1
            current[2] = max(current[2], kmh)
        else:
            if current is not None:
                runs.append((current[0], current[1], current[2], current[3], current[4]))
            current = [i, i + 1, kmh, klass, over]
    if current is not None:
        runs.append((current[0], current[1], current[2], current[3], current[4]))
    return runs


def speed_over_time(
    track: Trajectory,
    s: Any,
    moving: NDArray[np.bool_],
    period: Period,
    bucket_s: int,
) -> list[list[float | None]]:
    """The fastest speed per bucket over the whole period, `[epoch ms, km/h]`. A bucket with
    fixes takes the fastest of them (the reported speed, else the speed of the moving step the
    fix starts or ends); a bucket between two fixes takes the step over it, zero when the
    vehicle stood; a bucket the record is silent over (a gap, before the first fix, after the
    last) is None, which breaks the line, since a silence is not a standstill."""
    n = len(track)
    start = period.time_from.timestamp()
    count = max(1, int(np.ceil((period.time_to.timestamp() - start) / bucket_s)))
    if n == 0:
        return [[_ms(start + b * bucket_s), None] for b in range(count)]
    fix_kmh = np.where(np.isfinite(track.speed_mps), track.speed_mps * KMH, 0.0)
    step_kmh = np.array([_step_kmh(track, s, i) if moving[i] else 0.0 for i in range(len(s))])
    unreported = ~np.isfinite(track.speed_mps)
    if len(s):
        # a fix without a reported speed is as fast as the moving step it ends or starts
        around = np.zeros(n)
        around[:-1] = step_kmh
        around[1:] = np.maximum(around[1:], step_kmh)
        fix_kmh = np.where(unreported, around, fix_kmh)
    top = np.full(count, -1.0)
    index = np.clip(((track.times - start) // bucket_s).astype(int), 0, count - 1)
    np.maximum.at(top, index, fix_kmh)
    out: list[list[float | None]] = []
    for b in range(count):
        at = start + b * bucket_s
        if top[b] >= 0:
            out.append([_ms(at), round(float(top[b]), 1)])
            continue
        # no fix in the bucket: the step that spans it says what happened meanwhile
        i = int(np.searchsorted(track.times, at, side="right")) - 1
        if i < 0 or i >= len(s) or bool(s.gap[i]):
            out.append([_ms(at), None])
        else:
            out.append([_ms(at), round(float(step_kmh[i]), 1)])
    return out


def days_of(period: Period, zone: ZoneInfo) -> list[date]:
    """Every local day the period touches, so the vehicles of a run share one axis and a day
    nothing moved on reads as zero rather than missing."""
    first = period.time_from.astimezone(zone).date()
    # the period ends just before `time_to`: a run to midnight does not touch the next day
    last = (period.time_to - timedelta(seconds=1)).astimezone(zone).date()
    return [first + timedelta(days=d) for d in range(max(0, (last - first).days) + 1)]


def _line(track: Trajectory, start: int, end: int) -> list[list[float]]:
    """The distinct consecutive points of a stretch of the folded track, [lon, lat]."""
    out: list[list[float]] = []
    for i in range(start, end + 1):
        point = [round(float(track.lon[i]), 6), round(float(track.lat[i]), 6)]
        if not out or out[-1] != point:
            out.append(point)
    return out


def analyse_vehicle(
    track: Trajectory,
    params: VehicleParameters,
    period: Period,
    tz: str,
    sites: list[Site],
    subject: Subject,
    *,
    excluded: int = 0,
    folded: int = 0,
    bucket_s: int | None = None,
) -> SubjectResult:
    """The figures of one vehicle in one period from a trajectory already filtered and
    folded; pure apart from the arrays it reads. `bucket_s` is the width of a bucket of the
    speed over time, which the run sets for all its vehicles together."""
    gap_s = params.gap_hours * 3600
    s = steps(track, gap_s)
    window_s = (period.time_to - period.time_from).total_seconds()
    zone = ZoneInfo(tz)
    all_days = days_of(period, zone)
    width_s = bucket_s or speed_bucket_s(window_s, 1)
    n = len(track)
    summary: dict[str, float | str | None] = dict.fromkeys(METRICS)
    summary["fixes"] = float(n)
    summary["excluded_fixes"] = float(excluded)
    summary["folded_fixes"] = float(folded)
    warnings, figures = quality_report(
        track,
        s,
        subject_id=subject.id,
        window_seconds=window_s,
        excluded=excluded,
        few_fixes=FEW_FIXES,
    )
    if "missing_share" in figures:
        summary["missing_share"] = figures["missing_share"]
    if "median_interval_s" in figures:
        summary["median_interval_min"] = round(figures["median_interval_s"] / 60, 1)
    result = SubjectResult(summary, warnings=warnings, figures=figures)
    if n == 0:
        # the charts keep their axes: a vehicle that reported nothing is a flat line of days
        empty = np.zeros(0, dtype=np.bool_)
        result.speed_series = speed_over_time(track, s, empty, period, width_s)
        _daily_series(result, all_days, {}, {})
        return result

    with_speed = int(np.isfinite(track.speed_mps).sum())
    summary["fixes_with_speed_share"] = round(with_speed / n, 3)
    if with_speed == 0:
        warnings.append(
            Warning(
                code="no_reported_speed",
                level="notice",
                subject_id=subject.id,
                text=(
                    f"No fix of {subject.name} carries a reported speed, so the speeds are the "
                    "means over a step and no speeding is judged. An OpenCollar reports a speed "
                    "with active tracking on."
                ),
            )
        )
    elif with_speed < n * FEW_SPEEDS_SHARE:
        warnings.append(
            Warning(
                code="few_reported_speeds",
                level="notice",
                subject_id=subject.id,
                text=(
                    f"Only {round(100 * with_speed / n)} percent of the fixes of {subject.name} "
                    "carry a reported speed; the rest of its speeds are means over a step, and "
                    "speeding is judged where a speed was reported alone."
                ),
            )
        )

    trips = [
        trip
        for trip in segment_trips(
            track, s, moving_mps=params.moving_kmh / KMH, stop_s=params.stop_minutes * 60
        )
        if trip.distance_m >= params.min_trip_m
    ]
    moving = moving_steps(track, s, params.moving_kmh / KMH)
    days = local_days(track.times, tz)

    distance_m = sum(t.distance_m for t in trips)
    driving_s = sum(t.duration_s - t.paused_s for t in trips)
    summary["trips"] = float(len(trips))
    summary["distance_km"] = round(distance_m / 1000, 3)
    summary["driving_h"] = round(driving_s / 3600, 2)
    summary["mean_speed_kmh"] = round(distance_m / driving_s * KMH, 1) if driving_s > 0 else None
    tops = [t.top_mps for t in trips]
    summary["top_speed_kmh"] = round(max(tops) * KMH, 1) if tops else None
    summary["longest_trip_km"] = (
        round(max(t.distance_m for t in trips) / 1000, 3) if trips else None
    )
    summary["paused_min"] = round(sum(t.paused_s for t in trips) / 60, 1)
    if any(t.cut_by_gap for t in trips):
        cut = sum(1 for t in trips if t.cut_by_gap)
        warnings.append(
            Warning(
                code="trips_cut_by_gaps",
                level="notice",
                subject_id=subject.id,
                text=(
                    f"{cut} of {len(trips)} trips of {subject.name} end where the record fell "
                    "silent, not where the vehicle stopped; a trip cut by a gap may be two."
                ),
            )
        )

    for k, trip in enumerate(trips[:MAX_TRIP_ROWS], start=1):
        start_place = _place(
            float(track.lat[trip.start_index]),
            float(track.lon[trip.start_index]),
            sites,
            params.site_radius_m,
        )
        end_place = _place(
            float(track.lat[trip.end_index]),
            float(track.lon[trip.end_index]),
            sites,
            params.site_radius_m,
        )
        top_kmh = round(trip.top_mps * KMH, 1)
        result.trips.append(
            [
                subject.name,
                period.key,
                k,
                _iso(trip.start_s),
                _iso(trip.end_s),
                round(trip.duration_s / 60, 1),
                round(trip.distance_m / 1000, 3),
                round(trip.mean_mps * KMH, 1),
                top_kmh,
                "reported" if trip.top_reported_mps is not None else "between fixes",
                start_place,
                end_place,
                trip.fixes,
                round(trip.paused_s / 60, 1),
                "gap" if trip.cut_by_gap else "stop",
            ]
        )
        about = {
            "period": period.key,
            "trip": k,
            "start": _iso(trip.start_s),
            "end": _iso(trip.end_s),
            "distance_km": round(trip.distance_m / 1000, 3),
            "duration_min": round(trip.duration_s / 60, 1),
            "top_kmh": top_kmh,
            "limit_kmh": params.limit_kmh,
            "from": start_place,
            "to": end_place,
        }
        title = f"{subject.name}: trip {k}, {trip.distance_m / 1000:.1f} km, top {top_kmh:.0f} km/h"
        # the path in runs of one speed band, and of one side of the limit; past the budget
        # a trip is one line in the band of its top speed
        runs = (
            trip_segments(track, s, moving, trip, params.limit_kmh)
            if len(result.geometries) < SEGMENT_BUDGET
            else [
                (
                    trip.start_index,
                    trip.end_index,
                    top_kmh,
                    speed_class(top_kmh),
                    top_kmh > params.limit_kmh,
                )
            ]
        )
        for start_i, end_i, run_kmh, klass, over in runs:
            line = _line(track, start_i, end_i)
            if len(line) < 2:
                continue
            result.geometries.append(
                Geometry(
                    kind="trip_segment",
                    subject_id=subject.id,
                    label=title,
                    level=round(min(run_kmh / params.limit_kmh, 2.0), 3),
                    geojson={"type": "LineString", "coordinates": line},
                    properties={
                        **about,
                        "speed_kmh": round(run_kmh, 1),
                        "speed_class": klass,
                        "over_limit": over,
                    },
                )
            )
        # one numbered marker where the trip began and one where it ended, one layer
        # (Tim, 2026-09-27: two layers for the two ends of one trip made no sense)
        for role, index, place in (
            ("start", trip.start_index, start_place),
            ("end", trip.end_index, end_place),
        ):
            result.geometries.append(
                Geometry(
                    kind="trip_marker",
                    subject_id=subject.id,
                    label=f"{title}; {'from' if role == 'start' else 'to'} {place}",
                    level=None,
                    geojson={
                        "type": "Point",
                        "coordinates": [
                            round(float(track.lon[index]), 6),
                            round(float(track.lat[index]), 6),
                        ],
                    },
                    properties={**about, "short": str(k), "role": role},
                )
            )

    # per local day: trips that started, distance of the moving steps that started that day,
    # the driving time of those steps, and the first and last movement; per hour of the day
    # the driving time and the speeds driven; per speed band the minutes driven in it
    per_day: dict[Any, dict[str, float]] = {}
    hour_h = [0.0] * 24
    hour_speeds: list[list[float]] = [[] for _ in range(24)]
    band_min = [0.0] * len(SPEED_BAND_LABELS)
    for i in np.where(moving)[0]:
        day = days[i]
        row = per_day.setdefault(day, {"km": 0.0, "h": 0.0, "first": np.inf, "last": -np.inf})
        row["km"] += float(s.dist_m[i]) / 1000
        row["h"] += float(s.dt_s[i]) / 3600
        row["first"] = min(row["first"], float(track.times[i]))
        row["last"] = max(row["last"], float(track.times[i + 1]))
        hour = datetime.fromtimestamp(float(track.times[i]), tz=UTC).astimezone(zone).hour
        kmh = _step_kmh(track, s, int(i))
        hour_h[hour] += float(s.dt_s[i]) / 3600
        hour_speeds[hour].append(kmh)
        band_min[speed_class(kmh)] += float(s.dt_s[i]) / 60
    trips_by_day: dict[Any, int] = {}
    for trip in trips:
        day = days[trip.start_index]
        trips_by_day[day] = trips_by_day.get(day, 0) + 1
    summary["days_active"] = float(len(per_day))

    def clock(seconds: float) -> str:
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone(zone).strftime("%H:%M")

    for day, row in sorted(per_day.items()):
        result.days.append(
            [
                subject.name,
                period.key,
                day.isoformat(),
                trips_by_day.get(day, 0),
                round(row["km"], 3),
                round(row["h"], 2),
                clock(row["first"]),
                clock(row["last"]),
            ]
        )
    result.hour_h = [[str(h), round(v, 2)] for h, v in enumerate(hour_h)]
    # the speed a vehicle usually drives at that hour and the fastest it drove; an hour it
    # never drove in has neither
    result.hour_typical_kmh = [
        [str(h), round(float(np.median(v)), 1) if v else None] for h, v in enumerate(hour_speeds)
    ]
    result.hour_top_kmh = [
        [str(h), round(float(max(v)), 1) if v else None] for h, v in enumerate(hour_speeds)
    ]
    result.band_min = [[SPEED_BAND_LABELS[i], round(v, 1)] for i, v in enumerate(band_min)]
    result.speed_series = speed_over_time(track, s, moving, period, width_s)

    episodes = speeding_episodes(track, params.limit_kmh / KMH) if with_speed else []
    _speeding_figures(result, episodes, track, subject, period, sites, params)
    # an episode counts on the day it began
    speeding_by_day: dict[Any, float] = {}
    for episode in episodes:
        day = days[episode.start_index]
        speeding_by_day[day] = speeding_by_day.get(day, 0.0) + episode.duration_s / 60
    _daily_series(result, all_days, per_day, speeding_by_day)
    result.figures = figures
    return result


def _daily_series(
    result: SubjectResult,
    all_days: list[date],
    per_day: dict[Any, dict[str, float]],
    speeding_by_day: dict[Any, float],
) -> None:
    """The three series per day over every day of the period, a day without movement as zero,
    so the bars of several vehicles stand on the same days."""

    def at(day: date) -> float:
        return _ms(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())

    result.daily_km = [[at(d), round(per_day.get(d, {}).get("km", 0.0), 3)] for d in all_days]
    result.daily_h = [[at(d), round(per_day.get(d, {}).get("h", 0.0), 2)] for d in all_days]
    result.daily_speeding_min = [[at(d), round(speeding_by_day.get(d, 0.0), 1)] for d in all_days]


def _speeding_figures(
    result: SubjectResult,
    episodes: list[Speeding],
    track: Trajectory,
    subject: Subject,
    period: Period,
    sites: list[Site],
    params: VehicleParameters,
) -> None:
    summary = result.summary
    summary["speeding_episodes"] = float(len(episodes))
    summary["speeding_minutes"] = round(sum(e.duration_s for e in episodes) / 60, 1)
    summary["speeding_top_kmh"] = (
        round(max(e.top_mps for e in episodes) * KMH, 1) if episodes else None
    )
    for episode in episodes[:MAX_TRIP_ROWS]:
        lat = float(track.lat[episode.top_index])
        lon = float(track.lon[episode.top_index])
        top_kmh = round(episode.top_mps * KMH, 1)
        result.speeding.append(
            [
                subject.name,
                period.key,
                _iso(episode.start_s),
                _iso(episode.end_s),
                round(episode.duration_s / 60, 1),
                top_kmh,
                _place(lat, lon, sites, params.site_radius_m),
            ]
        )
        result.geometries.append(
            Geometry(
                kind="speeding",
                subject_id=subject.id,
                label=f"{subject.name}: {top_kmh:.0f} km/h",
                level=round(min(episode.top_mps * KMH / params.limit_kmh, 2.0), 3),
                geojson={"type": "Point", "coordinates": [lon, lat]},
                properties={
                    "period": period.key,
                    "start": _iso(episode.start_s),
                    "end": _iso(episode.end_s),
                    "top_kmh": top_kmh,
                    "limit_kmh": params.limit_kmh,
                    "short": f"{top_kmh:.0f}",
                },
            )
        )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def build_document(
    subjects: list[Subject],
    periods: list[Period],
    results: dict[tuple[str, uuid.UUID], SubjectResult],
    params: VehicleParameters,
    *,
    input_count: int,
    excluded_count: int,
    geometries: dict[str, int] | None = None,
    limits: list[Limit] | None = None,
) -> ResultDocument:
    """The result document: the summary per subject and period, the summary table with a
    mean row for several vehicles, the trips, days and speeding tables, the charts. `limits`
    are the limits the project's rules judge by; the run's own always leads them."""
    geometries = geometries or {}
    lines = [
        limit.document()
        for limit in merge_limits(
            [Limit(value=params.limit_kmh, label="run_limit", source="run"), *(limits or [])]
        )
    ]
    summary: dict[str, dict[str, dict[str, float | str | None]]] = {}
    warnings: list[Warning] = []
    rows: list[list[Any]] = []
    trips: list[list[Any]] = []
    days: list[list[Any]] = []
    speeding: list[list[Any]] = []
    for period in periods:
        summary[period.key] = {}
        for subject in subjects:
            r = results.get((period.key, subject.id))
            if r is None:
                continue
            summary[period.key][str(subject.id)] = r.summary
            rows.append([subject.name, period.key] + [r.summary[k] for k in METRICS])
            trips.extend(r.trips)
            days.extend(r.days)
            speeding.extend(r.speeding)
            warnings.extend(r.warnings)
    if len(subjects) > 1:
        for period in periods:
            values = [
                results[(period.key, s.id)].summary
                for s in subjects
                if (period.key, s.id) in results
            ]
            if len(values) < 2:
                continue
            mean_row: list[Any] = ["mean", period.key]
            for key in METRICS:
                column = [float(value) for v in values if isinstance(value := v[key], int | float)]
                mean_row.append(_round(sum(column) / len(column)) if len(column) >= 2 else None)
            rows.append(mean_row)
    # the trips worst first: the fastest at the top, as the design asks
    trips.sort(key=lambda row: -float(row[8]))
    speeding.sort(key=lambda row: -float(row[5]))
    tables = [
        Table(key="summary", columns=["subject", "period", *METRICS], rows=rows),
        Table(
            key="trips",
            columns=[
                "subject",
                "period",
                "trip",
                "start",
                "end",
                "duration_min",
                "distance_km",
                "mean_kmh",
                "top_kmh",
                "speed_source",
                "from",
                "to",
                "fixes",
                "paused_min",
                "ended_by",
            ],
            rows=trips,
        ),
        Table(
            key="days",
            columns=[
                "subject",
                "period",
                "date",
                "trips",
                "distance_km",
                "driving_h",
                "first_movement",
                "last_movement",
            ],
            rows=days,
        ),
        Table(
            key="speeding",
            columns=["subject", "period", "start", "end", "duration_min", "top_kmh", "where"],
            rows=speeding,
        ),
    ]

    def series(pick: Any, part: str | None = None) -> list[dict[str, Any]]:
        out = []
        for period in periods:
            for subject in subjects:
                r = results.get((period.key, subject.id))
                if r is None:
                    continue
                row = {"subject": str(subject.id), "period": period.key, "data": pick(r)}
                if part:
                    row["part"] = part
                out.append(row)
        return out

    # what a vehicle manager reads, in the order of the questions: how fast and against which
    # limit, how far and how long per day, when in the day, at which speeds, how often too fast
    charts = [
        Chart(
            key="speed_over_time",
            kind="line",
            unit="km/h",
            series=series(lambda r: r.speed_series),
            limits=lines,
            breaks=True,
        ),
        Chart(key="daily_distance", kind="stacked", unit="km", series=series(lambda r: r.daily_km)),
        Chart(key="daily_driving", kind="stacked", unit="h", series=series(lambda r: r.daily_h)),
        Chart(key="hour_driving", kind="stacked", unit="h", series=series(lambda r: r.hour_h)),
        Chart(
            key="hour_speed",
            kind="line",
            unit="km/h",
            series=[
                *series(lambda r: r.hour_typical_kmh, "typical"),
                *series(lambda r: r.hour_top_kmh, "top"),
            ],
            limits=lines,
            breaks=True,
        ),
        Chart(key="speed_bands", kind="bar", unit="min", series=series(lambda r: r.band_min)),
        Chart(
            key="daily_speeding",
            kind="stacked",
            unit="min",
            series=series(lambda r: r.daily_speeding_min),
        ),
    ]
    return ResultDocument(
        module="vehicle_use",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=periods,
        summary=summary,
        tables=tables,
        charts=charts,
        geometries=geometries,
        warnings=warnings,
        provenance=Provenance(
            module="vehicle_use",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=[
                "positions (device fixes, effective time and geometry, valid rows) with the "
                "speed the receiver reported",
                "features of type site, for the names of where a trip started and ended",
                "the enabled rules of the project that judge a speed, for the limit lines",
            ],
        ),
    )


def merge_limits(limits: list[Limit]) -> list[Limit]:
    """One line per value: limits of the same speed share a line and their names, the run's
    first; the lowest `MAX_LIMITS` stay, since a chart with ten lines says nothing."""
    by_value: dict[float, Limit] = {}
    for limit in limits:
        known = by_value.get(limit.value)
        if known is None:
            by_value[limit.value] = Limit(limit.value, limit.label, limit.source, limit.zone)
        elif limit.source == "rule":
            if known.source == "run":
                # the run's limit is one a rule judges by too; the line keeps the run's name
                continue
            known.label = f"{known.label}, {limit.label}"
            known.zone = known.zone and limit.zone
    ordered = sorted(by_value.values(), key=lambda limit: (limit.source != "run", limit.value))
    return ordered[:MAX_LIMITS]


def speed_limits_of(name: str, document: dict[str, Any]) -> list[Limit]:
    """The limits a rule document judges a speed by: every threshold on `speed_kmh` that asks
    for more than a value, anywhere in its conditions. The rule holds inside an area when the
    same document has a spatial condition that says inside."""
    found: list[float] = []
    inside = False

    def walk(node: Any) -> None:
        nonlocal inside
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        if (
            kind == "threshold"
            and node.get("metric") == "speed_kmh"
            and node.get("op") in (">", ">=")
            and isinstance(node.get("value"), int | float)
        ):
            found.append(float(node["value"]))
        if kind == "spatial" and node.get("relation") == "inside":
            inside = True
        for key in ("all", "any", "not"):
            if key in node:
                walk(node[key])

    walk(document.get("conditions"))
    return [Limit(value=v, label=name, source="rule", zone=inside) for v in found if v > 0]


async def load_speed_limits(session: AsyncSession, project_id: uuid.UUID) -> list[Limit]:
    """The limits of the project's enabled rules, each in the version that runs today."""
    rows = (
        await session.execute(
            select(Rule.name, RuleVersion.document)
            .join(
                RuleVersion,
                (RuleVersion.rule_id == Rule.id) & (RuleVersion.version == Rule.current_version),
            )
            .where(Rule.project_id == project_id, Rule.enabled.is_(True))
            .order_by(Rule.name)
            .limit(200)
        )
    ).all()
    limits: list[Limit] = []
    for name, document in rows:
        limits.extend(speed_limits_of(name, document or {}))
    return limits


async def load_sites(session: AsyncSession, project_id: uuid.UUID) -> list[Site]:
    """The project's sites as points: the centroid of each `site` feature."""
    rows = (
        await session.execute(
            text(
                """
                SELECT name, ST_Y(ST_Centroid(geom)) AS lat, ST_X(ST_Centroid(geom)) AS lon
                FROM features
                WHERE project_id = :project_id AND feature_type = 'site'
                ORDER BY name
                """
            ),
            {"project_id": project_id},
        )
    ).all()
    return [Site(name=row.name, lat=float(row.lat), lon=float(row.lon)) for row in rows]


async def non_vehicles(session: AsyncSession, entity_ids: list[uuid.UUID]) -> list[str]:
    """The names of the subjects that are not of the Vehicles type or one of its sub-types."""
    parent = aliased(EntityType)
    rows = (
        await session.execute(
            select(Entity.name, EntityType.key, parent.key)
            .join(EntityType, EntityType.id == Entity.entity_type_id)
            .outerjoin(parent, parent.id == EntityType.parent_id)
            .where(Entity.id.in_(entity_ids))
            .order_by(Entity.name)
        )
    ).all()
    return [
        name
        for name, key, parent_key in rows
        if key != VEHICLE_TYPE_KEY and parent_key != VEHICLE_TYPE_KEY
    ]


class VehicleUseModule:
    key = "vehicle_use"
    label = "Vehicle use"
    version = METHOD_VERSION
    parameters: type[BaseModel] = VehicleParameters

    async def check(
        self, session: AsyncSession, project_id: uuid.UUID, params: BaseModel
    ) -> list[str]:
        """A run reads vehicles: an entity of another type has trips only in name, so it is
        refused before the run is queued rather than reported as a car."""
        assert isinstance(params, VehicleParameters)
        if not params.entity_ids:
            return []
        others = await non_vehicles(session, params.entity_ids)
        if not others:
            return []
        if len(others) == len(params.entity_ids):
            return [
                "No vehicle among the subjects: the module reads entities of the Vehicles type "
                "and its sub-types (a car, a 4x4, a boat)."
            ]
        return [f"{others[0]} is not a vehicle; choose vehicles only for this analysis."]

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, VehicleParameters)
        session = ctx.session
        tz = await session.scalar(select(Project.timezone).where(Project.id == ctx.project_id))
        rows = (
            await session.execute(
                select(Entity.id, Entity.name, EntityType.label)
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(Entity.id.in_(params.entity_ids), Entity.project_id == ctx.project_id)
                .order_by(Entity.name)
            )
        ).all()
        subjects = [Subject(id=r.id, name=r.name, type=r.label) for r in rows]
        periods = [Period(key="main", time_from=params.time_from, time_to=params.time_to)]
        if params.comparison:
            periods.append(
                Period(
                    key="comparison",
                    time_from=params.comparison.time_from,
                    time_to=params.comparison.time_to,
                )
            )
        sites = await load_sites(session, ctx.project_id)
        limits = await load_speed_limits(session, ctx.project_id)
        # one bucket width for the run, from its longest period and the series it draws
        longest_s = max((p.time_to - p.time_from).total_seconds() for p in periods)
        bucket_s = speed_bucket_s(longest_s, len(subjects) * len(periods))
        results: dict[tuple[str, uuid.UUID], SubjectResult] = {}
        geometries: list[Geometry] = []
        input_count = excluded_count = 0
        total = max(1, len(subjects) * len(periods))
        done = 0
        for period in periods:
            for subject in subjects:
                await ctx.progress(int(done * 90 / total), f"{subject.name} ({period.key})")
                track = await load_trajectory(
                    session,
                    subject.id,
                    period.time_from,
                    period.time_to,
                    max_fixes=MAX_FIXES_PER_SUBJECT,
                )
                input_count += len(track) + track.duplicates
                track, dropped = exclude_impossible(track, params.max_speed_mps)
                excluded_count += dropped + track.duplicates
                track, folded = fold_stops(track, params.stop_radius_m)
                r = analyse_vehicle(
                    track,
                    params,
                    period,
                    tz or "UTC",
                    sites,
                    subject,
                    excluded=dropped,
                    folded=folded,
                    bucket_s=bucket_s,
                )
                results[(period.key, subject.id)] = r
                geometries.extend(r.geometries)
                done += 1
        await ctx.progress(95, "document")
        counts: dict[str, int] = {}
        for g in geometries:
            counts[g.kind] = counts.get(g.kind, 0) + 1
        document = build_document(
            subjects,
            periods,
            results,
            params,
            input_count=input_count,
            excluded_count=excluded_count,
            geometries=counts,
            limits=limits,
        )
        return RunResult(document=document, geometries=geometries)
