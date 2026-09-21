"""Areas proposed from what the map already knows (phase 33, decisions D268 to D271).

Most zones a reserve wants are already drawn on the ground: a block between two roads and a
river, a fenced camp, a forest OpenStreetMap has as a polygon. Instead of tracing them, a person
clicks inside one and gets it proposed. Two kinds of candidate come back for a click:

* the face of the line network that encloses the point: OpenStreetMap's roads, paths, rivers,
  fences and railways in a box around the click, noded and polygonized, plus the box's edge so
  a face open on one side still closes (and is marked `clipped`, since the edge is ours and not
  the landscape's);
* every OpenStreetMap area that contains the point (a protected area, a forest, a lake, a
  landuse), smallest first.

A name is the other way in (decision D273): somebody who knows the area is called Kraansvlak
types that instead of hunting for the spot to click, and the areas of that name in the part of
the map they are looking at come back as the same kind of candidate.

Pure: the query text and the reading of the answer live here, the HTTP call does not, so the
tests run on a recorded answer. Coordinates are GeoJSON `[lon, lat]`; the flat frame for
metres is a plain equirectangular scaling around the click, good enough for a box of a few km.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from shapely import set_precision
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
)
from shapely.geometry import (
    shape as shapely_shape,
)
from shapely.ops import linemerge, polygonize, unary_union

#: The box around a click that is read, in metres: half its side. Clamped by the API.
DEFAULT_RADIUS_M = 1500
MIN_RADIUS_M = 200
MAX_RADIUS_M = 2500
#: How much ground one read may cover, in square kilometres (decision D277). Measured on the
#: public Overpass over the Kennemer dunes: a box of 9 km² answers in 3 seconds with 392
#: elements and about a megabyte, one of 100 km² takes 11 seconds and 14 megabytes, and the
#: same box over Okonjima is refused with a 504. A box past `WARN_READ_KM2` is worth a word of
#: warning; one past `MAX_READ_KM2` is refused, here and in the interface, so nobody waits for
#: an answer that is not coming.
WARN_READ_KM2 = 9.0
MAX_READ_KM2 = 25.0
#: Line features that bound an area on the ground.
LINE_KEYS = ("highway", "waterway", "barrier", "railway")
#: Ways people walk or cycle on (decision D272). They cross a landscape without dividing it,
#: and a dune reserve is threaded with them — a box of three kilometres over the Kennemer dunes
#: holds 281 footways and 125 paths — so a face cut by all of them is a fragment of a few
#: hectares instead of a zone. They do not cut the face; a way that is also a fence still does.
WALKING_HIGHWAYS = ("footway", "path", "steps", "cycleway", "bridleway", "pedestrian", "corridor")
#: Area features worth proposing as they are. `boundary` is narrowed to the kinds that mean a
#: managed area; an administrative boundary is not a zone anybody patrols.
AREA_KEYS = ("landuse", "natural", "leisure", "amenity")
BOUNDARY_VALUES = ("protected_area", "national_park", "aboriginal_lands", "forest")
#: The most candidates a click answers and the most vertices a candidate keeps.
MAX_CANDIDATES = 8
#: The widest box a search by name reads, in degrees (decision D273). A view wider than this is
#: narrowed to this around its middle, since a name asked over a continent is a query no public
#: Overpass server will answer.
MAX_SEARCH_SPAN_DEG = 1.5
#: The shortest name worth searching for.
MIN_SEARCH_LENGTH = 2
#: The grid two areas' corners are snapped to before they are joined, in degrees: about a
#: centimetre. Two shapes that share an edge rarely share its numbers to the last digit — an
#: outline read from OpenStreetMap, reprojected from a shapefile or dragged by hand carries
#: noise far below a centimetre — and without snapping that leaves a sliver of a gap, so a
#: zone somebody sees as one comes back in pieces (decision D274).
JOIN_GRID_DEG = 1e-7
MAX_VERTICES = 2000
#: Where the simplification starts, in metres, doubled until a shape fits `MAX_VERTICES`.
SIMPLIFY_START_M = 1.0
#: A face whose exterior comes this close to the box is cut by the box, not by the landscape.
EDGE_TOLERANCE = 1e-7

ATTRIBUTION = "© OpenStreetMap contributors, ODbL"


@dataclass(slots=True)
class Candidate:
    """One proposal: what it is, its shape and its size."""

    kind: str
    name: str
    geometry: dict[str, Any]
    area_m2: int
    clipped: bool = False
    osm_id: int | None = None
    tags: dict[str, str] = field(default_factory=dict)
    #: Whether the name is the area's own (OpenStreetMap's `name`) rather than its kind in
    #: words, so the interface prefills a name only when there is one to prefill.
    named: bool = False


@dataclass(slots=True)
class Frame:
    """A flat frame around a latitude: degrees to metres and back."""

    lat: float

    @property
    def m_per_deg_lon(self) -> float:
        return 111_320.0 * math.cos(math.radians(self.lat))

    @property
    def m_per_deg_lat(self) -> float:
        return 110_574.0

    def box_around(self, lon: float, lat: float, radius_m: float) -> Polygon:
        dlon = radius_m / self.m_per_deg_lon
        dlat = radius_m / self.m_per_deg_lat
        return box(lon - dlon, lat - dlat, lon + dlon, lat + dlat)

    def area_m2(self, shape: Polygon | MultiPolygon) -> float:
        return float(shape.area) * self.m_per_deg_lon * self.m_per_deg_lat

    def degrees(self, metres: float) -> float:
        """A tolerance in metres as degrees, the smaller of the two axes so it errs fine."""
        return metres / max(self.m_per_deg_lon, self.m_per_deg_lat)


@dataclass(slots=True)
class ReadBox:
    """The ground one read covers (decision D277): a click makes a box around the point, a drag
    makes the box itself, and both say how much ground they ask OpenStreetMap to hand over."""

    west: float
    south: float
    east: float
    north: float

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2, (self.south + self.north) / 2)

    @property
    def polygon(self) -> Polygon:
        return box(self.west, self.south, self.east, self.north)

    @property
    def area_km2(self) -> float:
        frame = Frame((self.south + self.north) / 2)
        return (
            abs(self.east - self.west)
            * frame.m_per_deg_lon
            * abs(self.north - self.south)
            * frame.m_per_deg_lat
            / 1_000_000
        )

    @property
    def too_large(self) -> bool:
        return self.area_km2 > MAX_READ_KM2


def box_around(lon: float, lat: float, radius_m: float) -> ReadBox:
    """The box a click reads: `radius_m` to each side of the point."""
    b = Frame(lat).box_around(lon, lat, radius_m).bounds
    return ReadBox(west=b[0], south=b[1], east=b[2], north=b[3])


def box_of(west: float, south: float, east: float, north: float) -> ReadBox:
    """The box a drag reads, whichever corner it started from."""
    return ReadBox(
        west=min(west, east),
        south=min(south, north),
        east=max(west, east),
        north=max(south, north),
    )


def _line_part(key: str, bbox: str) -> str:
    """The query statement for one kind of line. The ways people walk on are left out here as
    well as in the reading, so the answer stays small on a landscape full of footpaths."""
    if key != "highway":
        return f'way["{key}"]{bbox};'
    walking = "|".join(WALKING_HIGHWAYS)
    return f'way["highway"]["highway"!~"^({walking})$"]{bbox};'


def overpass_query(read: ReadBox) -> str:
    """The Overpass QL for the lines and areas in the box that is read. `out geom` puts the
    coordinates on every way and on every relation member, so no second read is needed."""
    bbox = f"({read.south:.6f},{read.west:.6f},{read.north:.6f},{read.east:.6f})"
    parts = [_line_part(key, bbox) for key in LINE_KEYS]
    parts += [f'way["{key}"]{bbox};' for key in AREA_KEYS]
    parts += [f'relation["{key}"]{bbox};' for key in AREA_KEYS]
    parts += [f'way["boundary"="{value}"]{bbox};' for value in BOUNDARY_VALUES]
    parts += [f'relation["boundary"="{value}"]{bbox};' for value in BOUNDARY_VALUES]
    return "[out:json][timeout:25];(" + "".join(parts) + ");out geom;"


def _coords(geometry: list[dict[str, float]]) -> list[tuple[float, float]]:
    return [(float(p["lon"]), float(p["lat"])) for p in geometry]


def _area_kind(tags: dict[str, str]) -> str | None:
    """The tag that makes an element an area, as `key=value`, or None."""
    for key in AREA_KEYS:
        if key in tags:
            return f"{key}={tags[key]}"
    if tags.get("boundary") in BOUNDARY_VALUES:
        return f"boundary={tags['boundary']}"
    return None


def _is_line(tags: dict[str, str]) -> bool:
    """Whether the way divides the ground. A way people walk on does not (decision D272),
    unless it is something else as well: a footpath along a fence still cuts."""
    for key in LINE_KEYS:
        if key not in tags:
            continue
        if key == "highway" and tags[key] in WALKING_HIGHWAYS:
            continue
        return True
    return False


def _name_of(tags: dict[str, str], kind: str) -> str:
    """The area's own name, else its kind in words: `natural=scrub` reads "Scrub"."""
    if tags.get("name"):
        return tags["name"]
    value = kind.split("=", 1)[1] if "=" in kind else kind
    return value.replace("_", " ").capitalize()


