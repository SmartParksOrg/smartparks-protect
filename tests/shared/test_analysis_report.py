"""The PDF report of an analysis run (decision D211): the charts, the map picture without a
base map, the wide table turned on its side, and a whole document rendered to a PDF."""

import io
import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from shapely.geometry import Polygon, mapping

from shared.analysis.report.charts import chart_svg, series_name
from shared.analysis.report.mapimage import (
    TrackLine,
    draw_map,
    extent_for,
    map_picture,
    mercator,
    metres_per_pixel,
    pressure_color,
    shapes_from_geometries,
)
from shared.analysis.report.render import (
    ReportInput,
    fmt_figure,
    fmt_time,
    key_figures,
    labels_for,
    render_document,
    render_html,
    render_pdf,
    settings_rows,
    table_block,
)

A, B = uuid.uuid4(), uuid.uuid4()
DAY0 = datetime(2025, 5, 1, tzinfo=UTC)


def _document() -> dict:
    days = [int((DAY0 + timedelta(days=i)).timestamp() * 1000) for i in range(30)]
    return {
        "version": 1,
        "module": "movement",
        "method_version": "movement/1",
        "subjects": [
            {"id": str(A), "name": "Rhino 14", "type": "Animal"},
            {"id": str(B), "name": "Rhino 15", "type": "Animal"},
        ],
        "periods": [
            {
                "key": "main",
                "time_from": "2025-05-01T00:00:00+00:00",
                "time_to": "2025-05-31T00:00:00+00:00",
            },
            {
                "key": "comparison",
                "time_from": "2025-04-01T00:00:00+00:00",
                "time_to": "2025-05-01T00:00:00+00:00",
            },
        ],
        "summary": {
            "main": {
                str(A): {
                    "distance_km": 54.2,
                    "daily_distance_km": 1.8,
                    "stationary_share": 0.4,
                    "fixes": 3000,
                },
                str(B): {
                    "distance_km": 41.0,
                    "daily_distance_km": 1.4,
                    "stationary_share": 0.5,
                    "fixes": 2800,
                },
            },
            "comparison": {str(A): {"distance_km": 50.0, "daily_distance_km": 1.7, "fixes": 2900}},
        },
        "tables": [
            {
                "key": "summary",
                "columns": [
                    "subject",
                    "period",
                    "fixes",
                    "days_with_data",
                    "distance_km",
                    "a",
                    "b",
                    "c",
                    "d",
                    "e",
                ],
                "rows": [
                    [str(A), "main", 3000, 30, 54.2, 1, 2, 3, 4, 5],
                    [str(B), "main", 2800, 29, 41.0, 1, 2, 3, 4, 5],
                ],
            },
            {"key": "small", "columns": ["subject", "fixes"], "rows": [[str(A), 3000]]},
        ],
        "charts": [
            {
                "key": "daily_distance",
                "kind": "line",
                "unit": "km",
                "series": [
                    {
                        "subject": str(A),
                        "period": "main",
                        "data": [[d, 1 + (i % 3)] for i, d in enumerate(days)],
                    },
                    {"subject": str(A), "period": "comparison", "data": [[d, 1.5] for d in days]},
                ],
            },
            {
                "key": "speed_histogram",
                "kind": "bar",
                "unit": "fixes",
                "series": [{"subject": str(A), "data": [["<0.01", 5], ["0.1", 9]]}],
            },
            {
                "key": "turning",
                "kind": "rose",
                "unit": "steps",
                "series": [
                    {"subject": str(A), "data": [[str(d), 3] for d in range(-160, 180, 40)]}
                ],
            },
            {
                "key": "day_night",
                "kind": "stacked",
                "unit": "km",
                "series": [
                    {"name": "day", "data": [[str(A), 40], [str(B), 30]]},
                    {"name": "night", "data": [[str(A), 14], [str(B), 11]]},
                ],
            },
        ],
        "geometries": {"mcp": 2},
        "warnings": [
            {
                "code": "missing_fixes",
                "level": "warning",
                "subject_id": str(A),
                "text": "68% of the fixes are missing.",
            }
        ],
        "provenance": {"computed_at": "2026-09-15T13:02:00+00:00"},
    }


