"""Every writer produces a valid document from streamed rows; XLSX splits at the Excel limit."""

import csv
import io
import json
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq
import pytest
from openpyxl import load_workbook
from shapely import from_wkb
from shapely.geometry import LineString, Polygon

from shared.enums import ExportFormat
from shared.exports.writers import (
    CsvWriter,
    GeoJsonWriter,
    GeoParquetWriter,
    GpxWriter,
    JsonWriter,
    XlsxWriter,
    make_writer,
)

COLUMNS = ["time", "latitude", "longitude", "altitude_m", "name", "attributes"]
ROWS = [
    {
        "time": "2026-04-01T02:00:00+02:00",
        "time_utc": "2026-04-01T00:00:00.000Z",
        "latitude": -24.9,
        "longitude": 31.5,
        "altitude_m": 300.5,
        "name": "Rhino 14",
        "attributes": {"fix_type": 3},
        "track_key": "a",
        "track_name": "Rhino 14",
    },
    {
        "time": "2026-04-01T02:10:00+02:00",
        "time_utc": "2026-04-01T00:10:00.000Z",
        "latitude": -24.91,
        "longitude": 31.51,
        "altitude_m": None,
        "name": 'Rhino "14"',
        "attributes": {},
        "track_key": "a",
        "track_name": "Rhino 14",
    },
    {
        "time": "2026-04-01T02:20:00+02:00",
        "time_utc": "2026-04-01T00:20:00.000Z",
        "latitude": -24.92,
        "longitude": 31.52,
        "altitude_m": 301.0,
        "name": "Elephant & co",
        "attributes": {"a": [1, 2]},
        "track_key": "b",
        "track_name": "Elephant & co",
    },
]
META = {"generator": "test"}


def _write(writer_cls, *args):
    stream = io.BytesIO()
    writer = writer_cls(stream, COLUMNS, *args)
    for row in ROWS:
        writer.write_row(row)
    writer.finish()
    return stream.getvalue()


def test_csv_quotes_and_serializes_nested_values():
    text = _write(CsvWriter).decode()
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == COLUMNS
    assert rows[2][4] == 'Rhino "14"' and rows[2][3] == ""
    assert json.loads(rows[1][5]) == {"fix_type": 3}


def test_json_is_one_document_with_metadata():
    document = json.loads(_write(JsonWriter, META))
    assert document["metadata"] == META and document["columns"] == COLUMNS
    assert len(document["rows"]) == 3 and document["rows"][2]["attributes"] == {"a": [1, 2]}
    assert "track_key" not in document["rows"][0]  # only listed columns are written


def test_geojson_points_with_properties():
    document = json.loads(_write(GeoJsonWriter, META))
    assert document["type"] == "FeatureCollection" and len(document["features"]) == 3
    feature = document["features"][0]
    assert feature["geometry"] == {"type": "Point", "coordinates": [31.5, -24.9]}
    assert feature["properties"]["name"] == "Rhino 14" and "latitude" not in feature["properties"]


def test_gpx_one_track_per_key_with_utc_times():
    root = ET.fromstring(_write(GpxWriter, META))
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    tracks = root.findall("g:trk", ns)
    assert [t.find("g:name", ns).text for t in tracks] == ["Rhino 14", "Elephant & co"]
    points = tracks[0].findall("g:trkseg/g:trkpt", ns)
    assert len(points) == 2 and points[0].get("lat") == "-24.9"
    assert points[0].find("g:time", ns).text == "2026-04-01T00:00:00.000Z"
    assert points[0].find("g:ele", ns).text == "300.5" and points[1].find("g:ele", ns) is None


def test_xlsx_splits_sheets_at_the_row_limit():
    stream = io.BytesIO()
    writer = XlsxWriter(stream, COLUMNS, max_rows=3)  # header plus two rows per sheet
    for row in ROWS:
        writer.write_row(row)
    writer.finish()
    workbook = load_workbook(io.BytesIO(stream.getvalue()), read_only=True)
    assert workbook.sheetnames == ["data", "data_2"] and writer.sheets == 2
    first = list(workbook["data"].iter_rows(values_only=True))
    second = list(workbook["data_2"].iter_rows(values_only=True))
    assert first[0] == tuple(COLUMNS) and second[0] == tuple(COLUMNS)
    assert len(first) == 3 and len(second) == 2
    assert first[1][4] == "Rhino 14" and json.loads(first[1][5]) == {"fix_type": 3}


