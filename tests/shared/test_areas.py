"""Areas proposed from OpenStreetMap (phase 33, decisions D268 to D273): the query names the
box and leaves the ways people walk on out, a recorded Overpass answer over the PWN dunes
parses into lines and areas, a click gets the enclosed face and the areas containing it, a face
open to the box is marked clipped, a face that is an area is that area, every candidate stays
within the vertex bound, and a name finds the areas that carry it."""

import json
from pathlib import Path

from shapely.geometry import Point, shape

from shared.domain import areas

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "overpass" / "pwn_dunes.json"


def _document() -> dict:
    return json.loads(FIXTURE.read_text())


def test_the_query_names_a_box_around_the_click_south_west_north_east():
    query = areas.overpass_query(4.61, 52.53, 500)
    assert query.startswith("[out:json][timeout:25];(")
    assert query.endswith(");out geom;")
    # 500 m is about 0.0045 degrees of latitude and 0.0074 of longitude at 52.5 north
    bbox = "(52.525478,4.602617,52.534522,4.617383)"
    assert f'way["waterway"]{bbox};' in query
    assert 'relation["boundary"="protected_area"]' in query
    # the ways people walk on are not asked for at all (decision D272)
    assert 'way["highway"]["highway"!~"^(footway|path|steps|cycleway|bridleway' in query
    assert f'way["highway"]{bbox};' not in query


def test_the_recorded_answer_parses_into_lines_and_areas():
    parsed = areas.parse_overpass(_document())
    assert len(parsed.lines) > 10
    kinds = {a.kind for a in parsed.areas}
    assert {"landuse=forest", "natural=water", "natural=scrub"} <= kinds
    # a multipolygon relation is one shape with its pieces joined
    scrub = [a for a in parsed.areas if a.kind == "natural=scrub"]
    assert len(scrub) == 3 and all(a.shape.is_valid for a in scrub)


def test_a_click_in_the_dunes_proposes_the_scrub_it_is_in_smallest_first():
    candidates = areas.propose(_document(), 4.6105, 52.5305, 500)
    assert candidates, "nothing proposed"
    assert candidates[0].kind == "osm" and candidates[0].tags == {"kind": "natural=scrub"}
    # no name on OpenStreetMap: the kind in words, and not marked as named
    assert candidates[0].name == "Scrub" and candidates[0].named is False
    assert 250_000 < candidates[0].area_m2 < 300_000
    assert shape(candidates[0].geometry).contains(Point(4.6105, 52.5305))
    # the enclosed face was the scrub itself, so it is not listed twice
    assert [c.kind for c in candidates].count("enclosed") == 0
    assert all(len(json.dumps(c.geometry)) < 20_000 for c in candidates)


def test_a_face_cut_by_the_box_is_marked_clipped():
    candidates = areas.propose(_document(), 4.6070, 52.5290, 500)
    enclosed = [c for c in candidates if c.kind == "enclosed"]
    assert enclosed and enclosed[0].clipped is True
    assert enclosed[0].name == "Enclosed by roads and water"


def test_nothing_around_the_click_proposes_nothing():
    assert areas.propose({"elements": []}, 4.61, 52.53, 500) == []
    far = areas.propose(_document(), 4.70, 52.60, 500)
    assert far == []


def test_a_big_shape_is_simplified_under_the_vertex_bound():
    ring = [
        (
            4.61 + 0.001 * __import__("math").cos(i / 5000 * 6.283),
            52.53 + 0.001 * __import__("math").sin(i / 5000 * 6.283),
        )
        for i in range(5000)
    ]
    ring.append(ring[0])
    document = {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"landuse": "forest", "name": "Round wood"},
                "geometry": [{"lon": x, "lat": y} for x, y in ring],
            }
        ]
    }
    (candidate,) = areas.propose(document, 4.61, 52.53, 500)
    assert candidate.name == "Round wood" and candidate.named is True
    assert len(candidate.geometry["coordinates"][0]) <= areas.MAX_VERTICES
    assert 22_000 < candidate.area_m2 < 25_000