def _merged(pieces: list[LineString]) -> Any:
    """The pieces of a ring joined end to end; `linemerge` refuses a single line."""
    joined = unary_union(pieces)
    return joined if isinstance(joined, LineString) else linemerge(joined)


def _relation_polygon(members: list[dict[str, Any]]) -> Polygon | MultiPolygon | None:
    """A multipolygon relation's shape from its outer and inner ways, which arrive as pieces
    in no order: merge the pieces into rings, polygonize, and cut the inners out."""
    outers = [
        LineString(_coords(m["geometry"]))
        for m in members
        if m.get("type") == "way"
        and m.get("role", "outer") in ("outer", "")
        and m.get("geometry")
        and len(m["geometry"]) >= 2
    ]
    if not outers:
        return None
    shape = unary_union(list(polygonize(_merged(outers))))
    if shape.is_empty:
        return None
    inners = [
        LineString(_coords(m["geometry"]))
        for m in members
        if m.get("type") == "way"
        and m.get("role") == "inner"
        and m.get("geometry")
        and len(m["geometry"]) >= 2
    ]
    if inners:
        holes = unary_union(list(polygonize(_merged(inners))))
        shape = shape.difference(holes)
    if shape.is_empty or not isinstance(shape, Polygon | MultiPolygon):
        return None
    return shape


