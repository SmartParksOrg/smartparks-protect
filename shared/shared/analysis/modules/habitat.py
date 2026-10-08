"""Habitat selection (phase 41, decisions D313 to D318, docs/HABITAT_SELECTION_PLAN.md):
which habitat the animals selected against what was available to them, through hrHSA's
frequentist resource selection function: the fixes as used points, available points sampled
in each animal's own domain, the covariates read at both from rasters over the run's area,
a logistic fit, leave-one-individual-out validation with the Boyce index, and a relative
selection surface on the map. The engine is hrHSA (Paul Kasko and Ralph Kühn, BSD 3-Clause);
this module assembles its inputs and reads its answer. A worker without it refuses the run
with `MODULE_UNAVAILABLE` (decision D318)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from shared.analysis.environment import configured_provider
from shared.analysis.limits import MAX_FIXES_PER_SUBJECT, MIN_SUBJECTS_LOIO
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives import habitat as hab
from shared.analysis.primitives.trajectory import (
    Trajectory,
    exclude_impossible,
    fold_stops,
    load_trajectory,
    steps,
)
from shared.analysis.quality import quality_report
from shared.analysis.rasters import (
    DISTANCE_PREFIX,
    FETCHED_LAYERS,
    LayerChoice,
    cached_raster,
    project_layer_bytes,
    project_layers,
)
from shared.enums import LayerKind
from shared.logger import get_logger
from shared.models import Entity, EntityType, Feature, Project, ProjectLayer

log = get_logger("analysis.habitat")

METHOD_VERSION = "habitat_selection/1"
#: The hrHSA commit the worker image pins (services/analysis/image/pyproject.toml), named
#: in the provenance so a result says what computed it.
ENGINE = "hrHSA c6e975be (Kasko and Kühn, BSD 3-Clause)"
#: Fewer fixes than this and an animal is left out of the fit with a warning: hrHSA needs
#: five for a domain, and a hull over a handful of fixes is no range.
FEW_FIXES = 20
MAX_LAYERS = 8
#: A Boyce index under this says the model ranks the held-out animal's fixes little better
#: than chance (the index runs from -1 to 1).
BOYCE_WEAK = 0.5
#: A layer with a value in fewer cells than this share of the grid is warned about.
SPARSE_COVERAGE = 0.9
#: The finest grid a distance layer or an upload asks for, in metres.
DISTANCE_RESOLUTION_M = 30.0

METRICS: list[str] = ["fixes", "domain_ha", "boyce", "excluded_fixes", "folded_fixes"]
FLEET_METRICS: list[str] = [
    "used_points",
    "available_points",
    "log_likelihood",
    "mean_boyce",
    "layers",
    "grid_m",
]


class HabitatParameters(CommonParameters):
    """The subjects and the period of every module, the layers by name (what
    `GET /projects/{id}/analysis-layers` offers), and the method (decision D316)."""

    layers: list[str] = Field(min_length=1, max_length=MAX_LAYERS)
    #: Layers also entered squared, for a response that peaks (a distance that is good up
    #: to a point).
    quadratic: list[str] = Field(default_factory=list, max_length=MAX_LAYERS)
    domain_quantile: float = Field(default=0.95, ge=0.5, le=1.0)
    sampling_factor: int = Field(default=10, ge=1, le=50)
    #: Hours between two fixes kept for the fit; null keeps every fix.
    thin_hours: float | None = Field(default=12, ge=0.25, le=168)
    area_buffer_m: float = Field(default=1_000, ge=0, le=20_000)
    loio: bool = True
    #: The stop rule of decision D303, off by default: a parked receiver's drift is used
    #: habitat too, and the fold would thin it.
    stop_radius_m: float = Field(default=0, ge=0, le=500)
    max_speed_mps: float = Field(default=15, gt=0, le=100)


class HabitatModule:
    key = "habitat_selection"
    label = "Habitat selection"
    version = METHOD_VERSION
    parameters: type[BaseModel] = HabitatParameters

    #: The API's estimate refuses a run whose subjects together have fewer fixes than one
    #: animal needs, so the form says so before the run is queued (the first run on Okonjima,
    #: 2026-10-08, failed in the worker on an animal with 18 fixes in the week).
    min_fixes: int = FEW_FIXES

    async def check(
        self, session: AsyncSession, project_id: uuid.UUID, params: BaseModel
    ) -> list[str]:
        """Before a run is queued: every named layer exists for the project, a squared layer
        is one of the chosen, and no comparison period (not offered yet)."""
        assert isinstance(params, HabitatParameters)
        reasons: list[str] = []
        choices = {c.name: c for c in await project_layers(session, project_id)}
        unknown = [name for name in params.layers if name not in choices]
        if unknown:
            reasons.append(
                f"No layer named {', '.join(unknown)} in this project; choose from the layers "
                "the project offers."
            )
        for name in params.quadratic:
            if name not in params.layers:
                reasons.append(f"{name} is squared but not among the layers.")
            elif name in choices and choices[name].kind == LayerKind.CATEGORICAL:
                reasons.append(f"{name} is a categorical layer and cannot be squared.")
        if len(set(params.layers)) != len(params.layers):
            reasons.append("A layer is named twice.")
        if params.comparison is not None:
            reasons.append("A comparison period is not offered by this analysis yet.")
        return reasons

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, HabitatParameters)
        hab.require_engine()
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
        period = Period(key="main", time_from=params.time_from, time_to=params.time_to)
        window_s = (period.time_to - period.time_from).total_seconds()
        warnings: list[Warning] = []
        tracks: list[Trajectory] = []
        figures: dict[uuid.UUID, dict[str, float | None]] = {}
        input_count = excluded_count = 0
        for index, subject in enumerate(subjects):
            await ctx.progress(int(index * 20 / max(1, len(subjects))), f"{subject.name} (fixes)")
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
            folded = 0
            if params.stop_radius_m > 0:
                track, folded = fold_stops(track, params.stop_radius_m)
            quality, _ = quality_report(
                track,
                steps(track, params.gap_hours * 3600),
                subject_id=subject.id,
                window_seconds=window_s,
                excluded=dropped,
                few_fixes=FEW_FIXES,
            )
            warnings.extend(quality)
            figures[subject.id] = {
                "fixes": float(len(track)),
                "domain_ha": None,
                "boyce": None,
                "excluded_fixes": float(dropped),
                "folded_fixes": float(folded),
            }
            if len(track) < FEW_FIXES:
                warnings.append(
                    Warning(
                        code="left_out",
                        subject_id=subject.id,
                        text=(
                            f"{subject.name}: {len(track)} fixes in the period, fewer than "
                            f"{FEW_FIXES}, so the animal is left out of the fit."
                        ),
                    )
                )
                continue
            tracks.append(track)
        if not tracks:
            raise ValueError(
                f"No animal has {FEW_FIXES} fixes or more in the period; nothing to fit."
            )
        await ctx.progress(22, "the grid")
        choices = {c.name: c for c in await project_layers(session, ctx.project_id)}
        chosen = [choices[name] for name in params.layers if name in choices]
        if not chosen:
            raise ValueError("None of the named layers exists in the project any more.")
        finest = min(_finest_m(c, session_layers=None) for c in chosen)
        grid = hab.grid_for(
            tracks,
            quantile=params.domain_quantile,
            buffer_m=params.area_buffer_m,
            finest_m=finest,
        )
        layers, layer_rows = await self._layers(ctx, params, chosen, grid, period, warnings)
        if not layers:
            raise ValueError(
                "No layer could be read for the run's area: "
                + "; ".join(w.text for w in warnings if w.code.startswith("layer"))
            )
        await ctx.progress(58, "the fit")
        names = {s.id: s.name for s in subjects}
        reloc = hab.relocations(tracks, names, grid.epsg)
        env = hab.stack_layers(grid, layers)
        categorical = [
            c.name for c in chosen if c.name in layers and c.kind == LayerKind.CATEGORICAL
        ]
        linear = [name for name in layers if name not in categorical]
        quadratic = [name for name in params.quadratic if name in linear]
        loio = params.loio and len(tracks) >= MIN_SUBJECTS_LOIO
        if params.loio and not loio:
            warnings.append(
                Warning(
                    code="loio_skipped",
                    level="notice",
                    text=(
                        f"Leave-one-individual-out validation needs {MIN_SUBJECTS_LOIO} animals "
                        f"with enough fixes; this run has {len(tracks)}, so it is skipped."
                    ),
                )
            )
        fit = hab.fit_rsf(
            reloc,
            env,
            linear=linear,
            quadratic=quadratic,
            categorical=categorical,
            domain_quantile=params.domain_quantile,
            sampling_factor=params.sampling_factor,
            thin_hours=params.thin_hours,
            loio=loio,
        )
        await ctx.progress(90, "the surface")
        if fit.used < FEW_FIXES:
            thinned = (
                f"after thinning to one fix per {params.thin_hours:g} h, "
                if params.thin_hours
                else ""
            )
            warnings.append(
                Warning(
                    code="few_used",
                    text=(
                        f"Only {fit.used} fixes carry the fit {thinned}so the coefficients "
                        "rest on few points; a longer period or less thinning gives more."
                    ),
                )
            )
        if not fit.converged:
            warnings.append(
                Warning(
                    code="not_converged",
                    text="The fit did not converge; read the coefficients with care, and try "
                    "fewer layers or more fixes.",
                )
            )
        for fold in fit.folds:
            figures.setdefault(fold.subject_id, {})["boyce"] = fold.boyce
            name = names.get(fold.subject_id, str(fold.subject_id))
            if fold.error:
                warnings.append(
                    Warning(
                        code="fold_failed",
                        subject_id=fold.subject_id,
                        text=f"{name}: the validation fold failed ({fold.error}).",
                    )
                )
            elif fold.boyce is not None and fold.boyce < BOYCE_WEAK:
                warnings.append(
                    Warning(
                        code="boyce_weak",
                        subject_id=fold.subject_id,
                        text=(
                            f"{name}: a Boyce index of {fold.boyce:.2f}: the model fitted on the "
                            "other animals ranks this one's fixes little better than chance."
                        ),
                    )
                )
        geometries = self._geometries(tracks, names, grid, fit, params, figures)
        await ctx.progress(97, "document")
        counts: dict[str, int] = {}
        for g in geometries:
            counts[g.kind] = counts.get(g.kind, 0) + 1
        document = build_document(
            subjects,
            period,
            tracks,
            fit,
            grid,
            layer_rows,
            figures,
            warnings,
            params,
            input_count=input_count,
            excluded_count=excluded_count,
            geometries=counts,
            tz=tz or "UTC",
        )
        return RunResult(document=document, geometries=geometries)

    async def _layers(
        self,
        ctx: RunContext,
        params: HabitatParameters,
        chosen: list[LayerChoice],
        grid: hab.Grid,
        period: Period,
        warnings: list[Warning],
    ) -> tuple[dict[str, Any], list[list[Any]]]:
        """Every chosen layer on the run's grid, in the order chosen: a provider's through the
        cache, a distance from the project's features, an upload from the bucket. A layer that
        cannot be read is a warning and is left out; one without variation too."""
        session = ctx.session
        layers: dict[str, Any] = {}
        rows: list[list[Any]] = []
        provider = await configured_provider(session, "ndvi")
        elevation: Any = None
        for index, choice in enumerate(chosen):
            await ctx.progress(25 + int(index * 30 / max(1, len(chosen))), f"layer {choice.name}")
            source = choice.source
            resolution = grid.resolution_m
            fetched = False
            try:
                if source == "provider":
                    if provider is None or not getattr(provider, "raster_layers", ()):
                        raise ValueError("no environmental data provider is set up")
                    base = "elevation" if choice.name == "slope" else choice.name
                    periodic = bool(FETCHED_LAYERS[base]["periodic"])
                    data, fetched = await cached_raster(
                        session,
                        provider,  # type: ignore[arg-type]
                        base,
                        grid.bbox_wgs84,
                        grid.epsg,
                        grid.resolution_m,
                        period.time_from if periodic else None,
                        period.time_to if periodic else None,
                        ctx.project_id,
                    )
                    if choice.name == "slope":
                        if elevation is None:
                            elevation = hab.layer_from_geotiff(data, grid)
                        layer = hab.slope_from_elevation(elevation)
                    elif choice.name == "elevation":
                        elevation = hab.layer_from_geotiff(data, grid)
                        layer = elevation
                    else:
                        layer = hab.layer_from_geotiff(data, grid)
                    source_text = str(
                        getattr(provider, "raster_sources", {}).get(base)
                        or getattr(provider, "source", provider.key)
                    )
                    resolution = float(FETCHED_LAYERS[base]["resolution_m"])
                elif source == "distance":
                    feature_type = choice.feature_type or choice.name.removeprefix(DISTANCE_PREFIX)
                    shapes = (
                        await session.scalars(
                            select(func.ST_AsGeoJSON(Feature.geom)).where(
                                Feature.project_id == ctx.project_id,
                                Feature.feature_type == feature_type,
                            )
                        )
                    ).all()
                    layer = hab.distance_layer(grid, [json.loads(s) for s in shapes])
                    source_text = f"the project's {len(shapes)} {feature_type} features"
                else:
                    row = await session.scalar(
                        select(ProjectLayer).where(
                            ProjectLayer.project_id == ctx.project_id,
                            ProjectLayer.name == choice.name,
                        )
                    )
                    if row is None:
                        raise ValueError("the uploaded layer is gone")
                    layer = hab.layer_from_geotiff(
                        await project_layer_bytes(row),
                        grid,
                        categorical=row.kind == LayerKind.CATEGORICAL,
                    )
                    resolution = float(row.pixel_m)
                    source_text = f"uploaded GeoTIFF (EPSG:{row.epsg})"
            except Exception as exc:  # a provider's or a file's failure is a warning
                log.warning("habitat layer failed", layer=choice.name, error=str(exc))
                warnings.append(
                    Warning(
                        code="layer_failed",
                        text=f"The layer {choice.label} could not be read ({exc}); the run "
                        "goes on without it.",
                    )
                )
                continue
            values = np.asarray(layer.values, dtype=np.float64)
            valid = np.isfinite(values)
            coverage = float(valid.mean()) if valid.size else 0.0
            if valid.any() and coverage < SPARSE_COVERAGE:
                warnings.append(
                    Warning(
                        code="layer_sparse",
                        text=(
                            f"The layer {choice.label} has a value in {coverage:.0%} of the "
                            "grid's cells; a fix or an available point without one is left "
                            "out of the fit."
                        ),
                    )
                )
            if not valid.any() or float(np.nanstd(values)) == 0.0:
                warnings.append(
                    Warning(
                        code="layer_flat",
                        text=f"The layer {choice.label} has no variation over the run's area "
                        "and is left out: a constant cannot explain selection.",
                    )
                )
                continue
            layers[choice.name] = layer
            rows.append(
                [
                    choice.name,
                    choice.label,
                    source_text,
                    resolution,
                    int(valid.sum()),
                    round(float(np.nanmean(values)), 4),
                    round(float(np.nanstd(values)), 4),
                    "fetched now" if fetched else ("cached" if source == "provider" else ""),
                ]
            )
        return layers, rows

    def _geometries(
        self,
        tracks: list[Trajectory],
        names: dict[uuid.UUID, str],
        grid: hab.Grid,
        fit: hab.Fit,
        params: HabitatParameters,
        figures: dict[uuid.UUID, dict[str, float | None]],
    ) -> list[Geometry]:
        geometries: list[Geometry] = []
        for track in tracks:
            x, y = hab._to_utm(track.lat, track.lon, grid.epsg)
            ring = hab.mcp_ring(x, y, params.domain_quantile)
            if ring is None:
                continue
            import shapely

            hectares = shapely.Polygon(ring).area / 10_000
            figures.setdefault(track.entity_id, {})["domain_ha"] = round(hectares, 2)
            geometries.append(
                Geometry(
                    kind="domain",
                    subject_id=track.entity_id,
                    label=f"{names.get(track.entity_id, '')}: available ({hectares:.0f} ha)",
                    level=params.domain_quantile,
                    geojson={"type": "Polygon", "coordinates": [hab.ring_wgs84(ring, grid.epsg)]},
                    properties={"quantile": params.domain_quantile, "hectares": round(hectares, 2)},
                )
            )
        if fit.surface is not None:
            lat = np.concatenate([t.lat for t in tracks])
            lon = np.concatenate([t.lon for t in tracks])
            cells = hab.surface_cells(fit.surface, grid, float(np.mean(lat)), float(np.mean(lon)))
            fit.breaks = cells.breaks
            for ix, iy, value, rank in cells.cells:
                geometries.append(
                    Geometry(
                        kind="selection",
                        label=f"relative selection {value:.3g}",
                        level=rank / 4,
                        geojson={"type": "Polygon", "coordinates": [cells.grid.polygon(ix, iy)]},
                        properties={"value": value, "rank": rank},
                    )
                )
        return geometries


def _finest_m(choice: LayerChoice, *, session_layers: Any) -> float:
    if choice.source == "provider":
        base = "elevation" if choice.name == "slope" else choice.name
        return float(FETCHED_LAYERS[base]["resolution_m"])
    return DISTANCE_RESOLUTION_M


def build_document(
    subjects: list[Subject],
    period: Period,
    tracks: list[Trajectory],
    fit: hab.Fit,
    grid: hab.Grid,
    layer_rows: list[list[Any]],
    figures: dict[uuid.UUID, dict[str, float | None]],
    warnings: list[Warning],
    params: HabitatParameters,
    *,
    input_count: int,
    excluded_count: int,
    geometries: dict[str, int],
    tz: str,
) -> ResultDocument:
    """The result document: a summary per animal and for the whole, the coefficients, the
    validation per held-out animal, the layers, the two charts, the warnings and the
    provenance with the engine named."""
    summary: dict[str, Any] = {"main": {}}
    rows: list[list[Any]] = []
    boyces: list[float] = []
    for subject in subjects:
        f = figures.get(subject.id, {})
        summary["main"][str(subject.id)] = {k: f.get(k) for k in METRICS}
        rows.append([subject.name, period.key, *[f.get(k) for k in METRICS]])
        if f.get("boyce") is not None:
            boyces.append(float(f["boyce"]))  # type: ignore[arg-type]
    fleet = {
        "used_points": float(fit.used),
        "available_points": float(fit.available),
        "log_likelihood": fit.log_likelihood,
        "mean_boyce": round(sum(boyces) / len(boyces), 3) if boyces else None,
        "layers": float(len(layer_rows)),
        "grid_m": grid.resolution_m,
    }
    summary["fleet"] = fleet
    summary["scaling"] = {k: {"mean": v[0], "scale": v[1]} for k, v in fit.scaling.items()}
    summary["selection_breaks"] = fit.breaks
    summary["grid"] = {
        "epsg": grid.epsg,
        "resolution_m": grid.resolution_m,
        "cells": grid.cells,
        "bbox": list(grid.bbox_wgs84),
    }
    coefficient_rows = [
        [c.term, c.estimate, c.std_error, c.p_value, c.lower, c.upper] for c in fit.coefficients
    ]
    names = {s.id: s.name for s in subjects}
    validation_rows = [
        [names.get(f.subject_id, str(f.subject_id)), f.boyce, f.test_fixes, f.train_fixes, f.error]
        for f in fit.folds
    ]
    terms = [c for c in fit.coefficients if c.term != "const"]
    charts = [
        Chart(
            key="estimates",
            kind="bar",
            unit=None,
            series=[{"name": "estimate", "data": [[c.term, round(c.estimate, 4)] for c in terms]}],
        ),
    ]
    if fit.folds:
        charts.append(
            Chart(
                key="boyce",
                kind="line",
                unit=None,
                series=[
                    {
                        "subject": str(f.subject_id),
                        "data": [[str(i + 1), round(pe, 3)] for i, (_, pe) in enumerate(f.curve)],
                    }
                    for f in fit.folds
                    if f.curve
                ],
            )
        )
    return ResultDocument(
        module="habitat_selection",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=[period],
        summary=summary,
        tables=[
            Table(key="summary", columns=["subject", "period", *METRICS], rows=rows),
            Table(
                key="coefficients",
                columns=["term", "estimate", "std_error", "p_value", "lower", "upper"],
                rows=coefficient_rows,
            ),
            Table(
                key="validation",
                columns=["subject", "boyce", "test_fixes", "train_fixes", "error"],
                rows=validation_rows,
            ),
            Table(
                key="layers",
                columns=[
                    "name",
                    "label",
                    "source",
                    "resolution_m",
                    "cells",
                    "mean",
                    "spread",
                    "cache",
                ],
                rows=layer_rows,
            ),
        ],
        charts=charts,
        geometries=geometries,
        warnings=warnings,
        provenance=Provenance(
            module="habitat_selection",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=[period],
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=[
                "positions (device fixes, effective time and geometry, valid rows)",
                *[f"layer {r[0]}: {r[2]}" for r in layer_rows],
                ENGINE,
            ],
        ),
    )
