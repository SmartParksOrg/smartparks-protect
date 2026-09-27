"""Vehicle use (phase 39, decisions D301, D303 and D304; docs/VEHICLE_PLAN.md section 5): what
the vehicles did, per vehicle and per day. Trips with their distance, duration, mean and top
speed and where they started and ended, distance and driving hours per day, the speeding
episodes the reported speed shows, the time paused inside trips, and a map of the trips.
Everything comes from the positions and the speed a device reports with its fix; nothing new
is collected. Subjects are entities of the Vehicles type and its sub-types; the check refuses
anything else before a run is queued."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
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
    moving_steps,
    segment_trips,
    speeding_episodes,
)
from shared.analysis.quality import quality_report
from shared.geodesy import haversine_m
from shared.models import Entity, EntityType, Project

METHOD_VERSION = "vehicle_use/1"
#: The catalogue key of the type whose entities (and sub-types) are vehicles.
VEHICLE_TYPE_KEY = "vehicle"
KMH = 3.6
#: Fixed bins in km/h, so every vehicle shares one axis.
SPEED_EDGES_KMH = [0, 10, 20, 30, 40, 50, 60, 70, 80, 100, 120, np.inf]
SPEED_LABELS = ["<10", "10", "20", "30", "40", "50", "60", "70", "80", "100", ">120"]
FEW_FIXES = 10
#: Trips and speeding rows a run keeps per subject; the rest is counted.
MAX_TRIP_ROWS = 500

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
    #: Standing still this long ends a trip; a shorter stop is a pause inside it.
    stop_minutes: float = Field(default=10, ge=1, le=720)
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
    speed_hist: list[list[Any]] = field(default_factory=list)
    hour_km: list[list[Any]] = field(default_factory=list)
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
) -> SubjectResult:
    """The figures of one vehicle in one period from a trajectory already filtered and
    folded; pure apart from the arrays it reads."""
    gap_s = params.gap_hours * 3600
    s = steps(track, gap_s)
    window_s = (period.time_to - period.time_from).total_seconds()
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

    trips = segment_trips(
        track, s, moving_mps=params.moving_kmh / KMH, stop_s=params.stop_minutes * 60
    )
    moving = moving_steps(track, s, params.moving_kmh / KMH)
    zone = ZoneInfo(tz)
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
        line = _line(track, trip.start_index, trip.end_index)
        if len(line) >= 2:
            result.geometries.append(
                Geometry(
                    kind="trip",
                    subject_id=subject.id,
                    label=(
                        f"{subject.name}: trip {k}, {trip.distance_m / 1000:.1f} km, "
                        f"top {top_kmh:.0f} km/h"
                    ),
                    level=round(min(trip.top_mps * KMH / params.limit_kmh, 2.0), 3),
                    geojson={"type": "LineString", "coordinates": line},
                    properties={
                        "period": period.key,
                        "start": _iso(trip.start_s),
                        "end": _iso(trip.end_s),
                        "distance_km": round(trip.distance_m / 1000, 3),
                        "duration_min": round(trip.duration_s / 60, 1),
                        "top_kmh": top_kmh,
                        "from": start_place,
                        "to": end_place,
                    },
                )
            )

    # per local day: trips that started, distance of the moving steps that started that day,
    # the driving time of those steps, and the first and last movement
    per_day: dict[Any, dict[str, float]] = {}
    per_hour = [0.0] * 24
    for i in np.where(moving)[0]:
        day = days[i]
        row = per_day.setdefault(day, {"km": 0.0, "h": 0.0, "first": np.inf, "last": -np.inf})
        row["km"] += float(s.dist_m[i]) / 1000
        row["h"] += float(s.dt_s[i]) / 3600
        row["first"] = min(row["first"], float(track.times[i]))
        row["last"] = max(row["last"], float(track.times[i + 1]))
        hour = datetime.fromtimestamp(float(track.times[i]), tz=UTC).astimezone(zone).hour
        per_hour[hour] += float(s.dist_m[i]) / 1000
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
    result.daily_km = [
        [_ms(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()), round(row["km"], 3)]
        for d, row in sorted(per_day.items())
    ]
    result.hour_km = [[str(h), round(v, 3)] for h, v in enumerate(per_hour)]

    # the speed histogram: the reported speeds while moving, else the step speeds
    reported = track.speed_mps[np.isfinite(track.speed_mps)]
    reported = reported[reported > params.moving_kmh / KMH]
    speeds_kmh = (reported if reported.size else s.speed_mps[moving & (s.dt_s > 0)]) * KMH
    if speeds_kmh.size:
        hist, _ = np.histogram(speeds_kmh, bins=SPEED_EDGES_KMH)
        result.speed_hist = [[SPEED_LABELS[i], int(hist[i])] for i in range(len(SPEED_LABELS))]

    episodes = speeding_episodes(track, params.limit_kmh / KMH) if with_speed else []
    _speeding_figures(result, episodes, track, subject, period, sites, params)
    result.figures = figures
    return result


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
) -> ResultDocument:
    """The result document: the summary per subject and period, the summary table with a
    mean row for several vehicles, the trips, days and speeding tables, the charts."""
    geometries = geometries or {}
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
    trips.sort(key=lambda row: -float(row[7]))
    speeding.sort(key=lambda row: -float(row[5]))
    tables = [
        Table(key="summary", columns=["subject", "period", *METRICS], rows=rows),
        Table(
            key="trips",
            columns=[
                "subject",
                "period",
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

    def series(pick: Any) -> list[dict[str, Any]]:
        out = []
        for period in periods:
            for subject in subjects:
                r = results.get((period.key, subject.id))
                if r is None:
                    continue
                out.append({"subject": str(subject.id), "period": period.key, "data": pick(r)})
        return out

    charts = [
        Chart(key="daily_distance", kind="bar", unit="km", series=series(lambda r: r.daily_km)),
        Chart(
            key="speed_histogram",
            kind="bar",
            unit="fixes",
            series=series(lambda r: r.speed_hist),
        ),
        Chart(key="hour_profile", kind="bar", unit="km", series=series(lambda r: r.hour_km)),
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
            ],
        ),
    )


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
        )
        return RunResult(document=document, geometries=geometries)
