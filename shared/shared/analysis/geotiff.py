"""The header of a GeoTIFF, read without a raster library (phase 41, decision D315): the API
runs in the lean image and must say at upload whether a file is a GeoTIFF with a CRS, its size,
its pixel size and its extent, so the Layers card can show them and refuse what the worker
could not use. The pixels are never read here; the worker reads them with rasterio.

Sources: the TIFF 6.0 specification (the header, the IFD, the tag entries), the BigTIFF
layout (version 43, 8 byte offsets) and GeoTIFF 1.1 (OGC 19-008r4: ModelPixelScaleTag 33550,
ModelTiepointTag 33922, ModelTransformationTag 34264, GeoKeyDirectoryTag 34735, the keys
GTModelTypeGeoKey 1024, ProjectedCSTypeGeoKey 3072 and GeographicTypeGeoKey 2048)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: The first IFD and the tags it points at sit near the front of a file; a header this long
#: holds every Cloud Optimized GeoTIFF's and ordinary GeoTIFF's metadata.
HEADER_BYTES = 1 << 20

TYPE_SIZES = {
    1: 1,
    2: 1,
    3: 2,
    4: 4,
    5: 8,
    6: 1,
    7: 1,
    8: 2,
    9: 4,
    10: 8,
    11: 4,
    12: 8,
    16: 8,
    17: 8,
    18: 8,
}
TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q"}

TAG_WIDTH = 256
TAG_HEIGHT = 257
TAG_BITS = 258
TAG_SAMPLES = 277
TAG_SAMPLE_FORMAT = 339
TAG_PIXEL_SCALE = 33550
TAG_TIEPOINT = 33922
TAG_TRANSFORM = 34264
TAG_GEO_KEYS = 34735
TAG_NODATA = 42113

KEY_MODEL_TYPE = 1024
KEY_PROJECTED_CRS = 3072
KEY_GEOGRAPHIC_CRS = 2048
USER_DEFINED = 32767


class GeoTiffError(ValueError):
    """Not a GeoTIFF the module can use; the message says why."""


@dataclass(frozen=True, slots=True)
class GeoTiffHeader:
    width: int
    height: int
    bands: int
    epsg: int
    #: The pixel size in the CRS's units (metres for a projected CRS, degrees otherwise).
    pixel_x: float
    pixel_y: float
    #: The extent as west, south, east, north in the CRS's units.
    extent: tuple[float, float, float, float]
    geographic: bool
    dtype: str
    nodata: float | None

    @property
    def cells(self) -> int:
        return self.width * self.height


def _read_entries(
    data: bytes, offset: int, order: str, big: bool
) -> dict[int, tuple[int, int, int]]:
    """The entries of one IFD: tag to (type, count, value offset or inline value start)."""
    if big:
        (count,) = struct.unpack_from(order + "Q", data, offset)
        offset += 8
        entry = 20
    else:
        (count,) = struct.unpack_from(order + "H", data, offset)
        offset += 2
        entry = 12
    if count > 10_000 or offset + count * entry > len(data):
        raise GeoTiffError("the TIFF directory is truncated or not a TIFF")
    entries: dict[int, tuple[int, int, int]] = {}
    for i in range(count):
        at = offset + i * entry
        if big:
            tag, kind, n = struct.unpack_from(order + "HHQ", data, at)
            value_at = at + 12
        else:
            tag, kind, n = struct.unpack_from(order + "HHI", data, at)
            value_at = at + 8
        entries[tag] = (kind, n, value_at)
    return entries


def _values(data: bytes, entry: tuple[int, int, int], order: str, big: bool) -> list[float]:
    kind, n, value_at = entry
    size = TYPE_SIZES.get(kind)
    fmt = TYPE_FORMATS.get(kind)
    if size is None or fmt is None:
        raise GeoTiffError(f"a TIFF tag of type {kind} is not one this reader knows")
    total = size * n
    inline = 8 if big else 4
    if total <= inline:
        start = value_at
    else:
        (start,) = struct.unpack_from(order + ("Q" if big else "I"), data, value_at)
    if start + total > len(data):
        raise GeoTiffError("a TIFF tag points past the header this reader holds")
    return list(struct.unpack_from(order + fmt * n, data, start))


def _ascii(data: bytes, entry: tuple[int, int, int], order: str, big: bool) -> str:
    _, n, value_at = entry
    inline = 8 if big else 4
    if n <= inline:
        start = value_at
    else:
        (start,) = struct.unpack_from(order + ("Q" if big else "I"), data, value_at)
    return data[start : start + n].split(b"\0", 1)[0].decode("ascii", "replace")


def read_geotiff_header(data: bytes) -> GeoTiffHeader:
    """What the first directory of a GeoTIFF says. Raises `GeoTiffError` for anything that is
    not a TIFF, has no georeferencing, or names its CRS without an EPSG code (a user-defined
    projection in the GeoKeys), since the worker and every GIS agree on EPSG codes alone."""
    if len(data) < 16:
        raise GeoTiffError("the file is too short to be a TIFF")
    order = {b"II": "<", b"MM": ">"}.get(data[:2])
    if order is None:
        raise GeoTiffError("not a TIFF: the byte order mark is missing")
    (version,) = struct.unpack_from(order + "H", data, 2)
    if version == 42:
        big = False
        (first,) = struct.unpack_from(order + "I", data, 4)
    elif version == 43:
        big = True
        (first,) = struct.unpack_from(order + "Q", data, 8)
    else:
        raise GeoTiffError("not a TIFF: the version is neither 42 nor 43")
    if first >= len(data):
        raise GeoTiffError("the first TIFF directory lies past the header this reader holds")
    entries = _read_entries(data, first, order, big)
    try:
        width = int(_values(data, entries[TAG_WIDTH], order, big)[0])
        height = int(_values(data, entries[TAG_HEIGHT], order, big)[0])
    except KeyError as exc:
        raise GeoTiffError("the TIFF has no image size") from exc
    bands = int(_values(data, entries[TAG_SAMPLES], order, big)[0]) if TAG_SAMPLES in entries else 1
    bits = int(_values(data, entries[TAG_BITS], order, big)[0]) if TAG_BITS in entries else 8
    sample_format = (
        int(_values(data, entries[TAG_SAMPLE_FORMAT], order, big)[0])
        if TAG_SAMPLE_FORMAT in entries
        else 1
    )
    dtype = {1: "uint", 2: "int", 3: "float"}.get(sample_format, "uint") + str(bits)
    nodata: float | None = None
    if TAG_NODATA in entries:
        try:
            nodata = float(_ascii(data, entries[TAG_NODATA], order, big).strip())
        except ValueError:
            nodata = None
    # the georeferencing: a scale with a tiepoint, or a transformation matrix
    if TAG_TRANSFORM in entries:
        m = _values(data, entries[TAG_TRANSFORM], order, big)
        if len(m) < 16:
            raise GeoTiffError("the ModelTransformation tag is incomplete")
        if m[1] != 0 or m[4] != 0:
            raise GeoTiffError("a rotated raster is not supported; export it north-up")
        pixel_x, pixel_y = abs(m[0]), abs(m[5])
        west, north = m[3], m[7]
    elif TAG_PIXEL_SCALE in entries and TAG_TIEPOINT in entries:
        scale = _values(data, entries[TAG_PIXEL_SCALE], order, big)
        tie = _values(data, entries[TAG_TIEPOINT], order, big)
        if len(scale) < 2 or len(tie) < 6:
            raise GeoTiffError("the pixel scale or the tiepoint tag is incomplete")
        pixel_x, pixel_y = abs(scale[0]), abs(scale[1])
        # the tiepoint maps raster (i, j) to model (x, y); the raster origin is the top left
        west = tie[3] - tie[0] * pixel_x
        north = tie[4] + tie[1] * pixel_y
    else:
        raise GeoTiffError("the file is a TIFF without georeferencing tags: not a GeoTIFF")
    if pixel_x <= 0 or pixel_y <= 0:
        raise GeoTiffError("the pixel size is zero")
    if TAG_GEO_KEYS not in entries:
        raise GeoTiffError("the GeoTIFF names no coordinate reference system")
    keys = [int(v) for v in _values(data, entries[TAG_GEO_KEYS], order, big)]
    if len(keys) < 4:
        raise GeoTiffError("the GeoKey directory is empty")
    geokeys: dict[int, int] = {}
    for i in range(4, 4 + 4 * keys[3], 4):
        if i + 3 >= len(keys):
            break
        key, location, count, value = keys[i : i + 4]
        if location == 0 and count == 1:
            geokeys[key] = value
    model = geokeys.get(KEY_MODEL_TYPE)
    epsg = 0
    geographic = False
    if model == 1:
        epsg = geokeys.get(KEY_PROJECTED_CRS, 0)
    elif model == 2:
        epsg = geokeys.get(KEY_GEOGRAPHIC_CRS, 0)
        geographic = True
    if epsg in (0, USER_DEFINED):
        raise GeoTiffError(
            "the GeoTIFF's coordinate reference system has no EPSG code; export it with one "
            "(a UTM zone, or EPSG:4326)"
        )
    extent = (west, north - height * pixel_y, west + width * pixel_x, north)
    return GeoTiffHeader(
        width=width,
        height=height,
        bands=bands,
        epsg=epsg,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        extent=extent,
        geographic=geographic,
        dtype=dtype,
        nodata=nodata,
    )
