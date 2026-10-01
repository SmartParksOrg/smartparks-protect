"""Streaming writers: rows in, bytes out, never the whole dataset in memory (architecture 13.8).

Every writer takes a binary file object and a column list, gets rows as dicts in column order,
and writes them as they come. XLSX is the exception in spirit: openpyxl's write-only mode
streams rows to a temporary zip, but the file is only complete after `finish()`.
"""

import csv
import io
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Protocol
from xml.sax.saxutils import escape

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from shapely import to_wkb
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from shared.enums import ExportFormat

EXCEL_MAX_ROWS = 1_048_576  # per sheet, header included; enforced by splitting (decision D40)

CONTENT_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.JSON: "application/json",
    ExportFormat.GEOJSON: "application/geo+json",
    ExportFormat.GPX: "application/gpx+xml",
    ExportFormat.PARQUET: "application/vnd.apache.parquet",  # the media type the spec names
}

# GeoParquet (decision D312): the specification version written, the name of the geometry
# column (the default readers look for), the rows per row group, and the key the export's
# own metadata (generator, parameters, timezone, metrics) travels under in the file.
GEOPARQUET_VERSION = "1.1.0"
GEOMETRY_COLUMN = "geometry"
ROW_GROUP_ROWS = 10_000
EXPORT_METADATA_KEY = "smartparks_protect"

Row = Mapping[str, Any]


class Writer(Protocol):
    def write_row(self, row: Row) -> None: ...

    def finish(self) -> None: ...


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _cell(value: Any) -> Any:
    """Cell values for CSV and XLSX: JSON for nested data, text for identifiers."""
    if isinstance(value, dict | list):
        return json.dumps(value, default=_json_default, separators=(",", ":"))
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


class CsvWriter:
    def __init__(self, stream: BinaryIO, columns: list[str]) -> None:
        self._text = io.TextIOWrapper(stream, encoding="utf-8", newline="", write_through=True)
        self._writer = csv.writer(self._text)
        self._columns = columns
        self._writer.writerow(columns)

    def write_row(self, row: Row) -> None:
        self._writer.writerow([_cell(row.get(c)) for c in self._columns])

    def finish(self) -> None:
        self._text.flush()
        self._text.detach()


class JsonWriter:
    """`{"metadata": {...}, "rows": [ ... ]}` with the rows streamed one by one."""

    def __init__(self, stream: BinaryIO, columns: list[str], metadata: dict[str, Any]) -> None:
        self._stream = stream
        self._columns = columns
        self._first = True
        head = json.dumps({"metadata": metadata, "columns": columns}, default=_json_default)
        self._stream.write(head[:-1].encode() + b', "rows": [')

    def write_row(self, row: Row) -> None:
        if not self._first:
            self._stream.write(b",")
        self._first = False
        record = {c: row.get(c) for c in self._columns}
        self._stream.write(json.dumps(record, default=_json_default).encode())

    def finish(self) -> None:
        self._stream.write(b"]}")


class GeoJsonWriter:
    """FeatureCollection of points; `latitude` and `longitude` become the geometry, the other
    columns the properties."""

    def __init__(self, stream: BinaryIO, columns: list[str], metadata: dict[str, Any]) -> None:
        self._stream = stream
        self._columns = [c for c in columns if c not in ("latitude", "longitude")]
        self._first = True
        head = json.dumps(
            {"type": "FeatureCollection", "metadata": metadata}, default=_json_default
        )
        self._stream.write(head[:-1].encode() + b', "features": [')

    def write_row(self, row: Row) -> None:
        if not self._first:
            self._stream.write(b",")
        self._first = False
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
            "properties": {c: row.get(c) for c in self._columns},
        }
        self._stream.write(json.dumps(feature, default=_json_default).encode())

    def finish(self) -> None:
        self._stream.write(b"]}")


class GpxWriter:
    """One track per `track_key` (entity or device), one segment each; rows must arrive grouped
    by track key and ordered by time. Positions only."""

    def __init__(self, stream: BinaryIO, columns: list[str], metadata: dict[str, Any]) -> None:
        self._stream = stream
        self._track: str | None = None
        self._stream.write(
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<gpx version="1.1" creator="Smart Parks Protect" '
            b'xmlns="http://www.topografix.com/GPX/1/1">\n'
        )
        self._stream.write(
            f"<metadata><desc>{escape(json.dumps(metadata, default=_json_default))}</desc>"
            f"</metadata>\n".encode()
        )

    def write_row(self, row: Row) -> None:
        track = str(row.get("track_key") or "track")
        if track != self._track:
            if self._track is not None:
                self._stream.write(b"</trkseg></trk>\n")
            name = escape(str(row.get("track_name") or track))
            self._stream.write(f"<trk><name>{name}</name><trkseg>\n".encode())
            self._track = track
        point = f'<trkpt lat="{row["latitude"]}" lon="{row["longitude"]}">'
        if row.get("altitude_m") is not None:
            point += f"<ele>{row['altitude_m']}</ele>"
        time = row.get("time_utc")
        if time is not None:
            point += f"<time>{time}</time>"
        self._stream.write((point + "</trkpt>\n").encode())

    def finish(self) -> None:
        if self._track is not None:
            self._stream.write(b"</trkseg></trk>\n")
        self._stream.write(b"</gpx>\n")