def test_a_footpath_does_not_cut_a_face_but_a_fence_along_one_does():
    """Decision D272: a dune reserve is threaded with footpaths, and a face cut by all of them
    is a fragment. The ring below is one block with a path straight through the middle."""

    def block(lon_west: float, lon_east: float) -> list[dict[str, float]]:
        corners = [
            (lon_west, 52.520),
            (lon_east, 52.520),
            (lon_east, 52.540),
            (lon_west, 52.540),
            (lon_west, 52.520),
        ]
        return [{"lon": x, "lat": y} for x, y in corners]

    def through_the_middle(tags: dict[str, str]) -> dict:
        return {
            "type": "way",
            "id": 2,
            "tags": tags,
            "geometry": [{"lon": 4.610, "lat": 52.520}, {"lon": 4.610, "lat": 52.540}],
        }

    ring = {"type": "way", "id": 1, "tags": {"barrier": "fence"}, "geometry": block(4.600, 4.620)}
    click = (4.6045, 52.530)

    def face_area(divider: dict) -> int:
        candidates = areas.propose({"elements": [ring, divider]}, *click, 2000)
        enclosed = [c for c in candidates if c.kind == "enclosed"]
        assert enclosed, "no face"
        return enclosed[0].area_m2

    whole = face_area(through_the_middle({"highway": "track"}))
    with_a_path = face_area(through_the_middle({"highway": "footway"}))
    with_a_fenced_path = face_area(through_the_middle({"highway": "footway", "barrier": "fence"}))
    # the track halves the block, the footway leaves it whole, the fence along it halves it
    assert with_a_path > whole * 1.9
    assert abs(with_a_fenced_path - whole) < whole * 0.01


def test_a_view_wider_than_the_widest_search_is_narrowed_to_its_middle():
    kept = areas.search_box(4.40, 52.30, 4.75, 52.55)
    assert (kept.west, kept.south, kept.east, kept.north) == (4.40, 52.30, 4.75, 52.55)
    assert kept.narrowed is False
    # corners given the other way round are still read as a box
    assert areas.search_box(4.75, 52.55, 4.40, 52.30).west == 4.40
    wide = areas.search_box(0.0, 50.0, 10.0, 56.0)
    assert wide.narrowed is True
    assert wide.east - wide.west == areas.MAX_SEARCH_SPAN_DEG
    assert wide.north - wide.south == areas.MAX_SEARCH_SPAN_DEG
    assert (wide.west + wide.east) / 2 == 5.0 and (wide.south + wide.north) / 2 == 53.0


def test_a_name_is_a_literal_in_the_query_and_only_areas_are_asked_for():
    query = areas.name_query(areas.search_box(4.4, 52.3, 4.75, 52.55), 'Kraans"vlak.')
    assert query.startswith("[out:json][timeout:25];(") and query.endswith(");out geom;")
    # Overpass reads \" as a quote and \\ as a backslash, so the regex is the name, literally
    assert 'way["name"~"Kraans\\"vlak\\\\.",i]["leisure"]' in query
    assert 'relation["name"~"Kraans\\"vlak\\\\.",i]["boundary"="protected_area"]' in query
    # a road of the same name is never asked for: every statement carries an area tag
    for statement in query.split("(", 1)[1].rsplit(")", 1)[0].split(";"):
        assert not statement or '["name"~' in statement


def test_a_name_finds_the_area_that_carries_it():
    document = json.loads(
        (
            Path(__file__).resolve().parents[1] / "fixtures" / "overpass" / "kraansvlak_name.json"
        ).read_text()
    )
    box = areas.search_box(4.40, 52.30, 4.75, 52.55)
    (found,) = areas.search_areas(document, "Kraansvlak", box)
    assert found.name == "Het Kraansvlak" and found.named is True
    assert found.kind == "osm" and found.tags == {"kind": "leisure=nature_reserve"}
    assert 4_700_000 < found.area_m2 < 4_800_000
    assert shape(found.geometry).contains(Point(4.5621, 52.3906))
    assert areas.search_areas(document, "Zuid-Kennemerland", box) == []