@dataclass(slots=True)
class OsmArea:
    kind: str
    name: str
    shape: Polygon | MultiPolygon
    osm_id: int
    tags: dict[str, str]

    @property
    def named(self) -> bool:
        return bool(self.tags.get("name"))


@dataclass(slots=True)
class Parsed:
    lines: list[LineString]
    areas: list[OsmArea]


def parse_overpass(document: dict[str, Any]) -> Parsed:
    """The lines and the areas of an Overpass answer. A closed way with an area tag is an area;
    a way with a line tag is a line, and a closed area way's ring bounds faces as well, since a
    forest's edge is as much a boundary on the ground as a road."""
    lines: list[LineString] = []
    areas: list[OsmArea] = []
    for element in document.get("elements", []):
        tags = {str(k): str(v) for k, v in (element.get("tags") or {}).items()}
        kind = _area_kind(tags)
        if element.get("type") == "way":
            coords = _coords(element.get("geometry") or [])
            if len(coords) < 2:
                continue
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            if _is_line(tags):
                lines.append(LineString(coords))
            if kind and closed:
                ring = Polygon(coords)
                if ring.is_valid and not ring.is_empty:
                    areas.append(
                        OsmArea(kind, _name_of(tags, kind), ring, int(element["id"]), tags)
                    )
                    if not _is_line(tags):
                        lines.append(LineString(coords))
        elif element.get("type") == "relation" and kind:
            shape = _relation_polygon(element.get("members") or [])
            if shape is None:
                continue
            areas.append(OsmArea(kind, _name_of(tags, kind), shape, int(element["id"]), tags))
            lines.append(shape.boundary) if isinstance(
                shape.boundary, LineString
            ) else lines.extend(list(shape.boundary.geoms))
    return Parsed(lines=lines, areas=areas)