def _input(document: dict, **overrides) -> ReportInput:
    values = {
        "document": document,
        "parameters": {
            "entity_ids": [str(A), str(B)],
            "time_from": "2025-05-01T00:00:00+00:00",
            "time_to": "2025-05-31T00:00:00+00:00",
            "comparison": {
                "time_from": "2025-04-01T00:00:00+00:00",
                "time_to": "2025-05-01T00:00:00+00:00",
            },
            "gap_hours": 4,
            "methods": ["mcp", "kde"],
        },
        "module": "movement",
        "run_name": "May 2025",
        "project_name": "Demo park",
        "timezone": "Africa/Johannesburg",
        "created_by": "Ada",
        "created_at": datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        "computed_at": datetime(2026, 9, 15, 10, 1, tzinfo=UTC),
        "version": "v2.6.0",
    }
    values.update(overrides)
    return ReportInput(**values)


def test_the_labels_name_subjects_and_the_settings_read_as_words():
    document = _document()
    labels = labels_for("movement", document)
    assert labels[str(A)] == "Rhino 14" and labels["distance_km"] == "Distance (km)"
    rows = dict(settings_rows(_input(document), labels))
    assert rows["Subjects"] == "Rhino 14, Rhino 15"
    assert rows["Period"] == "1 May 2025, 02:00 (SAST) to 31 May 2025, 02:00 (SAST)"
    assert rows["Compared with"].startswith("1 Apr 2025")
    assert rows["Home range methods"] == "mcp, kde" and rows["Gap threshold (hours)"] == "4"
    assert fmt_time("2026-09-15T12:00:00+00:00", "UTC") == "15 Sep 2026, 12:00"


def test_key_figures_carry_the_comparison_in_brackets():
    document = _document()
    figures = key_figures(_input(document), labels_for("movement", document))
    assert figures["first"] == "Subject" and figures["columns"][0] == "Distance (km)"
    rhino_14 = figures["rows"][0]
    assert rhino_14["name"] == "Rhino 14" and rhino_14["cells"][0] == "54.2 km (50.0 km)"
    assert rhino_14["cells"][3] == "40% (-)"  # no comparison figure for the share
    assert figures["rows"][1]["cells"][0] == "41.0 km"  # no comparison for this subject
    assert (
        fmt_figure(0.4, "%") == "40%"
        and fmt_figure(2, "#") == "#2"
        and fmt_figure(None, "km") == "-"
    )
    assert fmt_figure(123.4, "km") == "123 km" and fmt_figure(12.34, "km") == "12.3 km"


def test_a_wide_table_with_few_rows_is_turned_on_its_side():
    document = _document()
    labels = labels_for("movement", document)
    wide = table_block(document["tables"][0], labels)
    assert wide["wide"] and wide["columns"] == [
        "",
        "Rhino 14 · This period",
        "Rhino 15 · This period",
    ]
    assert wide["rows"][0] == ["Fixes", "3000", "2800"]
    assert wide["rows"][2] == ["Distance (km)", "54.2", "41"]
    small = table_block(document["tables"][1], labels)
    assert not small["wide"] and small["rows"] == [["Rhino 14", "3000"]]


def test_every_chart_kind_draws_as_svg_with_the_subjects_names():
    document = _document()
    labels = labels_for("movement", document)
    colors = {str(A): "#52735E", str(B): "#D9825F"}
    for chart in document["charts"]:
        svg = chart_svg(chart, labels, colors)
        assert svg.lstrip().startswith("<?xml") and "<svg" in svg
    stacked = chart_svg(document["charts"][3], labels, colors)
    assert "Rhino 14" in stacked and str(A) not in stacked  # the category is the name, not the id
    assert series_name({"subject": str(A), "period": "comparison"}, labels) == "Rhino 14 · before"
    assert series_name({"name": "day"}, labels) == "day"


