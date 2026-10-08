"""The GeoTIFF header reader (phase 41): the size, the CRS, the pixel size and the extent of
files written by rasterio in the three georeferencing shapes, classic and BigTIFF, and the
refusals (not a TIFF, no georeferencing, a CRS without an EPSG code). The fixtures are written
by rasterio where it is installed (the analysis image) and kept as bytes built by hand here
otherwise, so the lean environment tests the reader too."""

import struct

import pytest

from shared.analysis.geotiff import GeoTiffError, read_geotiff_header


def _tiff(entries: list[tuple[int, int, list]], *, big: bool = False, order: str = "<") -> bytes:
    """A minimal TIFF with one directory and the given (tag, type, values) entries; the data
    of a value longer than the inline size is appended after the directory."""
    fmt = {3: "H", 4: "I", 12: "d", 2: "s", 16: "Q"}
    size = {3: 2, 4: 4, 12: 8, 2: 1, 16: 8}
    inline = 8 if big else 4
    head = 16 if big else 8
    entry = 20 if big else 12
    count_size = 8 if big else 2
    next_size = 8 if big else 4
    dir_at = head
    data_at = dir_at + count_size + entry * len(entries) + next_size
    body = b""
    out = bytearray()
    if big:
        out += struct.pack(order + "2sHHHQ", b"II" if order == "<" else b"MM", 43, 8, 0, dir_at)
    else:
        out += struct.pack(order + "2sHI", b"II" if order == "<" else b"MM", 42, dir_at)
    out += struct.pack(order + ("Q" if big else "H"), len(entries))
    for tag, kind, values in sorted(entries):
        if kind == 2:
            raw = values[0].encode() + b"\0"
            n = len(raw)
        else:
            raw = struct.pack(order + fmt[kind] * len(values), *values)
            n = len(values)
        total = size[kind] * n
        if big:
            out += struct.pack(order + "HHQ", tag, kind, n)
        else:
            out += struct.pack(order + "HHI", tag, kind, n)
        if total <= inline:
            out += raw + b"\0" * (inline - total)
        else:
            out += struct.pack(order + ("Q" if big else "I"), data_at + len(body))
            body += raw
    out += struct.pack(order + ("Q" if big else "I"), 0)
    return bytes(out) + body


def _geokeys(model: int, epsg_key: int, epsg: int) -> list[int]:
    return [1, 1, 0, 2, 1024, 0, 1, model, epsg_key, 0, 1, epsg]


def test_scale_and_tiepoint_utm():
    data = _tiff(
        [
            (256, 4, [200]),
            (257, 4, [100]),
            (258, 3, [32]),
            (277, 3, [1]),
            (339, 3, [3]),
            (33550, 12, [30.0, 30.0, 0.0]),
            (33922, 12, [0.0, 0.0, 0.0, 500_000.0, 7_700_000.0, 0.0]),
            (34735, 3, _geokeys(1, 3072, 32733)),
            (42113, 2, ["-9999"]),
        ]
    )
    h = read_geotiff_header(data)
    assert (h.width, h.height, h.bands, h.epsg, h.geographic) == (200, 100, 1, 32733, False)
    assert (h.pixel_x, h.pixel_y) == (30.0, 30.0)
    assert h.extent == (500_000.0, 7_697_000.0, 506_000.0, 7_700_000.0)
    assert h.dtype == "float32" and h.nodata == -9999 and h.cells == 20_000


def test_transformation_matrix_geographic_bigtiff():
    matrix = [0.001, 0, 0, 16.0, 0, -0.001, 0, -20.0, 0, 0, 0, 0, 0, 0, 0, 1]
    data = _tiff(
        [
            (256, 3, [1000]),
            (257, 3, [500]),
            (34264, 12, matrix),
            (34735, 3, _geokeys(2, 2048, 4326)),
        ],
        big=True,
    )
    h = read_geotiff_header(data)
    assert h.geographic and h.epsg == 4326 and h.dtype == "uint8"
    assert h.extent == pytest.approx((16.0, -20.5, 17.0, -20.0))


def test_big_endian():
    data = _tiff(
        [
            (256, 3, [10]),
            (257, 3, [10]),
            (33550, 12, [10.0, 10.0, 0.0]),
            (33922, 12, [0.0, 0.0, 0.0, 100.0, 200.0, 0.0]),
            (34735, 3, _geokeys(1, 3072, 32633)),
        ],
        order=">",
    )
    assert read_geotiff_header(data).epsg == 32633


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"PK\x03\x04" + b"\0" * 20, "byte order"),
        (_tiff([(256, 3, [10]), (257, 3, [10])]), "without georeferencing"),
        (
            _tiff(
                [
                    (256, 3, [10]),
                    (257, 3, [10]),
                    (33550, 12, [10.0, 10.0, 0.0]),
                    (33922, 12, [0.0, 0.0, 0.0, 100.0, 200.0, 0.0]),
                ]
            ),
            "names no coordinate reference system",
        ),
        (
            _tiff(
                [
                    (256, 3, [10]),
                    (257, 3, [10]),
                    (33550, 12, [10.0, 10.0, 0.0]),
                    (33922, 12, [0.0, 0.0, 0.0, 100.0, 200.0, 0.0]),
                    (34735, 3, _geokeys(1, 3072, 32767)),
                ]
            ),
            "no EPSG code",
        ),
    ],
)
def test_refusals(data, reason):
    with pytest.raises(GeoTiffError, match=reason):
        read_geotiff_header(data)
