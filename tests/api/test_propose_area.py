"""`POST /projects/{id}/features/propose` (phase 33, decision D270) and
`/features/search-areas` (decision D273): the click's candidates and the named areas from a
recorded Overpass answer, features:write to ask, a radius or a name out of bounds refused, a
view too wide read in the middle, and a 502 with the reason when OpenStreetMap does not
answer."""

import json
from pathlib import Path

import pytest

from shared.enums import ErrorCode, Role
from shared.trace import ApplicationError
from tests.api.conftest import create_project, project_actor

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "overpass"
FIXTURE = FIXTURES / "pwn_dunes.json"
BY_NAME = FIXTURES / "kraansvlak_name.json"


async def test_a_click_answers_candidates(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    asked: list[tuple[str, str]] = []

    async def fake_fetch(url: str, query: str) -> dict:
        asked.append((url, query))
        return json.loads(FIXTURE.read_text())

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", fake_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/propose",
        json={"lon": 4.6105, "lat": 52.5305, "radius_m": 500},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["attribution"].startswith("© OpenStreetMap")
    assert body["candidates"] and body["candidates"][0]["kind"] == "osm"
    assert body["candidates"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert asked and asked[0][0].startswith("https://") and "out geom" in asked[0][1]

    too_far = await client.post(
        f"/api/v1/projects/{project.id}/features/propose",
        json={"lon": 4.61, "lat": 52.53, "radius_m": 50_000},
        headers=admin.headers,
    )
    assert too_far.status_code == 422

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/projects/{project.id}/features/propose",
        json={"lon": 4.61, "lat": 52.53},
        headers=viewer.headers,
    )
    assert refused.status_code == 403


async def test_an_unanswering_overpass_is_a_502_with_the_reason(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)

    async def failing_fetch(url: str, query: str) -> dict:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered 504",
            component="overpass",
        )

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", failing_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/propose",
        json={"lon": 4.61, "lat": 52.53},
        headers=admin.headers,
    )
    assert response.status_code == 502 and "504" in response.text


async def test_a_name_answers_the_areas_that_carry_it(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    asked: list[str] = []

    async def fake_fetch(url: str, query: str) -> dict:
        asked.append(query)
        return json.loads(BY_NAME.read_text())

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", fake_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/search-areas",
        json={"name": "Kraansvlak", "west": 4.40, "south": 52.30, "east": 4.75, "north": 52.55},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrowed"] is False
    assert body["attribution"].startswith("© OpenStreetMap")
    (found,) = body["candidates"]
    assert found["name"] == "Het Kraansvlak" and found["named"] is True
    assert found["kind"] == "osm" and found["osm_id"] == 1018618514
    assert 4_700_000 < found["area_m2"] < 4_800_000
    assert asked and '"Kraansvlak"' in asked[0].replace("\\", "")
    assert "(52.300000,4.400000,52.550000,4.750000)" in asked[0]

    short = await client.post(
        f"/api/v1/projects/{project.id}/features/search-areas",
        json={"name": "K", "west": 4.40, "south": 52.30, "east": 4.75, "north": 52.55},
        headers=admin.headers,
    )
    assert short.status_code == 422

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/projects/{project.id}/features/search-areas",
        json={"name": "Kraansvlak", "west": 4.40, "south": 52.30, "east": 4.75, "north": 52.55},
        headers=viewer.headers,
    )
    assert refused.status_code == 403


async def test_a_view_wider_than_the_widest_search_says_it_read_the_middle(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    asked: list[str] = []

    async def fake_fetch(url: str, query: str) -> dict:
        asked.append(query)
        return {"elements": []}

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", fake_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/search-areas",
        json={"name": "Kraansvlak", "west": 0.0, "south": 50.0, "east": 10.0, "north": 56.0},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrowed"] is True and body["candidates"] == []
    # the middle of the view, 1.5 degrees wide, not the whole of it
    assert "(52.250000,4.250000,53.750000,5.750000)" in asked[0]


async def test_a_name_search_an_unanswering_overpass_is_a_502(client, db, monkeypatch):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)

    async def failing_fetch(url: str, query: str) -> dict:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered 429",
            component="overpass",
        )

    monkeypatch.setattr("protect_api.routers.entities.fetch_overpass", failing_fetch)
    response = await client.post(
        f"/api/v1/projects/{project.id}/features/search-areas",
        json={"name": "Kraansvlak", "west": 4.40, "south": 52.30, "east": 4.75, "north": 52.55},
        headers=admin.headers,
    )
    assert response.status_code == 502 and "429" in response.text