class XlsxWriter:
    """Write-only workbook; a new sheet starts when a sheet would exceed the Excel row limit,
    so nothing is ever cut off silently."""

    def __init__(
        self, stream: BinaryIO, columns: list[str], max_rows: int = EXCEL_MAX_ROWS
    ) -> None:
        self._stream = stream
        self._columns = columns
        self._max_rows = max_rows
        self._workbook = Workbook(write_only=True)
        self._sheets = 0
        self._rows_in_sheet = 0
        self._sheet = self._new_sheet()

    def _new_sheet(self) -> Any:
        self._sheets += 1
        title = "data" if self._sheets == 1 else f"data_{self._sheets}"
        sheet = self._workbook.create_sheet(title)
        header = [WriteOnlyCell(sheet, value=c) for c in self._columns]
        sheet.append(header)
        self._rows_in_sheet = 1
        return sheet

    def write_row(self, row: Row) -> None:
        if self._rows_in_sheet >= self._max_rows:
            self._sheet = self._new_sheet()
        self._sheet.append([_cell(row.get(c)) for c in self._columns])
        self._rows_in_sheet += 1

    @property
    def sheets(self) -> int:
        return self._sheets

    def finish(self) -> None:
        self._workbook.save(self._stream)


@dataclass(frozen=True)
class _Column:
    """How one column reaches the Parquet file: its Arrow type and the conversion of a row's
    value into it. A value the conversion cannot take raises, so a file is never written with
    a value silently dropped."""

    type: Any
    convert: Callable[[Any], Any]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict | list):
        return json.dumps(value, default=_json_default, separators=(",", ":"))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _boolean(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise TypeError(f"{value!r} is not a boolean")


STRING = _Column(pa.string(), _text)
FLOAT = _Column(pa.float64(), lambda value: None if value is None else float(value))
INTEGER = _Column(pa.int64(), lambda value: None if value is None else int(value))
BOOLEAN = _Column(pa.bool_(), _boolean)
TIMESTAMP_UTC = _Column(pa.timestamp("us", tz="UTC"), _timestamp)

# The columns of the datasets that export as GeoParquet (positions, records and the geometries
# of an analysis run), typed by name; `time` takes the export's zone and a column not named
# here (a metric or state field of the records export) is typed by its first value.
COLUMN_TYPES: dict[str, _Column] = {
    "time_utc": TIMESTAMP_UTC,
    "original_time": TIMESTAMP_UTC,
    "effective_time": TIMESTAMP_UTC,
    "curated_at": TIMESTAMP_UTC,
    "id": INTEGER,
    "source_event_id": INTEGER,
    "satellites": INTEGER,
    "altitude_m": FLOAT,
    "speed_mps": FLOAT,
    "heading_deg": FLOAT,
    "accuracy_m": FLOAT,
    "original_value": FLOAT,
    "effective_value": FLOAT,
    "level": FLOAT,
    "area_m2": FLOAT,
    "valid": BOOLEAN,
    "is_curated": BOOLEAN,
}


def _inferred(value: Any) -> _Column:
    """The type of a column the table does not name, from its first value: a reading is a
    number or a boolean, everything else (text, a state field, a document) is text."""
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int | float):
        return FLOAT
    return STRING


