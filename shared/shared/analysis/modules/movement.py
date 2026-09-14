"""Movement ecology (docs/ANALYTICS_PHASE1_PLAN.md, section 8): what the fixes of the chosen
animals say about how far, how fast and where they moved, per subject and period, with the
comparison table and the quality warnings. The spatial layers (home range, clusters) come from
the primitives of M2 and are attached here when their methods are on."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel, Field
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from shared.analysis.limits import KDE_MAX_CELLS, MAX_FIXES_PER_SUBJECT
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.homerange import isopleths, kde_grid, mcp, reference_bandwidth
from shared.analysis.primitives.spatial import (
    LocalGrid,
    clusters_sql,
    hectares,
    hotspots,
    residence,
)
from shared.analysis.primitives.timeagg import local_days, sun_class
from shared.analysis.primitives.trajectory import (
    Steps,
    Trajectory,
    exclude_impossible,
    haversine_array,
    load_trajectory,
    steps,
    time_weights,
    turning_angles,
)
from shared.analysis.quality import quality_report
from shared.models import Entity, EntityType, Project

METHOD_VERSION = "movement/1"
Method = Literal["mcp", "kde", "clusters"]
FEW_FIXES = 30
NSD_POINTS = 500
CLUSTER_MIN_POINTS = 5
MAX_CLUSTERS_PER_SUBJECT = 50
SPEED_BINS = 20
TURNING_BINS = 16

#: The summary's metric keys in the order the table shows them (plan, section 8.3).
METRICS: list[str] = [
    "fixes",
    "days_with_data",
    "median_interval_min",
    "distance_km",
    "daily_distance_km",
    "displacement_km",
    "max_displacement_km",
    "mean_speed_mps",
    "median_speed_mps",
    "p95_speed_mps",
    "stationary_share",
    "moving_share",
    "stationary_periods",
    "day_distance_km",
    "night_distance_km",
    "mcp95_ha",
    "kde50_ha",
    "kde95_ha",
    "kde_bandwidth_m",
    "hotspot_count",
    "cluster_count",
    "missing_share",
    "excluded_fixes",
]


class MovementParameters(CommonParameters):
    """The options of section 8.1 with their defaults."""

    max_speed_mps: float = Field(default=15, gt=0, le=100)
    stationary_speed_mps: float = Field(default=0.05, ge=0, le=5)
    stationary_min_minutes: float = Field(default=30, ge=1, le=1440)
    cell_m: float = Field(default=100, ge=10, le=5000)
    revisit_hours: float = Field(default=12, ge=1, le=720)
    methods: list[Method] = Field(default=["mcp", "kde", "clusters"])
    kde_bandwidth_m: float | None = Field(default=None, gt=0, le=50_000)


@dataclass(slots=True)
class SubjectMetrics:
    """One subject in one period: the summary figures, the chart series and the warnings."""

    summary: dict[str, float | None]
    daily_km: list[list[float]]  # [ms at local midnight, km]
    speed_hist: list[float]  # counts per bin
    hour_km: list[float]  # 24 values
    turning_hist: list[float]  # TURNING_BINS values
    nsd: list[list[float]]  # [ms, km²]
    class_km: dict[str, float]  # day, twilight, night
    warnings: list[Warning] = field(default_factory=list)
    hotspot_cells: list[tuple[list[list[float]], float, int]] = field(default_factory=list)
    figures: dict[str, float] = field(default_factory=dict)


def _ms(seconds: float) -> float:
    return float(seconds) * 1000


def _stationary_periods(s: Steps, speed_mps: float, min_seconds: float) -> tuple[float, int, float]:
    """Seconds spent in stationary periods, their number and their mean length; a period is a
    run of consecutive non-gap steps below the speed lasting at least `min_seconds`."""
    still = (~s.gap) & (s.speed_mps < speed_mps)
    total = 0.0
    lengths: list[float] = []
    run = 0.0
    for i in range(len(s)):
        if still[i]:
            run += float(s.dt_s[i])
        elif run:
            if run >= min_seconds:
                lengths.append(run)
            run = 0.0
    if run >= min_seconds:
        lengths.append(run)
    total = float(sum(lengths))
    return total, len(lengths), (total / len(lengths) if lengths else 0.0)


def analyse_trajectory(
    track: Trajectory,
    params: MovementParameters,
    period: Period,
    tz: str,
    *,
    excluded: int = 0,
) -> SubjectMetrics:
    """The metrics of one subject in one period from a trajectory already filtered."""
    gap_s = params.gap_hours * 3600
    s = steps(track, gap_s)
    window_s = (period.time_to - period.time_from).total_seconds()
    n = len(track)
    summary: dict[str, float | None] = dict.fromkeys(METRICS)
    summary["fixes"] = float(n)
    summary["excluded_fixes"] = float(excluded)
    warnings, figures = quality_report(
        track, s, subject_id=track.entity_id, window_seconds=window_s, excluded=excluded
    )
    if "missing_share" in figures:
        summary["missing_share"] = figures["missing_share"]
    if "median_interval_s" in figures:
        summary["median_interval_min"] = round(figures["median_interval_s"] / 60, 1)
    if n == 0:
        return SubjectMetrics(summary, [], [], [0.0] * 24, [0.0] * TURNING_BINS, [], {}, warnings)

    devices = {d for d in track.device_ids}
    if len(devices) > 1:
        change = next(i for i in range(1, n) if track.device_ids[i] != track.device_ids[i - 1])
        when = datetime.fromtimestamp(float(track.times[change]), tz=UTC).date().isoformat()
        warnings.append(
            Warning(
                code="collar_change",
                level="notice",
                subject_id=track.entity_id,
                text=f"The subject changed device inside the period, on {when}.",
            )
        )

    days = local_days(track.times, tz)
    summary["days_with_data"] = float(len(set(days)))
    moving = ~s.gap
    dist_m = s.dist_m[moving]
    covered_s = float(s.dt_s[moving].sum())
    distance_km = float(dist_m.sum()) / 1000
    summary["distance_km"] = round(distance_km, 3)
    summary["daily_distance_km"] = (
        round(distance_km / (covered_s / 86_400), 3) if covered_s > 0 else None
    )
    figures["covered_share"] = round(covered_s / window_s, 3) if window_s > 0 else 0.0

    from_first = haversine_array(
        np.full(n, track.lat[0]), np.full(n, track.lon[0]), track.lat, track.lon
    )
    summary["displacement_km"] = round(float(from_first[-1]) / 1000, 3)
    summary["max_displacement_km"] = round(float(from_first.max()) / 1000, 3)
    stride = max(1, n // NSD_POINTS)
    nsd = [
        [_ms(track.times[i]), round(float(from_first[i] / 1000) ** 2, 4)]
        for i in range(0, n, stride)
    ]

    speeds = s.speed_mps[moving & (s.dt_s > 0)]
    if speeds.size:
        summary["mean_speed_mps"] = round(float(speeds.mean()), 4)
        summary["median_speed_mps"] = round(float(np.median(speeds)), 4)
        summary["p95_speed_mps"] = round(float(np.percentile(speeds, 95)), 4)
        top = max(float(np.percentile(speeds, 99)), 0.01)
        hist, _ = np.histogram(np.clip(speeds, 0, top), bins=SPEED_BINS, range=(0, top))
        speed_hist = [float(v) for v in hist]
        figures["speed_bin_mps"] = top / SPEED_BINS
    else:
        speed_hist = []

    still_s, still_n, still_mean = _stationary_periods(
        s, params.stationary_speed_mps, params.stationary_min_minutes * 60
    )
    if covered_s > 0:
        summary["stationary_share"] = round(still_s / covered_s, 3)
        summary["moving_share"] = round(1 - still_s / covered_s, 3)
    summary["stationary_periods"] = float(still_n)
    figures["stationary_mean_min"] = round(still_mean / 60, 1)

    # day and night by the sun at the start of each step
    classes = (
        sun_class(track.times[:-1], track.lat[:-1], track.lon[:-1]) if len(s) else np.array([])
    )
    class_km: dict[str, float] = {}
    for name in ("day", "twilight", "night"):
        chosen = moving & (classes == name)
        class_km[name] = round(float(s.dist_m[chosen].sum()) / 1000, 3)
    summary["day_distance_km"] = class_km["day"]
    summary["night_distance_km"] = class_km["night"]

    # distance per local day and per hour of the day, by the step's start
    per_day: dict[Any, float] = {}
    hour_km = [0.0] * 24
    zone = ZoneInfo(tz)
    for i in np.where(moving)[0]:
        day = days[i]
        per_day[day] = per_day.get(day, 0.0) + float(s.dist_m[i])
        hour = datetime.fromtimestamp(float(track.times[i]), tz=UTC).astimezone(zone).hour
        hour_km[hour] += float(s.dist_m[i]) / 1000
    daily_km = [
        [_ms(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()), round(v / 1000, 3)]
        for d, v in sorted(per_day.items())
    ]
    hour_km = [round(v, 3) for v in hour_km]

    turns = turning_angles(s)
    t_hist, _ = np.histogram(turns, bins=TURNING_BINS, range=(-180, 180))
    turning_hist = [float(v) for v in t_hist]

    # residence on the grid and the hotspot cells
    metrics = SubjectMetrics(
        summary, daily_km, speed_hist, hour_km, turning_hist, nsd, class_km, warnings
    )
    if n >= FEW_FIXES:
        grid = LocalGrid.around(track, params.cell_m)
        cells = residence(track, time_weights(track, gap_s), grid, params.revisit_hours * 3600)
        total = sum(c.seconds for c in cells.values()) or 1.0
        busiest = hotspots(cells, 0.5)
        summary["hotspot_count"] = float(len(busiest))
        metrics.hotspot_cells = [
            (grid.polygon(*key), round(cell.seconds / total, 4), cell.visits)
            for key, cell in busiest
        ]
    metrics.figures = figures
    return metrics


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def build_document(
    subjects: list[Subject],
    periods: list[Period],
    results: dict[tuple[str, uuid.UUID], SubjectMetrics],
    params: MovementParameters,
    *,
    input_count: int,
    excluded_count: int,
    geometries: dict[str, int] | None = None,
) -> ResultDocument:
    """The result document from the per-subject metrics: the summary, one table subject by
    period, the charts, the warnings, the provenance, and the count of geometries per kind."""
    geometries = geometries or {}
    summary: dict[str, dict[str, dict[str, float | None]]] = {}
    warnings: list[Warning] = []
    rows: list[list[Any]] = []
    for period in periods:
        summary[period.key] = {}
        for subject in subjects:
            m = results.get((period.key, subject.id))
            if m is None:
                continue
            summary[period.key][str(subject.id)] = m.summary
            rows.append([subject.name, period.key] + [m.summary[k] for k in METRICS])
            warnings.extend(m.warnings)
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
            sd_row: list[Any] = ["sd", period.key]
            for key in METRICS:
                column = [v[key] for v in values if v[key] is not None]
                if len(column) >= 2:
                    arr = np.asarray(column, dtype=np.float64)
                    mean_row.append(_round(float(arr.mean())))
                    sd_row.append(_round(float(arr.std(ddof=1))))
                else:
                    mean_row.append(None)
                    sd_row.append(None)
            rows.append(mean_row)
            rows.append(sd_row)
    tables = [Table(key="summary", columns=["subject", "period", *METRICS], rows=rows)]

    def series(pick: Any) -> list[dict[str, Any]]:
        out = []
        for period in periods:
            for subject in subjects:
                m = results.get((period.key, subject.id))
                if m is None:
                    continue
                out.append({"subject": str(subject.id), "period": period.key, "data": pick(m)})
        return out

    charts = [
        Chart(key="daily_distance", kind="line", unit="km", series=series(lambda m: m.daily_km)),
        Chart(
            key="speed_histogram", kind="bar", unit="fixes", series=series(lambda m: m.speed_hist)
        ),
        Chart(key="hour_profile", kind="bar", unit="km", series=series(lambda m: m.hour_km)),
        Chart(key="turning", kind="rose", unit="steps", series=series(lambda m: m.turning_hist)),
        Chart(key="nsd", kind="line", unit="km²", series=series(lambda m: m.nsd)),
        Chart(
            key="day_night",
            kind="stacked",
            unit="km",
            series=series(lambda m: [m.class_km.get(k, 0.0) for k in ("day", "twilight", "night")]),
        ),
    ]
    return ResultDocument(
        module="movement",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=periods,
        summary=summary,
        tables=tables,
        charts=charts,
        geometries=geometries,
        warnings=warnings,
        provenance=Provenance(
            module="movement",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=["positions (device fixes, effective time and geometry, valid rows)"],
        ),
    )


def hotspot_geometries(subject: Subject, period: Period, m: SubjectMetrics) -> list[Geometry]:
    return [
        Geometry(
            kind="hotspot",
            subject_id=subject.id,
            label=f"{subject.name}: {round(share * 100)}% of the time",
            level=share,
            geojson={"type": "Polygon", "coordinates": [ring]},
            properties={"period": period.key, "visits": visits, "time_share": share},
        )
        for ring, share, visits in m.hotspot_cells
    ]


async def spatial_layers(
    session: AsyncSession,
    subject: Subject,
    period: Period,
    track: Trajectory,
    params: MovementParameters,
    m: SubjectMetrics,
) -> list[Geometry]:
    """Home range and clusters for one subject and period when the methods are on and the
    fixes allow it (M2); the summary figures are filled in and the polygons returned."""
    out: list[Geometry] = []
    if len(track) < FEW_FIXES:
        return out
    weights = time_weights(track, params.gap_hours * 3600)
    if "mcp" in params.methods:
        hull = mcp(track.lat, track.lon, 95)
        geojson = mapping(hull.geometry)
        area = await hectares(session, geojson)
        m.summary["mcp95_ha"] = round(area, 2)
        out.append(
            Geometry(
                kind="mcp",
                subject_id=subject.id,
                label=f"{subject.name}: MCP 95%",
                level=0.95,
                geojson=geojson,
                properties={"period": period.key, "hectares": round(area, 2)},
            )
        )
    if "kde" in params.methods:
        bandwidth = params.kde_bandwidth_m or reference_bandwidth(track.lat, track.lon)
        kde = kde_grid(track.lat, track.lon, bandwidth, KDE_MAX_CELLS, weights)
        m.summary["kde_bandwidth_m"] = round(bandwidth, 1)
        for isopleth in isopleths(kde, [0.5, 0.95]):
            geojson = mapping(isopleth.geometry)
            area = await hectares(session, geojson)
            percent = round(isopleth.level * 100)
            m.summary[f"kde{percent}_ha"] = round(area, 2)
            out.append(
                Geometry(
                    kind="kde",
                    subject_id=subject.id,
                    label=f"{subject.name}: KDE {percent}%",
                    level=isopleth.level,
                    geojson=geojson,
                    properties={
                        "period": period.key,
                        "hectares": round(area, 2),
                        "bandwidth_m": round(bandwidth, 1),
                        "cell_m": round(kde.cell_m, 1),
                    },
                )
            )
    if "clusters" in params.methods:
        found = await clusters_sql(
            session,
            subject.id,
            period.time_from,
            period.time_to,
            eps_m=params.cell_m,
            min_points=CLUSTER_MIN_POINTS,
            max_clusters=MAX_CLUSTERS_PER_SUBJECT,
        )
        m.summary["cluster_count"] = float(len(found))
        for i, cluster in enumerate(found, start=1):
            out.append(
                Geometry(
                    kind="cluster",
                    subject_id=subject.id,
                    label=f"{subject.name}: cluster {i} ({cluster.fixes} fixes)",
                    level=cluster.fix_share,
                    geojson=cluster.hull,
                    properties={
                        "period": period.key,
                        "fixes": cluster.fixes,
                        "fix_share": cluster.fix_share,
                        "first_at": cluster.first_at.isoformat(),
                        "last_at": cluster.last_at.isoformat(),
                    },
                )
            )
    return out


class MovementModule:
    key = "movement"
    label = "Movement"
    version = METHOD_VERSION
    parameters: type[BaseModel] = MovementParameters

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, MovementParameters)
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
        results: dict[tuple[str, uuid.UUID], SubjectMetrics] = {}
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
                m = analyse_trajectory(track, params, period, tz or "UTC", excluded=dropped)
                results[(period.key, subject.id)] = m
                geometries.extend(hotspot_geometries(subject, period, m))
                geometries.extend(await spatial_layers(session, subject, period, track, params, m))
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
