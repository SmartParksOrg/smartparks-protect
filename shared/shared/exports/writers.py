"""Streaming writers: rows in, bytes out, never the whole dataset in memory (architecture 13.8).

Every writer takes a binary file object and a column list, gets rows as dicts in column order,
and writes them as they come. XLSX is the exception in spirit: openpyxl's write-only mode
streams rows to a temporary zip, but the file is only complete after `finish()`.
"""

import csv
import io
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, BinaryIO, Protocol
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from shared.enums import ExportFormat

EXCEL_MAX_ROWS = 1_048_576  # per sheet, header included; enforced by splitting (decision D40)

CONTENT_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv; charset=utf-8",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.JSON: "application/json",
    ExportFormat.GEOJSON: "application/geo+json",
    ExportFormat.GPX: "application/gpx+xml",
}

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
    return GpxWriter(stream, columns, metadata)