def test_the_best_match_comes_first_and_the_larger_of_two_equals_before_the_smaller():
    def area(osm_id: int, name: str, size: float) -> dict:
        ring = [
            (4.60, 52.52),
            (4.60 + size, 52.52),
            (4.60 + size, 52.52 + size),
            (4.60, 52.52 + size),
            (4.60, 52.52),
        ]
        return {
            "type": "way",
            "id": osm_id,
            "tags": {"leisure": "nature_reserve", "name": name},
            "geometry": [{"lon": x, "lat": y} for x, y in ring],
        }

    document = {
        "elements": [
            area(1, "Het Kraansvlak", 0.01),
            area(2, "Kraansvlak", 0.005),
            area(3, "Kraansvlak noord", 0.002),
            area(4, "Kraansvlak zuid", 0.02),
            area(5, "Duinen", 0.03),
        ]
    }
    box = areas.search_box(4.55, 52.50, 4.70, 52.60)
    found = [c.name for c in areas.search_areas(document, "kraansvlak", box)]
    assert found == ["Kraansvlak", "Kraansvlak zuid", "Kraansvlak noord", "Het Kraansvlak"]


def _square(west: float, south: float, side: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [west + side, south],
                [west + side, south + side],
                [west, south + side],
                [west, south],
            ]
        ],
    }


def test_areas_that_touch_become_one_and_areas_apart_stay_in_pieces():
    """Decision D274: four dune reserves beside each other are one zone to the people who
    patrol them, and a reserve with an outlying block is still one zone."""
    # the two squares share an edge, and 4.60 + 0.01 is not 4.61 to the last digit, which is
    # the noise every real outline carries: snapped to the join grid, they are one block
    beside = areas.combine_areas([_square(4.60, 52.52, 0.01), _square(4.61, 52.52, 0.01)])
    assert beside is not None
    assert beside.parts == 1 and beside.separate is False
    assert beside.geometry["type"] == "Polygon"
    # one block of twice the area, not two overlapping ones
    alone = areas.combine_areas([_square(4.60, 52.52, 0.01), _square(4.60, 52.52, 0.01)])
    assert alone is not None
    assert 1.95 < beside.area_m2 / alone.area_m2 < 2.05

    apart = areas.combine_areas([_square(4.60, 52.52, 0.01), _square(4.70, 52.52, 0.01)])
    assert apart is not None
    assert apart.parts == 2 and apart.separate is True
    assert apart.geometry["type"] == "MultiPolygon"


def test_combining_ignores_what_is_not_an_area_and_mends_a_broken_ring():
    line = {"type": "LineString", "coordinates": [[4.60, 52.52], [4.61, 52.53]]}
    point = {"type": "Point", "coordinates": [4.60, 52.52]}
    assert areas.combine_areas([line, point]) is None
    assert areas.combine_areas([]) is None
    with_a_line = areas.combine_areas([_square(4.60, 52.52, 0.01), line])
    assert with_a_line is not None and with_a_line.parts == 1
    # a bow-tie ring crosses itself; buffer(0) makes it the two triangles it draws
    bow_tie = {
        "type": "Polygon",
        "coordinates": [
            [[4.60, 52.52], [4.62, 52.54], [4.62, 52.52], [4.60, 52.54], [4.60, 52.52]]
        ],
    }
    mended = areas.combine_areas([bow_tie, _square(4.70, 52.52, 0.001)])
    assert mended is not None and mended.area_m2 > 0
    assert areas.combine_areas([{"type": "Polygon"}, _square(4.60, 52.52, 0.01)]) is not None


def test_a_combined_area_stays_under_the_vertex_bound():
    import math

    def circle(lon: float, lat: float) -> dict:
        ring = [
            (lon + 0.01 * math.cos(i / 3000 * math.tau), lat + 0.01 * math.sin(i / 3000 * math.tau))
            for i in range(3000)
        ]
        ring.append(ring[0])
        return {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}

    combined = areas.combine_areas([circle(4.60, 52.52), circle(4.70, 52.52)])
    assert combined is not None and combined.parts == 2
    points = sum(len(part[0]) for part in combined.geometry["coordinates"])
    assert points <= areas.MAX_VERTICES
