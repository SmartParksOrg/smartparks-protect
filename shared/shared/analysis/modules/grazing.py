"""Grazing and rewilding, level 1 (docs/ANALYTICS_PHASE1_PLAN.md, section 9): how tracked
grazing animals use the chosen management areas over time, from the fixes and the polygons
alone. Time in an area is a proxy for potential grazing pressure, never measured feeding, and
every table says so in its headers. Containment runs in shapely over the trajectory arrays
the movement primitives already load, so the fixes are read once."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import shapely
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select, text
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
from shared.analysis.limits import MAX_AREAS_GRAZING, MAX_FIXES_PER_SUBJECT
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.spatial import CellUse, LocalGrid, hotspots
from shared.analysis.primitives.timeagg import local_days, seasons
from shared.analysis.primitives.trajectory import (
    Trajectory,
    exclude_impossible,
    load_trajectory,
    steps,
    time_weights,
)
from shared.analysis.quality import quality_report
from shared.models import Entity, EntityType, Project

METHOD_VERSION = "grazing/1"
AREA_TYPES = ("zone", "geofence")
MIN_AREA_HA = 1.0
MAX_HOTSPOTS_PER_AREA = 60
FEW_FIXES = 30

Weighting = Literal["equal", "attribute", "metabolic"]

#: The per-area figures in table order (plan, section 9.2); the headers carry the weighting.
AREA_METRICS: list[str] = [
    "hectares",
    "animal_hours",
    "animal_days",
    "animal_hours_per_ha",
    "animal_days_per_ha",
    "weighted_animal_days_per_ha",
    "relative_pressure",
    "pressure_rank",
    "share_of_herd_time",
    "animals_used",
    "visits",
    "mean_visit_hours",
    "use_days",
    "rest_days",
    "longest_rest_days",
    "last_use",
    "hours_since_last_use",
    "hotspot_count",
]
ANIMAL_METRICS: list[str] = [
    "hours",
    "weighted_hours",
    "visits",
    "mean_visit_hours",
    "first_use",
    "last_use",
    "days_used",
]


class GrazingParameters(CommonParameters):
    feature_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_AREAS_GRAZING)
    weighting: Weighting = "equal"
    weight_key: str | None = Field(default=None, max_length=64)
    seasons: bool = False
    #: A second herd to compare with, by entity id (the API narrows it to the caller's scope).
    herd_b_entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    min_absence_hours: float = Field(default=6, ge=1, le=168)
    cell_m: float = Field(default=100, ge=10, le=5000)
    rest_threshold_hours: float = Field(default=0, ge=0, le=24)
    max_speed_mps: float = Field(default=5, gt=0, le=100)


@dataclass(slots=True)
class Area:
    id: uuid.UUID
    name: str
    kind: str
    geometry: BaseGeometry
    geojson: dict[str, Any]
    hectares: float


@dataclass(slots=True)
class Animal:
    """One animal's fixes over a window with everything the areas need: the time weight per
    fix, the local day per fix, the animal's weighting, and which fixes lie in which area."""

    subject: Subject
    track: Trajectory
    weights: NDArray[np.float64]
    days: list[date]
    weight: float = 1.0
    inside: dict[uuid.UUID, NDArray[np.bool_]] = field(default_factory=dict)
    excluded: int = 0


def containment(track: Trajectory, areas: list[Area]) -> dict[uuid.UUID, NDArray[np.bool_]]:
    """Which fixes lie in each area; a fix in overlapping areas counts in each."""
    return {area.id: shapely.contains_xy(area.geometry, track.lon, track.lat) for area in areas}


def _visits(
    times: NDArray[np.float64], weights: NDArray[np.float64], min_absence_s: float
) -> list[tuple[float, float, float]]:
    """Runs of fixes inside an area: (first time, last time, seconds); a run ends after an
    absence longer than `min_absence_s`."""
    out: list[tuple[float, float, float]] = []
    if times.size == 0:
        return out
    start = last = float(times[0])
    held = 0.0
    for t, w in zip(times, weights, strict=True):
        if t - last > min_absence_s:
            out.append((start, last, held))
            start, held = float(t), 0.0
        held += float(w)
        last = float(t)
    out.append((start, last, held))
    return out


def _day_index(days: list[date], first: date) -> NDArray[np.int64]:
    return np.asarray([(d - first).days for d in days], dtype=np.int64)


