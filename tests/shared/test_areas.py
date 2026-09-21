"""Areas proposed from OpenStreetMap (phase 33, decisions D268 to D271): the query names the
box, a recorded Overpass answer over the PWN dunes parses into lines and areas, a click gets
the enclosed face and the areas containing it, a face open to the box is marked clipped, a
face that is an area is that area, and every candidate stays within the vertex bound."""

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
    assert 'way["highway"](52.525478,4.602617,52.534522,4.617383);' in query
    assert 'relation["boundary"="protected_area"]' in query


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