def enclosed_face(
    lines: list[LineString], area: Polygon, point: Point
) -> tuple[Polygon | None, bool]:
    """The face of the noded line network, closed by the box's edge, that contains the point,
    and whether the box's edge is part of its outline."""
    if not lines:
        return None, False
    noded = unary_union([*lines, area.boundary])
    for face in polygonize(noded):
        if face.contains(point):
            clipped = face.exterior.distance(area.boundary) < EDGE_TOLERANCE
            return face, clipped
    return None, False


def _simplified(shape: Polygon | MultiPolygon, frame: Frame) -> Polygon | MultiPolygon:
    """Fewer vertices than `MAX_VERTICES`, from a metre of tolerance upwards."""
    tolerance_m = SIMPLIFY_START_M
    out = shape
    while _vertices(out) > MAX_VERTICES and tolerance_m < 1000:
        out = shape.simplify(frame.degrees(tolerance_m), preserve_topology=True)
        tolerance_m *= 2
    return out


def _vertices(shape: Polygon | MultiPolygon) -> int:
    polygons = shape.geoms if isinstance(shape, MultiPolygon) else [shape]
    return sum(len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in polygons)


def _candidate(
    kind: str,
    name: str,
    shape: Polygon | MultiPolygon,
    frame: Frame,
    *,
    clipped: bool = False,
    osm_id: int | None = None,
    tags: dict[str, str] | None = None,
    named: bool = False,
) -> Candidate:
    simplified = _simplified(shape, frame)
    return Candidate(
        kind=kind,
        name=name,
        geometry=mapping(simplified),
        area_m2=round(frame.area_m2(simplified)),
        clipped=clipped,
        osm_id=osm_id,
        tags=tags or {},
        named=named,
    )


def _same_shape(a: Polygon, b: Polygon | MultiPolygon) -> bool:
    return bool(a.symmetric_difference(b).area < max(a.area, b.area) * 0.01)


def propose(document: dict[str, Any], read: ReadBox) -> list[Candidate]:
    """The candidates for one read: the enclosed face first, then the areas that contain the
    point, smallest first, at most `MAX_CANDIDATES`. The point is the middle of the box, which
    is the click for a click and the middle of the drag for a drag."""
    lon, lat = read.centre
    frame = Frame(lat)
    area = read.polygon
    point = Point(lon, lat)
    parsed = parse_overpass(document)
    out: list[Candidate] = []
    containing = sorted(
        (a for a in parsed.areas if a.shape.contains(point)), key=lambda a: a.shape.area
    )
    face, clipped = enclosed_face(parsed.lines, area, point)
    # a face that is one of the areas, to the metre, is that area under its own name
    if (
        face is not None
        and face.area < area.area * 0.999
        and not any(_same_shape(face, a.shape) for a in containing)
    ):
        out.append(
            _candidate("enclosed", "Enclosed by roads and water", face, frame, clipped=clipped)
        )
    for osm in containing:
        if len(out) >= MAX_CANDIDATES:
            break
        out.append(
            _candidate(
                "osm",
                osm.name,
                osm.shape,
                frame,
                osm_id=osm.osm_id,
                tags={"kind": osm.kind},
                named=osm.named,
            )
        )
    return out


@dataclass(slots=True)
class SearchBox:
    """The part of the map a search by name reads: the view, narrowed when it is too wide."""

    west: float
    south: float
    east: float
    north: float
    narrowed: bool = False


def search_box(west: float, south: float, east: float, north: float) -> SearchBox:
    """The view as it will be searched. A view wider than `MAX_SEARCH_SPAN_DEG` is kept to that
    span around its middle, and says so, rather than being refused or asked for in full."""
    lon_span, lat_span = abs(east - west), abs(north - south)
    if lon_span <= MAX_SEARCH_SPAN_DEG and lat_span <= MAX_SEARCH_SPAN_DEG:
        return SearchBox(min(west, east), min(south, north), max(west, east), max(south, north))
    mid_lon, mid_lat = (west + east) / 2, (south + north) / 2
    half = MAX_SEARCH_SPAN_DEG / 2
    return SearchBox(
        max(mid_lon - half, -180.0),
        max(mid_lat - half, -90.0),
        min(mid_lon + half, 180.0),
        min(mid_lat + half, 90.0),
        narrowed=True,
    )


