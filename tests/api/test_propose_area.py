"""`POST /projects/{id}/features/propose` (phase 33, decision D270): the click's candidates
from a recorded Overpass answer, features:write to ask, a radius out of bounds refused, and a
502 with the reason when OpenStreetMap does not answer."""

import json
from pathlib import Path

import pytest

from shared.enums import ErrorCode, Role
from shared.trace import ApplicationError
from tests.api.conftest import create_project, project_actor

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "overpass" / "pwn_dunes.json"


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
