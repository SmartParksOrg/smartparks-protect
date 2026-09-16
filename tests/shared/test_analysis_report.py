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
    MAX_TILES,
    OSM_ATTRIBUTION,
    PRESSURE_RAMP,
    MapPicture,
    TrackLine,
    draw_map,
    extent_for,
    map_picture,
    mercator,
    metres_per_pixel,
    pressure_color,
    shapes_from_geometries,
    stitch_tiles,
    tile_grid,
)
from shared.analysis.report.render import (
    KIND_LEGEND,
    ReportInput,
    device_sections,
    fmt_figure,
    fmt_indicator,
    fmt_time,
    key_figures,
    labels_for,
    map_legend,
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


async def _no_tiles(_extent, _width):
    return None, "no tiles in tests"


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_tile_grid_covers_the_extent_within_the_tile_budget():
    extent = extent_for([(31.5, -24.9), (31.52, -24.88)], 1000, 620)
    assert extent is not None
    grid = tile_grid(extent, 1000)
    assert 0 < grid.count <= MAX_TILES
    xmin, xmax, ymin, ymax = grid.bounds
    assert (
        xmin <= extent.xmin and xmax >= extent.xmax and ymin <= extent.ymin and ymax >= extent.ymax
    )
    # a tile's pixels are at least as fine as the picture's, unless the budget coarsens them
    size_px = (xmax - xmin) / ((grid.x1 - grid.x0 + 1) * 256)
    assert size_px <= extent.width_m / 1000 * 2
    # a whole country: the budget wins and the zoom drops
    wide = extent_for([(16.0, -29.0), (33.0, -22.0)], 1000, 620)
    assert wide is not None and tile_grid(wide, 1000).count <= MAX_TILES


def test_tiles_stitch_into_one_picture_with_the_credit():
    extent = extent_for([(31.5, -24.9), (31.52, -24.88)], 1000, 620)
    assert extent is not None
    grid = tile_grid(extent, 1000)
    tiles = {(grid.x0, grid.y0): _png((200, 10, 10)), (grid.x1, grid.y1): b"not a png"}
    base = stitch_tiles(grid, tiles)
    assert base.attribution == OSM_ATTRIBUTION and base.bounds == grid.bounds
    assert base.image.size == ((grid.x1 - grid.x0 + 1) * 256, (grid.y1 - grid.y0 + 1) * 256)
    assert base.image.getpixel((1, 1)) == (200, 10, 10)
    png = draw_map(extent, base, [], [], width_px=400, height_px=300)
    assert Image.open(io.BytesIO(png)).size == (800, 600)


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
    picture = await map_picture(
        tracks, shapes, maptiler_key=None, referer="http://localhost:3000", tile_source=_no_tiles
    )
    assert picture is not None and not picture.with_base_map
    assert picture.note == "The base map is not drawn: no tiles in tests."
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
    picture = await map_picture(
        tracks, [], maptiler_key=None, referer="http://localhost:3000", tile_source=_no_tiles
    )
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


G, H = uuid.uuid4(), uuid.uuid4()


def _device_document() -> dict:
    """A device performance result of two devices, one failing (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md)."""
    days = [int((DAY0 + timedelta(days=i)).timestamp() * 1000) for i in range(30)]
    return {
        "version": 1,
        "module": "device_performance",
        "method_version": "device_performance/1",
        "subjects": [
            {
                "id": str(G),
                "name": "SP1",
                "type": "Device",
                "kind": "device",
                "tracked": "Rhino 14",
            },
            {"id": str(H), "name": "SP2", "type": "Device", "kind": "device", "tracked": None},
        ],
        "periods": [
            {
                "key": "main",
                "time_from": "2025-05-01T00:00:00+00:00",
                "time_to": "2025-05-31T00:00:00+00:00",
            }
        ],
        "summary": {
            "main": {
                str(G): {"level": "ok", "battery_v": 3.912, "fix_success": 1.0, "reboots": 0},
                str(H): {
                    "level": "critical",
                    "battery_v": 3.5,
                    "battery_slope_mv_day": -6.7,
                    "fix_success": 0.6,
                    "ttf_p90_s": 150,
                    "reboots": 1,
                    "lost_uplinks_share": 0.25,
                    "sources": ["ChirpStack"],
                },
            },
            "comparison": {},
            "levels": {
                str(G): {"battery_v": "ok", "fix_success": "ok"},
                str(H): {
                    "battery_v": "critical",
                    "battery_slope_mv_day": "warn",
                    "fix_success": "warn",
                    "lost_uplinks_share": "critical",
                },
            },
            "ranks": {str(H): {"battery_v": 1}, str(G): {"battery_v": 2}},
            "devices": {},
            "defaults": {"battery_v": "warn below 3.6 V, critical below 3.45 V"},
        },
        "tables": [
            {
                "key": "fleet",
                "columns": ["device", "level", "battery_v"],
                "rows": [["SP2", "critical", 3.5], ["SP1", "ok", 3.912]],
            },
            {
                "key": "reboots",
                "columns": ["device", "time", "reason"],
                "rows": [["SP2", "2025-05-11T00:00:00+00:00", "watchdog"]],
            },
            {
                "key": "errors",
                "columns": ["device", "flag", "statuses", "share", "level"],
                "rows": [],
            },
        ],
        "charts": [
            {
                "key": "battery",
                "kind": "line",
                "unit": "V",
                "series": [
                    {"subject": str(G), "period": "main", "data": [[d, 3.9] for d in days]},
                    {
                        "subject": str(H),
                        "period": "main",
                        "data": [[d, 3.7 - 0.0067 * i] for i, d in enumerate(days)],
                    },
                ],
            },
            {
                "key": "time_to_fix",
                "kind": "bar",
                "unit": "attempts",
                "series": [
                    {"subject": str(H), "period": "main", "data": [["<15 s", 2], ["120 s", 40]]}
                ],
            },
        ],
        "geometries": {"coverage": 2, "gateway": 1},
        "warnings": [],
        "provenance": {"computed_at": "2026-09-16T13:02:00+00:00"},
    }


def test_the_device_report_leads_with_the_fleet_and_folds_the_charts_per_device():
    document = _device_document()
    inp = _input(
        document,
        module="device_performance",
        parameters={
            "device_ids": [str(G), str(H)],
            "time_from": "2025-05-01T00:00:00+00:00",
            "time_to": "2025-05-31T00:00:00+00:00",
            "max_speed_mps": 15,
        },
        run_name=None,
    )
    labels = labels_for("device_performance", document)
    assert labels[str(G)] == "SP1" and labels["lost_uplinks_share"] == "Lost uplinks"
    assert dict(settings_rows(inp, labels))["Devices"] == "SP1, SP2"
    figures = key_figures(inp, labels)
    assert figures["first"] == "Device" and figures["columns"][0] == "Battery (V)"
    # the failing device first, with its level dots, the tracked animal as the note
    assert [row["name"] for row in figures["rows"]] == ["SP2", "SP1"]
    assert figures["rows"][0]["level"] == "critical" and figures["rows"][1]["note"] == "Rhino 14"
    assert figures["rows"][0]["cells"][0] == {"text": "3.50", "level": "critical"}
    assert figures["rows"][0]["cells"][8] == {"text": "60%", "level": "warn"}
    assert figures["rows"][0]["cells"][9] == {"text": "2 min", "level": None}
    # two devices: the table stands on its side, a row per indicator, the devices as columns
    assert figures["transposed"]["columns"] == ["SP2", "SP1"]
    assert figures["transposed"]["levels"] == ["critical", "ok"]
    assert figures["transposed"]["rows"][0]["label"] == "Battery (V)"
    assert figures["transposed"]["rows"][0]["cells"][1] == {"text": "3.91", "level": "ok"}
    assert figures["columns"][1] == "Slope (mV/day)"  # the short heads for paper
    assert fmt_indicator(None, "x") == "-" and fmt_indicator(["a", "b"], "sources") == "a, b"
    sections = device_sections(inp, labels, {str(G): "#52735E", str(H): "#D9825F"})
    assert [s["name"] for s in sections] == ["SP2", "SP1"]
    failing = sections[0]
    assert [c["title"] for c in failing["cards"]] == ["Health", "GNSS", "Network"]
    # a missing comparison figure adds no brackets
    assert failing["cards"][0]["rows"][0]["text"] == "3.50"
    assert failing["cards"][0]["rows"][0] == {
        "label": "Battery (V)",
        "text": "3.50",
        "level": "critical",
    }
    assert len(failing["charts"]) == 2 and len(sections[1]["charts"]) == 1  # SP1 has no time to fix
    html = render_html(inp)
    assert "Device performance analysis" in html and 'class="dot lvl-critical"' in html
    assert "The thresholds behind the levels" in html and "warn below 3.6 V" in html
    assert "watchdog" in html and ">Fleet<" not in html  # the fleet table is the key figures
    # the legend under the map: the two devices in their colours, the hulls and the gateways
    legend = map_legend(document, {str(G): "#52735E", str(H): "#D9825F"})
    assert [e["kind"] for e in legend] == ["swatch", "swatch", "outline", "marker"]
    assert legend[0]["text"] == "SP1" and legend[0]["color"] == "#52735E"
    assert legend[2]["text"].startswith("Coverage of the fixes")
    movement = map_legend(_document(), {str(A): "#52735E", str(B): "#D9825F"})
    assert [e["kind"] for e in movement] == ["swatch", "swatch", "outline"]
    assert movement[2]["text"].startswith("MCP 95%")
    grazing = map_legend({"subjects": [], "geometries": {"area": 3}}, {})
    assert grazing == [{"kind": "ramp", "colors": list(PRESSURE_RAMP), "text": KIND_LEGEND["area"]}]
    picture = MapPicture(png=_png((200, 10, 10)), with_base_map=False)
    with_map = render_html(_input(document, module="device_performance", map=picture))
    assert 'class="legend"' in with_map and "Gateways heard" in with_map
    assert render_document(inp).pages


def test_a_gateway_point_draws_as_a_marker_sized_by_its_share():
    square = Polygon([(31.5, -24.9), (31.52, -24.9), (31.52, -24.88), (31.5, -24.88)])
    shapes = shapes_from_geometries(
        [
            {"kind": "coverage", "subject_id": str(G), "label": "SP1", "geojson": mapping(square)},
            {
                "kind": "gateway",
                "subject_id": str(G),
                "label": "Hill gateway: 60%",
                "level": 0.6,
                "geojson": {"type": "Point", "coordinates": [31.51, -24.89]},
            },
        ],
        {str(G): "#52735E"},
    )
    assert [s.kind for s in shapes] == ["coverage", "gateway"] and shapes[1].level == 0.6
    extent = extent_for([(31.5, -24.9), (31.52, -24.88)], 400, 300)
    assert extent is not None
    png = draw_map(extent, None, [], shapes, width_px=400, height_px=300)
    assert Image.open(io.BytesIO(png)).size == (800, 600)