def test_the_extent_fits_the_points_and_the_zoom_matches_the_pixels():
    extent = extent_for([(31.5, -24.9), (31.52, -24.88)], 1000, 620)
    assert extent is not None
    x0, y0 = mercator(31.5, -24.9)
    x1, y1 = mercator(31.52, -24.88)
    assert extent.xmin < x0 and extent.xmax > x1 and extent.ymin < y0 and extent.ymax > y1
    assert math.isclose(extent.width_m, 1000 * metres_per_pixel(extent.zoom), rel_tol=1e-9)
    assert extent_for([], 100, 100) is None
    assert pressure_color(None) == "#E7EDE8" and pressure_color(2.5) == "#B86B5C"


@pytest.mark.asyncio
async def test_the_map_draws_without_a_base_map_and_says_so():
    ring = Polygon([(31.5, -24.9), (31.52, -24.9), (31.52, -24.88), (31.5, -24.88)])
    shapes = shapes_from_geometries(
        [
            {
                "kind": "mcp",
                "subject_id": A,
                "label": "MCP",
                "level": 0.95,
                "geojson": mapping(ring),
            },
            {
                "kind": "area",
                "subject_id": None,
                "label": "Camp",
                "level": 1.4,
                "geojson": mapping(ring.buffer(0.01)),
            },
        ],
        {str(A): "#52735E"},
    )
    assert [s.kind for s in shapes] == ["area", "mcp"]  # the larger first
    assert shapes[0].color == "#52735E"  # relative pressure 1.4 is the fourth step
    tracks = [
        TrackLine(
            lon=[31.5, 31.51, 31.52], lat=[-24.9, -24.89, -24.88], color="#52735E", label="Rhino 14"
        )
    ]
    picture = await map_picture(tracks, shapes, maptiler_key=None, referer="http://localhost:3000")
    assert picture is not None and not picture.with_base_map and "no map key" in picture.note
    image = Image.open(io.BytesIO(picture.png))
    assert image.width == 2000 and image.height == 1240
    extent = extent_for([(31.5, -24.9), (31.52, -24.88)], 1000, 620)
    assert extent is not None
    png = draw_map(extent, None, tracks, [], width_px=400, height_px=300)
    assert Image.open(io.BytesIO(png)).size == (800, 600)


@pytest.mark.asyncio
async def test_a_document_renders_to_a_pdf_of_several_pages():
    document = _document()
    tracks = [TrackLine(lon=[31.5, 31.51], lat=[-24.9, -24.89], color="#52735E", label="Rhino 14")]
    picture = await map_picture(tracks, [], maptiler_key=None, referer="http://localhost:3000")
    inp = _input(document, map=picture)
    html = render_html(inp)
    assert "May 2025" in html and "Demo park" in html and "Rhino 15" in html
    assert "Read with care" in html and "68% of the fixes are missing." in html
    assert "What these figures can and cannot say" in html
    pdf = render_pdf(inp)
    assert pdf.startswith(b"%PDF")
    assert len(render_document(inp).pages) >= 3
    # a grazing document without a map or charts still renders
    grazing = {
        **document,
        "module": "grazing",
        "charts": [],
        "summary": {
            "areas": [{"id": str(A), "name": "Camp 1", "kind": "zone", "hectares": 12.5}],
            "main": {
                str(A): {
                    "animal_days_per_ha": 0.31,
                    "relative_pressure": 1.2,
                    "pressure_rank": 1,
                    "use_days": 20,
                    "rest_days": 10,
                }
            },
            "herd": {"main": {"animal_hours": 720, "inside_share": 0.8}},
        },
    }
    bare = render_pdf(_input(grazing, module="grazing", run_name=None, map=None))
    assert bare.startswith(b"%PDF")