def test_geoparquet_points_typed_columns_and_geo_metadata():
    """GeoParquet 1.1.0 (decision D312): a point per row from latitude and longitude, the
    `geo` metadata with the types seen and their bounding box, typed columns, and the
    export's own metadata under its key."""
    stream = io.BytesIO()
    writer = GeoParquetWriter(stream, COLUMNS, {**META, "timezone": "Africa/Johannesburg"})
    for row in ROWS:
        writer.write_row(row)
    writer.write_row({**ROWS[0], "latitude": None})  # a moment without a position
    writer.finish()
    table = pq.read_table(io.BytesIO(stream.getvalue()))
    assert table.column_names == ["time", "altitude_m", "name", "attributes", "geometry"]
    assert str(table.schema.field("time").type) == "timestamp[us, tz=Africa/Johannesburg]"
    assert str(table.schema.field("altitude_m").type) == "double"
    rows = table.to_pylist()
    assert rows[0]["time"].isoformat() == "2026-04-01T02:00:00+02:00"
    assert rows[1]["altitude_m"] is None and rows[2]["altitude_m"] == 301.0
    assert json.loads(rows[2]["attributes"]) == {"a": [1, 2]}
    assert from_wkb(rows[0]["geometry"]).coords[0] == (31.5, -24.9)
    assert rows[3]["geometry"] is None
    # the Arrow schema carries the metadata as the file opened (points are known then), the
    # file's own footer the complete one with the bounding box
    geo = json.loads(table.schema.metadata[b"geo"])
    assert geo["version"] == "1.1.0" and geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"] == {"encoding": "WKB", "geometry_types": ["Point"]}
    footer = json.loads(pq.read_metadata(io.BytesIO(stream.getvalue())).metadata[b"geo"])
    column = footer["columns"]["geometry"]
    assert column["encoding"] == "WKB" and column["geometry_types"] == ["Point"]
    assert column["bbox"] == [31.5, -24.92, 31.52, -24.9]
    own = json.loads(table.schema.metadata[b"smartparks_protect"])
    assert own["generator"] == "test" and own["timezone"] == "Africa/Johannesburg"


def test_geoparquet_takes_shapes_and_infers_a_metric_column():
    """A run's geometries come as shapely shapes under `geometry`; a column the type table
    does not name takes the type of its first value, and a later value that does not fit
    fails the export rather than being dropped."""
    columns = ["label", "m_battery_voltage", "s_mode", "geometry"]
    stream = io.BytesIO()
    writer = GeoParquetWriter(stream, columns, META)
    writer.write_row(
        {
            "label": "North block",
            "m_battery_voltage": 3.6,
            "s_mode": None,
            "geometry": Polygon([(4.6, 52.5), (4.61, 52.5), (4.61, 52.51), (4.6, 52.5)]),
        }
    )
    writer.write_row(
        {
            "label": "Road",
            "m_battery_voltage": 4,
            "s_mode": {"a": 1},
            "geometry": LineString([(4.6, 52.5), (4.7, 52.6)]),
        }
    )
    writer.finish()
    table = pq.read_table(io.BytesIO(stream.getvalue()))
    assert str(table.schema.field("m_battery_voltage").type) == "double"
    assert str(table.schema.field("s_mode").type) == "string"
    assert table.to_pylist()[1]["s_mode"] == '{"a":1}'
    opened = json.loads(table.schema.metadata[b"geo"])["columns"]["geometry"]
    assert opened["geometry_types"] == []  # not known when the file opened
    geo = json.loads(pq.read_metadata(io.BytesIO(stream.getvalue())).metadata[b"geo"])
    column = geo["columns"]["geometry"]
    assert column["geometry_types"] == ["LineString", "Polygon"]
    assert column["bbox"] == [4.6, 52.5, 4.7, 52.6]

    bad = GeoParquetWriter(io.BytesIO(), columns, META)
    bad.write_row({"label": "a", "m_battery_voltage": 3.6, "s_mode": None, "geometry": None})
    bad.write_row({"label": "b", "m_battery_voltage": "low", "s_mode": None, "geometry": None})
    with pytest.raises(ValueError):
        bad.finish()


def test_geoparquet_without_rows_is_still_a_valid_file():
    stream = io.BytesIO()
    GeoParquetWriter(stream, COLUMNS, META).finish()
    table = pq.read_table(io.BytesIO(stream.getvalue()))
    assert table.num_rows == 0 and table.column_names[-1] == "geometry"
    geo = json.loads(pq.read_metadata(io.BytesIO(stream.getvalue())).metadata[b"geo"])
    assert geo["columns"]["geometry"]["geometry_types"] == []
    assert "bbox" not in geo["columns"]["geometry"]


def test_factory_covers_every_format():
    for export_format in ExportFormat:
        writer = make_writer(export_format, io.BytesIO(), COLUMNS, META)
        writer.write_row(ROWS[0])
        writer.finish()
