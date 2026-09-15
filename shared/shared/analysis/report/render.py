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
from shared.analysis.report.mapimage import MapPicture

TEMPLATES = Path(__file__).parent / "templates"
ASSETS = Path(__file__).parent / "assets"
CHART_WIDTH_IN = 3.4
CHART_HEIGHT_IN = 2.2

MODULE_LABELS = {"movement": "Movement", "grazing": "Grazing"}

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
#: The figures on a movement subject's card, with their unit (the frontend's card metrics).
MOVEMENT_KEY_FIGURES: list[tuple[str, str]] = [
    ("distance_km", "km"),
    ("daily_distance_km", "km/day"),
    ("median_speed_mps", "m/s"),
    ("stationary_share", "%"),
    ("mcp95_ha", "ha"),
    ("kde95_ha", "ha"),
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
OPTION_LABELS: list[tuple[str, str]] = [
    ("gap_hours", "Gap threshold (hours)"),
    ("max_speed_mps", "Maximum plausible speed (m/s)"),
    ("cell_m", "Grid cell (m)"),
    ("revisit_hours", "Revisit after (hours)"),
    ("methods", "Home range methods"),
    ("kde_bandwidth_m", "KDE bandwidth (m)"),
    ("weighting", "Weighting"),
    ("weight_key", "Attribute key"),
    ("min_absence_hours", "New visit after (hours away)"),
    ("rest_threshold_hours", "Rest day at or below (animal-hours)"),
]
MOVEMENT_LIMITATIONS = [
    "Distance from fixes underestimates the path between them; a coarser sampling means a "
    "shorter apparent distance. The sampling interval stands next to the distance for that "
    "reason.",
    "Speed is the mean over a step, not an instantaneous speed.",
    "The KDE is an estimate of space use that depends on the bandwidth and the grid; its "
    "isopleths are unions of cells, not smooth contours.",
    "The MCP includes ground never visited between far fixes.",
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
    labels = dict(GRAZING_LABELS if module == "grazing" else MOVEMENT_LABELS)
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
        return "-" if value is None else str(value)
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
    if p.get("seasons") is True:
        rows.append(("Seasons", "rows per season"))
    for key, label in OPTION_LABELS:
        value = p.get(key)
        if value is None or value == "" or value == []:
            continue
        rows.append((label, ", ".join(map(str, value)) if isinstance(value, list) else str(value)))
    return rows


def key_figures(inp: ReportInput, labels: dict[str, str]) -> dict[str, Any]:
    """The cards as one table: a row per subject (movement) or per area (grazing), a column
    per figure, the comparison in brackets when the run has one."""
    document = inp.document
    summary = document.get("summary", {})
    has_comparison = any(p.get("key") == "comparison" for p in document.get("periods", []))
    main = summary.get("main") or {}
    before = summary.get("comparison") or {}
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
        # the first two cells name the row (subject and period, area and period)
        heads = [" · ".join(c for c in r[:2] if c) for r in rows]
        body = [
            [columns[i], *[r[i] if i < len(r) else "" for r in rows]]
            for i in range(2, len(columns))
        ]
        return {"title": title, "columns": ["", *heads], "rows": body, "wide": True}
    return {"title": title, "columns": columns, "rows": rows, "wide": len(columns) > WIDE_COLUMNS}


def render_html(inp: ReportInput) -> str:
    document = inp.document
    labels = labels_for(inp.module, document)
    colors = subject_colors(document)
    charts = [
        {
            "title": labels.get(c["key"], c["key"]),
            "svg": _data_uri(
                chart_svg(c, labels, colors, width_in=CHART_WIDTH_IN, height_in=CHART_HEIGHT_IN),
                "image/svg+xml",
            ),
        }
        for c in document.get("charts", [])
    ]
    tables = [table_block(t, labels) for t in document.get("tables", [])]
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
            {"png": _data_uri(inp.map.png, "image/png"), "note": inp.map.note} if inp.map else None
        ),
        charts=charts,
        tables=tables,
        limitations=GRAZING_LIMITATIONS if inp.module == "grazing" else MOVEMENT_LIMITATIONS,
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