@dataclass(slots=True)
class AreaUse:
    """What one window says about the areas: the per-area figures, the per-animal rows, the
    daily animal-hours per area, and the herd totals."""

    areas: dict[uuid.UUID, dict[str, Any]]
    animals: list[list[Any]]
    timeline: dict[uuid.UUID, list[float]]  # animal-hours per day of the window
    days: list[date]
    herd: dict[str, float]


def area_use(
    animals: list[Animal],
    areas: list[Area],
    time_from: datetime,
    time_to: datetime,
    tz: str,
    *,
    min_absence_s: float,
    rest_threshold_h: float,
) -> AreaUse:
    """The level 1 figures of section 9.1 over one window (a period, a season)."""
    zone = ZoneInfo(tz)
    first_day = time_from.astimezone(zone).date()
    last_day = (time_to - timedelta(microseconds=1)).astimezone(zone).date()
    days = [first_day + timedelta(days=i) for i in range((last_day - first_day).days + 1)]
    n_days = len(days)
    t0, t1 = time_from.timestamp(), time_to.timestamp()
    timeline = {area.id: np.zeros(n_days, dtype=np.float64) for area in areas}
    per_area: dict[uuid.UUID, dict[str, Any]] = {}
    animal_rows: list[list[Any]] = []
    tracked_h = weighted_tracked_h = inside_any_h = 0.0
    for area in areas:
        per_area[area.id] = {
            "hours": 0.0,
            "weighted_hours": 0.0,
            "animals": 0,
            "visits": 0,
            "visit_hours": [],
            "use_days": set(),
            "last": -math.inf,
        }
    for animal in animals:
        mask = (animal.track.times >= t0) & (animal.track.times < t1)
        if not mask.any():
            continue
        w = animal.weights * mask
        tracked_h += float(w.sum()) / 3600
        weighted_tracked_h += animal.weight * float(w.sum()) / 3600
        any_inside = np.zeros(len(animal.track), dtype=np.bool_)
        day_idx = _day_index(animal.days, first_day)
        for area in areas:
            inside = animal.inside[area.id] & mask
            if not inside.any():
                continue
            any_inside |= inside
            hours = float(w[inside].sum()) / 3600
            block = per_area[area.id]
            block["hours"] += hours
            block["weighted_hours"] += animal.weight * hours
            block["animals"] += 1
            visits = _visits(animal.track.times[inside], w[inside], min_absence_s)
            block["visits"] += len(visits)
            block["visit_hours"].extend(v[2] / 3600 for v in visits)
            used = {animal.days[i] for i in np.where(inside)[0]}
            block["use_days"] |= used
            block["last"] = max(block["last"], float(animal.track.times[inside].max()))
            valid = inside & (day_idx >= 0) & (day_idx < n_days)
            np.add.at(timeline[area.id], day_idx[valid], w[valid] / 3600)
            animal_rows.append(
                [
                    animal.subject.name,
                    area.name,
                    round(hours, 2),
                    round(animal.weight * hours, 2),
                    len(visits),
                    round(sum(v[2] for v in visits) / 3600 / len(visits), 2) if visits else 0,
                    _iso(visits[0][0]),
                    _iso(visits[-1][1]),
                    len(used),
                ]
            )
        inside_any_h += float(w[any_inside].sum()) / 3600
    figures: dict[uuid.UUID, dict[str, Any]] = {}
    for area in areas:
        block = per_area[area.id]
        line = timeline[area.id]
        rest = line <= rest_threshold_h
        longest = 0
        run = 0
        for r in rest:
            run = run + 1 if r else 0
            longest = max(longest, run)
        hours = block["hours"]
        figures[area.id] = {
            "hectares": round(area.hectares, 2),
            "animal_hours": round(hours, 2),
            "animal_days": round(hours / 24, 3),
            "animal_hours_per_ha": round(hours / area.hectares, 4),
            "animal_days_per_ha": round(hours / 24 / area.hectares, 4),
            "weighted_animal_days_per_ha": round(block["weighted_hours"] / 24 / area.hectares, 4),
            "relative_pressure": None,
            "pressure_rank": None,
            "share_of_herd_time": round(hours / tracked_h, 4) if tracked_h else None,
            "animals_used": block["animals"],
            "visits": block["visits"],
            "mean_visit_hours": round(sum(block["visit_hours"]) / len(block["visit_hours"]), 2)
            if block["visit_hours"]
            else None,
            "use_days": len(block["use_days"]),
            "rest_days": int(rest.sum()),
            "longest_rest_days": longest,
            "last_use": _iso(block["last"]) if block["last"] > -math.inf else None,
            "hours_since_last_use": round((t1 - block["last"]) / 3600, 1)
            if block["last"] > -math.inf
            else None,
            "hotspot_count": None,
        }
    # relative pressure: an area's animal-days per hectare against the mean over the areas
    values = [f["animal_days_per_ha"] for f in figures.values()]
    mean = sum(values) / len(values) if values else 0.0
    ranked = sorted(figures.items(), key=lambda kv: kv[1]["animal_days_per_ha"], reverse=True)
    for rank, (_area_id, f) in enumerate(ranked, start=1):
        f["relative_pressure"] = round(f["animal_days_per_ha"] / mean, 3) if mean > 0 else None
        f["pressure_rank"] = rank if mean > 0 else None
    herd = {
        "tracked_animal_hours": round(tracked_h, 2),
        "weighted_animal_hours": round(weighted_tracked_h, 2),
        "share_inside": round(inside_any_h / tracked_h, 4) if tracked_h else 0.0,
        "share_outside": round(1 - inside_any_h / tracked_h, 4) if tracked_h else 0.0,
    }
    return AreaUse(
        figures,
        animal_rows,
        {k: [round(float(v), 3) for v in line] for k, line in timeline.items()},
        days,
        herd,
    )


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def weights_of(
    animals: list[Animal], weighting: Weighting, key: str | None, attributes: dict[uuid.UUID, Any]
) -> list[Warning]:
    """Set each animal's weighting from its attribute; the ones without a value count one
    and are named in a warning. Metabolic weights are mass to the 0.75, normalised to the
    herd mean so the totals stay in animal units."""
    if weighting == "equal":
        return []
    missing: list[str] = []
    raw: dict[uuid.UUID, float] = {}
    for animal in animals:
        value = attributes.get(animal.subject.id)
        try:
            number = float(value) if value is not None else None
        except (TypeError, ValueError):
            number = None
        if number is None or number <= 0:
            missing.append(animal.subject.name)
        else:
            raw[animal.subject.id] = number
    if weighting == "metabolic":
        scaled = {k: v**0.75 for k, v in raw.items()}
        mean = sum(scaled.values()) / len(scaled) if scaled else 1.0
        raw = {k: v / mean for k, v in scaled.items()}
    for animal in animals:
        animal.weight = raw.get(animal.subject.id, 1.0)
    if not missing:
        return []
    return [
        Warning(
            code="weight_missing",
            text=(f"No value for '{key}' on {', '.join(missing)}; they count as one animal each."),
        )
    ]