def _quoted(text: str) -> str:
    """The text as a literal inside an Overpass regex string: the regex's own characters lose
    their meaning, and the quotes and backslashes the query language reads are escaped."""
    return re.escape(text).replace("\\", "\\\\").replace('"', '\\"')


def name_query(box_: SearchBox, name: str) -> str:
    """The Overpass QL for the areas whose name holds `name`, inside the searched box. Only the
    elements that carry an area tag are asked for, so a street of the same name stays out."""
    bbox = f"({box_.south:.6f},{box_.west:.6f},{box_.north:.6f},{box_.east:.6f})"
    wanted = _quoted(name)
    parts = []
    for element in ("way", "relation"):
        for key in AREA_KEYS:
            parts.append(f'{element}["name"~"{wanted}",i]["{key}"]{bbox};')
        for value in BOUNDARY_VALUES:
            parts.append(f'{element}["name"~"{wanted}",i]["boundary"="{value}"]{bbox};')
    return "[out:json][timeout:25];(" + "".join(parts) + ");out geom;"


def _match_rank(area_name: str, wanted: str) -> int:
    """How well a name answers what was typed: the same name, then one that starts with it,
    then one that merely holds it. "Kraansvlak" finds "Het Kraansvlak" without beating it."""
    found, asked = area_name.casefold(), wanted.casefold()
    if found == asked:
        return 0
    if found.startswith(asked):
        return 1
    return 2


def search_areas(document: dict[str, Any], name: str, box_: SearchBox) -> list[Candidate]:
    """The named areas an Overpass answer holds for a search, best match first and the larger
    of two equal matches before the smaller, since the reserve is what a name usually means."""
    frame = Frame((box_.south + box_.north) / 2)
    parsed = parse_overpass(document)
    found = [a for a in parsed.areas if a.named and name.casefold() in a.name.casefold()]
    found.sort(key=lambda a: (_match_rank(a.name, name), -a.shape.area))
    seen: set[int] = set()
    out: list[Candidate] = []
    for osm in found:
        if osm.osm_id in seen:
            continue
        seen.add(osm.osm_id)
        out.append(
            _candidate(
                "osm",
                osm.name,
                osm.shape,
                frame,
                osm_id=osm.osm_id,
                tags={"kind": osm.kind},
                named=True,
            )
        )
        if len(out) >= MAX_CANDIDATES:
            break
    return out


@dataclass(slots=True)
class Combined:
    """Several areas as one (decision D274): the union, its size, and how many pieces it is
    in. Pieces that touch become one; pieces that do not stay separate in one shape."""

    geometry: dict[str, Any]
    area_m2: int
    parts: int

    @property
    def separate(self) -> bool:
        """Whether the shape is in pieces, which is what a drawing editor cannot correct."""
        return self.parts > 1


def combine_areas(geometries: list[dict[str, Any]]) -> Combined | None:
    """One area out of several (decision D274): four dune reserves beside each other are one
    zone to the people who patrol them. The shapes are cleaned of the self-touching rings
    OpenStreetMap and hand-drawing leave (`buffer(0)`), joined, and simplified under the same
    vertex bound as a proposal. Anything that is not an area is ignored; None when nothing of
    the sort is left."""
    shapes: list[Polygon | MultiPolygon] = []
    for geometry in geometries:
        try:
            piece = shapely_shape(geometry)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if not isinstance(piece, Polygon | MultiPolygon):
            continue
        if not piece.is_valid:
            piece = piece.buffer(0)
        if isinstance(piece, Polygon | MultiPolygon) and not piece.is_empty:
            shapes.append(piece)
    if not shapes:
        return None
    joined = unary_union([set_precision(piece, JOIN_GRID_DEG) for piece in shapes])
    if isinstance(joined, GeometryCollection):
        polygons = [g for g in joined.geoms if isinstance(g, Polygon | MultiPolygon)]
        if not polygons:
            return None
        joined = unary_union(polygons)
    if not isinstance(joined, Polygon | MultiPolygon) or joined.is_empty:
        return None
    frame = Frame(joined.centroid.y)
    simplified = _simplified(joined, frame)
    return Combined(
        geometry=mapping(simplified),
        area_m2=round(frame.area_m2(simplified)),
        parts=len(simplified.geoms) if isinstance(simplified, MultiPolygon) else 1,
    )