class GeoParquetWriter:
    """GeoParquet 1.1.0 (decision D312): rows go into the file one row group at a time, the
    geometry as ISO WKB in the `geometry` column. A row's geometry is its `latitude` and
    `longitude` (a point, none when either is missing) or a shapely geometry under `geometry`;
    the file is complete only after `finish()`, like XLSX.

    The `geo` metadata is written twice on purpose. The Arrow schema stored in the file carries
    it as the file opened (the geometry types when they are known up front, as for points),
    which is what a reader that restores that schema sees (pyarrow, GeoPandas); the file's own
    footer carries it complete, with every geometry type seen and their bounding box, which is
    what GDAL and the browser read. Both are valid; only the footer has the bounding box."""

    def __init__(self, stream: BinaryIO, columns: list[str], metadata: dict[str, Any]) -> None:
        self._stream = stream
        self._metadata = metadata
        self._from_point = GEOMETRY_COLUMN not in columns
        self._columns = [c for c in columns if c not in ("latitude", "longitude", GEOMETRY_COLUMN)]
        zone = str(metadata.get("timezone") or "UTC")
        self._types: dict[str, _Column] = {"time": _Column(pa.timestamp("us", tz=zone), _timestamp)}
        self._types.update({c: COLUMN_TYPES[c] for c in self._columns if c in COLUMN_TYPES})
        self._rows: list[dict[str, Any]] = []
        self._writer: Any = None
        self._schema: Any = None
        self._geometry_types: set[str] = set()
        self._bounds: list[float] | None = None
        self._has_z = False

    def _geometry(self, row: Row) -> bytes | None:
        geometry: BaseGeometry | None
        if self._from_point:
            lat, lon = row.get("latitude"), row.get("longitude")
            geometry = None if lat is None or lon is None else Point(float(lon), float(lat))
        else:
            geometry = row.get(GEOMETRY_COLUMN)
        if geometry is None:
            return None
        kind = geometry.geom_type + (" Z" if geometry.has_z else "")
        self._geometry_types.add(kind)
        self._has_z = self._has_z or geometry.has_z
        if not geometry.is_empty:
            x0, y0, x1, y1 = geometry.bounds
            b = self._bounds
            self._bounds = (
                [x0, y0, x1, y1]
                if b is None
                else [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
            )
        return bytes(to_wkb(geometry, flavor="iso"))

    def write_row(self, row: Row) -> None:
        self._rows.append(
            {**{c: row.get(c) for c in self._columns}, GEOMETRY_COLUMN: self._geometry(row)}
        )
        if len(self._rows) >= ROW_GROUP_ROWS:
            self._flush()

    def _open(self) -> None:
        """The schema is fixed by the first row group: a column the table does not name takes
        the type of its first value there, text when it holds none."""
        for name in self._columns:
            if name not in self._types:
                first = next((r[name] for r in self._rows if r[name] is not None), None)
                self._types[name] = STRING if first is None else _inferred(first)
        fields = [pa.field(c, self._types[c].type) for c in self._columns]
        known = ["Point"] if self._from_point else []
        self._schema = pa.schema(
            [*fields, pa.field(GEOMETRY_COLUMN, pa.binary())],
            metadata={
                "geo": json.dumps(self._geo(known)),
                EXPORT_METADATA_KEY: json.dumps(self._metadata, default=_json_default),
            },
        )
        self._writer = pq.ParquetWriter(self._stream, self._schema, compression="snappy")

    def _geo(self, geometry_types: list[str], bbox: list[float] | None = None) -> dict[str, Any]:
        column: dict[str, Any] = {"encoding": "WKB", "geometry_types": geometry_types}
        if bbox is not None:
            column["bbox"] = bbox
        return {
            "version": GEOPARQUET_VERSION,
            "primary_column": GEOMETRY_COLUMN,
            "columns": {GEOMETRY_COLUMN: column},
        }

    def _flush(self) -> None:
        if self._writer is None:
            self._open()
        converted = [
            {
                **{c: self._types[c].convert(r[c]) for c in self._columns},
                GEOMETRY_COLUMN: r[GEOMETRY_COLUMN],
            }
            for r in self._rows
        ]
        self._writer.write_batch(pa.RecordBatch.from_pylist(converted, schema=self._schema))
        self._rows = []

    def finish(self) -> None:
        if self._rows or self._writer is None:
            self._flush()
        bbox = self._bounds if self._bounds is not None and not self._has_z else None
        geo = self._geo(sorted(self._geometry_types), bbox)
        self._writer.add_key_value_metadata({"geo": json.dumps(geo)})
        self._writer.close()


def make_writer(
    export_format: ExportFormat, stream: BinaryIO, columns: list[str], metadata: dict[str, Any]
) -> Writer:
    if export_format is ExportFormat.CSV:
        return CsvWriter(stream, columns)
    if export_format is ExportFormat.XLSX:
        return XlsxWriter(stream, columns)
    if export_format is ExportFormat.JSON:
        return JsonWriter(stream, columns, metadata)
    if export_format is ExportFormat.GEOJSON:
        return GeoJsonWriter(stream, columns, metadata)
    if export_format is ExportFormat.PARQUET:
        return GeoParquetWriter(stream, columns, metadata)
    return GpxWriter(stream, columns, metadata)