def _overlaps_sql() -> str:
    return """
        SELECT a.id AS a, b.id AS b,
               ST_Area(ST_Intersection(a.geom, b.geom)::geography) / 10000 AS ha
        FROM features a JOIN features b ON a.id < b.id
        WHERE a.id = ANY(CAST(:ids AS uuid[])) AND b.id = ANY(CAST(:ids AS uuid[]))
          AND ST_Intersects(a.geom, b.geom)
    """


async def load_areas(
    session: AsyncSession, project_id: uuid.UUID, feature_ids: list[uuid.UUID]
) -> tuple[list[Area], list[str]]:
    """The chosen polygons with their geodesic hectares, in the order asked, and the reasons
    any of them cannot be used (missing, not a zone or geofence, not a polygon, invalid, under
    one hectare)."""
    rows = (
        await session.execute(
            text(
                """
                SELECT id, name, feature_type, ST_AsGeoJSON(geom) AS geojson,
                       ST_Area(geom::geography) / 10000 AS ha, ST_IsValid(geom) AS valid,
                       ST_Dimension(geom) AS dimension
                FROM features
                WHERE project_id = :project_id AND id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"project_id": project_id, "ids": [str(i) for i in feature_ids]},
        )
    ).all()
    by_id = {row.id: row for row in rows}
    areas: list[Area] = []
    reasons: list[str] = []
    for feature_id in feature_ids:
        row = by_id.get(feature_id)
        if row is None:
            reasons.append(f"Area {feature_id} is not a feature of this project.")
            continue
        if row.feature_type not in AREA_TYPES:
            reasons.append(f"{row.name} is a {row.feature_type}, not a zone or a geofence.")
        elif row.dimension != 2:
            reasons.append(f"{row.name} is not a polygon.")
        elif not row.valid:
            reasons.append(f"The polygon of {row.name} is invalid; repair it on the Features page.")
        elif float(row.ha) < MIN_AREA_HA:
            reasons.append(f"{row.name} is under one hectare ({float(row.ha):.2f} ha).")
        else:
            geojson = json.loads(row.geojson)
            areas.append(
                Area(row.id, row.name, row.feature_type, shape(geojson), geojson, float(row.ha))
            )
    return areas, reasons


class GrazingModule:
    key = "grazing"
    label = "Grazing"
    version = METHOD_VERSION
    parameters: type[BaseModel] = GrazingParameters

    async def check(
        self, session: AsyncSession, project_id: uuid.UUID, params: BaseModel
    ) -> list[str]:
        """What the estimate can already refuse: the areas."""
        assert isinstance(params, GrazingParameters)
        _, reasons = await load_areas(session, project_id, params.feature_ids)
        return reasons

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, GrazingParameters)
        session = ctx.session
        tz = await session.scalar(select(Project.timezone).where(Project.id == ctx.project_id))
        tz = tz or "UTC"
        areas, reasons = await load_areas(session, ctx.project_id, params.feature_ids)
        if reasons:
            raise ValueError(" ".join(reasons))
        overlaps = (
            await session.execute(text(_overlaps_sql()), {"ids": [str(a.id) for a in areas]})
        ).all()
        herds: list[tuple[str, list[uuid.UUID]]] = [("A", params.entity_ids)]
        if params.herd_b_entity_ids:
            herds.append(("B", params.herd_b_entity_ids))
        periods = [Period(key="main", time_from=params.time_from, time_to=params.time_to)]
        if params.comparison:
            periods.append(
                Period(
                    key="comparison",
                    time_from=params.comparison.time_from,
                    time_to=params.comparison.time_to,
                )
            )
        rows = (
            await session.execute(
                select(Entity.id, Entity.name, EntityType.label, Entity.attributes)
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(
                    Entity.id.in_([i for _, ids in herds for i in ids]),
                    Entity.project_id == ctx.project_id,
                )
                .order_by(Entity.name)
            )
        ).all()
        entity_rows = {r.id: r for r in rows}
        subjects = [Subject(id=r.id, name=r.name, type=r.label) for r in rows]
        attributes = {
            r.id: (r.attributes or {}).get(params.weight_key) if params.weight_key else None
            for r in rows
        }
        centre = shapely.union_all([a.geometry for a in areas]).centroid
        grid = LocalGrid(float(centre.y), float(centre.x), params.cell_m)
        southern = float(centre.y) < 0
        gap_s = params.gap_hours * 3600
        warnings: list[Warning] = []
        area_rows: list[list[Any]] = []
        animal_rows: list[list[Any]] = []
        comparison_rows: list[list[Any]] = []
        timeline_series: list[dict[str, Any]] = []
        pressure_series: list[dict[str, Any]] = []
        summary: dict[str, Any] = {"herd": {}}
        geometries: list[Geometry] = []
        input_count = excluded_count = 0
        total_steps = max(1, len(periods) * sum(len(ids) for _, ids in herds))
        done = 0
        main_use: dict[str, AreaUse] = {}
        for period in periods:
            summary[period.key] = {}
            for herd_key, ids in herds:
                animals: list[Animal] = []
                for entity_id in ids:
                    row = entity_rows.get(entity_id)
                    if row is None:
                        continue
                    subject = Subject(id=row.id, name=row.name, type=row.label)
                    await ctx.progress(int(done * 85 / total_steps), f"{row.name} ({period.key})")
                    done += 1
                    track = await load_trajectory(
                        session,
                        entity_id,
                        period.time_from,
                        period.time_to,
                        max_fixes=MAX_FIXES_PER_SUBJECT,
                    )
                    input_count += len(track) + track.duplicates
                    track, dropped = exclude_impossible(track, params.max_speed_mps)
                    excluded_count += dropped + track.duplicates
                    if len(track) == 0:
                        warnings.append(
                            Warning(
                                code="no_fixes",
                                subject_id=row.id,
                                text=f"No fixes in the {period.key} period.",
                            )
                        )
                        continue
                    if period.key == "main":
                        quality, _ = quality_report(
                            track,
                            steps(track, gap_s),
                            subject_id=row.id,
                            window_seconds=(period.time_to - period.time_from).total_seconds(),
                            excluded=dropped,
                        )
                        warnings.extend(w for w in quality if w.code != "few_fixes")
                    animal = Animal(
                        subject,
                        track,
                        time_weights(track, gap_s),
                        local_days(track.times, tz),
                        excluded=dropped,
                    )
                    animal.inside = containment(track, areas)
                    animals.append(animal)
                if period.key == "main":
                    warnings.extend(
                        weights_of(animals, params.weighting, params.weight_key, attributes)
                    )
                else:
                    weights_of(animals, params.weighting, params.weight_key, attributes)
                windows: list[tuple[str, datetime, datetime]] = [
                    (period.key, period.time_from, period.time_to)
                ]
                if params.seasons:
                    windows.extend(
                        (f"{period.key}:{name}", start, end)
                        for name, start, end in seasons(
                            period.time_from, period.time_to, tz, southern
                        )
                    )
                for label, start, end in windows:
                    use = area_use(
                        animals,
                        areas,
                        start,
                        end,
                        tz,
                        min_absence_s=params.min_absence_hours * 3600,
                        rest_threshold_h=params.rest_threshold_hours,
                    )
                    herd_label = herd_key if len(herds) > 1 else None
                    if label == period.key:
                        main_use[f"{period.key}:{herd_key}"] = use
                        if period.key == "main" and herd_key == "A":
                            geometries.extend(
                                _spatial(
                                    animals, areas, use, grid, params.time_from, params.time_to
                                )
                            )
                        if herd_key == "A":
                            summary["herd"][period.key] = use.herd
                            summary[period.key] = {str(a): f for a, f in use.areas.items()}
                        animal_rows.extend(
                            [*r, period.key] + ([herd_label] if herd_label else [])
                            for r in use.animals
                        )
                        for area in areas:
                            timeline_series.append(
                                {
                                    "name": area.name,
                                    "area": str(area.id),
                                    "period": period.key,
                                    **({"herd": herd_key} if herd_label else {}),
                                    "data": [
                                        [_day_ms(d), v]
                                        for d, v in zip(
                                            use.days, use.timeline[area.id], strict=True
                                        )
                                    ],
                                }
                            )
                        pressure_series.append(
                            {
                                "name": f"{period.key} {herd_key}" if herd_label else period.key,
                                "period": period.key,
                                **({"herd": herd_key} if herd_label else {}),
                                "data": [
                                    [a.name, use.areas[a.id]["animal_days_per_ha"]] for a in areas
                                ],
                            }
                        )
                    for area in areas:
                        f = use.areas[area.id]
                        area_rows.append(
                            [area.name, label]
                            + ([herd_key] if herd_label else [])
                            + [f[k] for k in AREA_METRICS]
                        )
        main = main_use.get("main:A")
        # the comparison: main against the period before, per area
        before = main_use.get("comparison:A")
        if main is not None and before is not None:
            for area in areas:
                a, b = main.areas[area.id], before.areas[area.id]
                for metric in ("animal_days_per_ha", "animal_hours", "use_days", "rest_days"):
                    x, y = a[metric], b[metric]
                    change = round((x - y) / y * 100, 1) if y else None
                    comparison_rows.append([area.name, metric, x, y, change])
        for a, b, ha in overlaps:
            name_a = next(x.name for x in areas if x.id == a)
            name_b = next(x.name for x in areas if x.id == b)
            warnings.append(
                Warning(
                    code="overlap",
                    level="notice",
                    text=(
                        f"{name_a} and {name_b} overlap by {float(ha):.2f} ha; time there "
                        "counts in both."
                    ),
                )
            )
        await ctx.progress(95, "document")
        unit = {
            "equal": "animals",
            "attribute": f"{params.weight_key} units",
            "metabolic": "metabolic units",
        }[params.weighting]
        herd_column = ["herd"] if len(herds) > 1 else []
        tables = [
            Table(
                key="areas",
                columns=["area", "period", *herd_column, *AREA_METRICS],
                rows=area_rows,
            ),
            Table(
                key="animals",
                columns=["animal", "area", *ANIMAL_METRICS, "period", *herd_column],
                rows=animal_rows,
            ),
        ]
        if comparison_rows:
            tables.append(
                Table(
                    key="comparison",
                    columns=["area", "metric", "main", "comparison", "change_percent"],
                    rows=comparison_rows,
                )
            )
        if overlaps:
            tables.append(
                Table(
                    key="overlaps",
                    columns=["area_a", "area_b", "hectares"],
                    rows=[
                        [
                            next(x.name for x in areas if x.id == a),
                            next(x.name for x in areas if x.id == b),
                            round(float(ha), 2),
                        ]
                        for a, b, ha in overlaps
                    ],
                )
            )
        charts = [
            Chart(key="timeline", kind="line", unit="animal-hours", series=timeline_series),
            Chart(
                key="pressure",
                kind="bar",
                unit=f"animal-days per ha ({unit})",
                series=pressure_series,
            ),
        ]
        counts: dict[str, int] = {}
        for g in geometries:
            counts[g.kind] = counts.get(g.kind, 0) + 1
        document = ResultDocument(
            module="grazing",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            summary={
                **summary,
                "weighting": {"kind": params.weighting, "key": params.weight_key, "unit": unit},
                "areas": [
                    {
                        "id": str(a.id),
                        "name": a.name,
                        "kind": a.kind,
                        "hectares": round(a.hectares, 2),
                    }
                    for a in areas
                ],
            },
            tables=tables,
            charts=charts,
            geometries=counts,
            warnings=warnings,
            provenance=Provenance(
                module="grazing",
                method_version=METHOD_VERSION,
                subjects=subjects,
                periods=periods,
                parameters=params.model_dump(mode="json"),
                input_count=input_count,
                excluded_count=excluded_count,
                computed_at=datetime.now(UTC),
                sources=[
                    "positions (device fixes, effective time and geometry, valid rows)",
                    "features (zones and geofences chosen for the run)",
                ],
            ),
        )
        return RunResult(document=document, geometries=geometries)


def _day_ms(day: date) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000


def _spatial(
    animals: list[Animal],
    areas: list[Area],
    use: AreaUse,
    grid: LocalGrid,
    time_from: datetime,
    time_to: datetime,
) -> list[Geometry]:
    """The hotspot cells inside each area (the busiest holding half of the area's time, at
    most 60) and the areas themselves with their pressure, for the main period; the hotspot
    counts are written into the use figures."""
    out: list[Geometry] = []
    for area in areas:
        cells = _area_cells(animals, area, grid, time_from, time_to)
        total = sum(c.seconds for c in cells.values()) or 1.0
        busiest = hotspots(cells, 0.5)[:MAX_HOTSPOTS_PER_AREA]
        use.areas[area.id]["hotspot_count"] = len(busiest)
        for key, cell in busiest:
            share = round(cell.seconds / total, 4)
            out.append(
                Geometry(
                    kind="hotspot",
                    label=f"{area.name}: {round(share * 100)}% of its time",
                    level=share,
                    geojson={"type": "Polygon", "coordinates": [grid.polygon(*key)]},
                    properties={
                        "area_id": str(area.id),
                        "period": "main",
                        "visits": cell.visits,
                        "time_share": share,
                    },
                )
            )
    for area in areas:
        f = use.areas[area.id]
        out.append(
            Geometry(
                kind="area",
                label=area.name,
                level=f["relative_pressure"],
                geojson=area.geojson,
                properties={
                    "area_id": str(area.id),
                    "period": "main",
                    "hectares": f["hectares"],
                    "animal_days_per_ha": f["animal_days_per_ha"],
                    "relative_pressure": f["relative_pressure"],
                    "pressure_rank": f["pressure_rank"],
                    "rest_days": f["rest_days"],
                },
            )
        )
    return out


def _area_cells(
    animals: list[Animal], area: Area, grid: LocalGrid, time_from: datetime, time_to: datetime
) -> dict[tuple[int, int], CellUse]:
    """Residence per cell inside one area, summed over the herd, visits per animal added."""
    out: dict[tuple[int, int], CellUse] = {}
    t0, t1 = time_from.timestamp(), time_to.timestamp()
    for animal in animals:
        chosen = animal.inside[area.id] & (animal.track.times >= t0) & (animal.track.times < t1)
        if not chosen.any():
            continue
        ix, iy = grid.cells_of(animal.track.lat[chosen], animal.track.lon[chosen])
        w = animal.weights[chosen] * animal.weight
        seen: set[tuple[int, int]] = set()
        for i in range(len(w)):
            key = (int(ix[i]), int(iy[i]))
            cell = out.get(key)
            if cell is None:
                cell = CellUse(key[0], key[1])
                out[key] = cell
            cell.seconds += float(w[i])
            if key not in seen:
                cell.visits += 1
                seen.add(key)
    return out
