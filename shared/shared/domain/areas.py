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

Pure: the query text and the reading of the answer live here, the HTTP call does not, so the
tests run on a recorded answer. Coordinates are GeoJSON `[lon, lat]`; the flat frame for
metres is a plain equirectangular scaling around the click, good enough for a box of a few km.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import linemerge, polygonize, unary_union

#: The box around the click that is read, in metres: half its side. Clamped by the API.
DEFAULT_RADIUS_M = 1500
MIN_RADIUS_M = 200
MAX_RADIUS_M = 5000
#: Line features that bound an area on the ground.
LINE_KEYS = ("highway", "waterway", "barrier", "railway")
#: Area features worth proposing as they are. `boundary` is narrowed to the kinds that mean a
#: managed area; an administrative boundary is not a zone anybody patrols.
AREA_KEYS = ("landuse", "natural", "leisure", "amenity")
BOUNDARY_VALUES = ("protected_area", "national_park", "aboriginal_lands", "forest")
#: The most candidates a click answers and the most vertices a candidate keeps.
MAX_CANDIDATES = 8
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


def overpass_query(lon: float, lat: float, radius_m: float) -> str:
    """The Overpass QL for the lines and areas in the box around a point. `out geom` puts the
    coordinates on every way and on every relation member, so no second read is needed."""
    frame = Frame(lat)
    b = frame.box_around(lon, lat, radius_m).bounds
    bbox = f"({b[1]:.6f},{b[0]:.6f},{b[3]:.6f},{b[2]:.6f})"
    parts = [f'way["{key}"]{bbox};' for key in LINE_KEYS]
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
    return any(key in tags for key in LINE_KEYS)


def _name_of(tags: dict[str, str], kind: str) -> str:
    return tags.get("name") or kind


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
    )


def _same_shape(a: Polygon, b: Polygon | MultiPolygon) -> bool:
    return bool(a.symmetric_difference(b).area < max(a.area, b.area) * 0.01)


def propose(document: dict[str, Any], lon: float, lat: float, radius_m: float) -> list[Candidate]:
    """The candidates for a click: the enclosed face first, then the areas that contain the
    point, smallest first, at most `MAX_CANDIDATES`."""
    frame = Frame(lat)
    area = frame.box_around(lon, lat, radius_m)
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
                "osm", osm.name, osm.shape, frame, osm_id=osm.osm_id, tags={"kind": osm.kind}
            )
        )
    return out
