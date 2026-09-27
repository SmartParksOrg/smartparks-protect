"""`POST /projects/{id}/features/roads` (phase 38, decision D300): the roads and tracks of a box
from a recorded Overpass answer, longest first with a name each, footways left out; the box
bound and the permission as for the area proposal; a route kept from one becomes a feature the
off-road rule can measure from."""

import json
from pathlib import Path

import pytest

from shared.enums import Role
from tests.api.conftest import create_project, project_actor

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "overpass" / "castricum_roads.json"


async def test_a_box_answers_the_roads_in_it(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    asked: list[str] = []

    async def fake_fetch(url: str, query: str) -> dict:
        asked.append(query)
        return json.loads(FIXTURE.read_text())

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", fake_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/roads",
        json={"west": 4.62, "south": 52.538, "east": 4.65, "north": 52.552},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attribution"].startswith("© OpenStreetMap")
    roads = body["roads"]
    assert len(roads) == 12
    # the query asks for highways without the ways people walk on, and nothing else
    assert asked and 'way["highway"]' in asked[0] and "footway" in asked[0]
    assert "landuse" not in asked[0]
    # longest first, each a line with a name from the tags or the kind
    assert roads[0]["geometry"]["type"] == "LineString"
    names = {r["name"] for r in roads}
    assert {"Geversweg", "Oude Schulpweg", "Bredeweg", "Scoutingpad"} <= names
    unnamed = [r for r in roads if r["name"] in ("Track", "Service")]
    assert unnamed and all(r["highway"] in ("track", "service") for r in unnamed)

    # a kept road is an ordinary route feature with its way id
    kept = roads[0]
    created = await client.post(
        f"/api/v1/projects/{project.id}/features",
        json={
            "name": kept["name"],
            "feature_type": "route",
            "geometry": kept["geometry"],
            "attributes": {"imported_from": "openstreetmap", "osm_id": kept["osm_id"]},
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["feature_type"] == "route"

    too_large = await client.post(
        f"/api/v1/projects/{project.id}/features/roads",
        json={"west": 4.5, "south": 52.4, "east": 4.8, "north": 52.7},
        headers=admin.headers,
    )
    assert too_large.status_code == 422
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/projects/{project.id}/features/roads",
        json={"lon": 4.63, "lat": 52.545},
        headers=viewer.headers,
    )
    assert refused.status_code == 403
