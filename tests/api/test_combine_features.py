"""`POST /projects/{id}/features/union` and `/features/combine` (phase 33, decision D274):
several areas seen as one shape before anything is kept, then saved as one feature with the
parts left alone or taken with it, and the refusals around both."""

import pytest

from shared.enums import Role
from tests.api.conftest import create_project, project_actor

pytestmark = pytest.mark.asyncio


def _square(west: float, south: float, side: float = 0.01) -> dict:
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


async def _zone(client, headers, project, name: str, geometry: dict) -> str:
    created = await client.post(
        f"/api/v1/projects/{project.id}/features",
        json={"feature_type": "zone", "name": name, "geometry": geometry},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_two_areas_beside_each_other_are_one_shape(client, db):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    west = await _zone(client, admin.headers, project, "Duin", _square(4.60, 52.52))
    east = await _zone(client, admin.headers, project, "Kruidberg", _square(4.61, 52.52))

    response = await client.post(
        f"/api/v1/projects/{project.id}/features/union",
        json={"feature_ids": [west, east]},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parts"] == 1 and body["geometry"]["type"] == "Polygon"
    assert body["area_m2"] > 0

    # a candidate that is not saved yet joins the same way
    with_a_loose_shape = await client.post(
        f"/api/v1/projects/{project.id}/features/union",
        json={"feature_ids": [west], "geometries": [_square(4.62, 52.52)]},
        headers=admin.headers,
    )
    assert with_a_loose_shape.status_code == 200, with_a_loose_shape.text
    assert with_a_loose_shape.json()["parts"] == 2

    alone = await client.post(
        f"/api/v1/projects/{project.id}/features/union",
        json={"feature_ids": [west]},
        headers=admin.headers,
    )
    assert alone.status_code == 422

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/projects/{project.id}/features/union",
        json={"feature_ids": [west, east]},
        headers=viewer.headers,
    )
    assert refused.status_code == 403


async def test_the_parts_stay_unless_they_are_asked_to_go(client, db):
    project = await create_project(db)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    west = await _zone(client, admin.headers, project, "Duin", _square(4.60, 52.52))
    east = await _zone(client, admin.headers, project, "Kruidberg", _square(4.61, 52.52))

    combined = await client.post(
        f"/api/v1/projects/{project.id}/features/combine",
        json={
            "name": "Kennemerduinen",
            "feature_type": "zone",
            "feature_ids": [west, east],
        },
        headers=admin.headers,
    )
    assert combined.status_code == 201, combined.text
    whole = combined.json()
    assert whole["name"] == "Kennemerduinen" and whole["feature_type"] == "zone"
    assert whole["geometry"]["type"] == "Polygon"
    assert whole["attributes"]["combined_from"] == [west, east]

    listed = await client.get(f"/api/v1/projects/{project.id}/features", headers=admin.headers)
    names = {f["name"] for f in listed.json()["items"]}
    assert names == {"Duin", "Kruidberg", "Kennemerduinen"}

    # the same two, taken along this time
    taken = await client.post(
        f"/api/v1/projects/{project.id}/features/combine",
        json={
            "name": "Kennemerduinen west",
            "feature_type": "geofence",
            "feature_ids": [west, east],
            "remove_parts": True,
        },
        headers=admin.headers,
    )
    assert taken.status_code == 201, taken.text
    after = await client.get(f"/api/v1/projects/{project.id}/features", headers=admin.headers)
    assert {f["name"] for f in after.json()["items"]} == {
        "Kennemerduinen",
        "Kennemerduinen west",
    }


async def test_a_feature_of_another_project_and_a_single_part_are_refused(client, db):
    project = await create_project(db)
    other = await create_project(db, name="Another project")
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    elsewhere = await project_actor(client, db, other, Role.PROJECT_ADMIN)
    mine = await _zone(client, admin.headers, project, "Duin", _square(4.60, 52.52))
    theirs = await _zone(client, elsewhere.headers, other, "Theirs", _square(4.61, 52.52))

    across = await client.post(
        f"/api/v1/projects/{project.id}/features/combine",
        json={"name": "Both", "feature_type": "zone", "feature_ids": [mine, theirs]},
        headers=admin.headers,
    )
    assert across.status_code == 404

    one = await client.post(
        f"/api/v1/projects/{project.id}/features/combine",
        json={"name": "Alone", "feature_type": "zone", "feature_ids": [mine]},
        headers=admin.headers,
    )
    assert one.status_code == 422

    line = await _zone(
        client,
        admin.headers,
        project,
        "Path",
        {"type": "LineString", "coordinates": [[4.60, 52.52], [4.61, 52.53]]},
    )
    no_areas = await client.post(
        f"/api/v1/projects/{project.id}/features/combine",
        json={"name": "Lines", "feature_type": "zone", "feature_ids": [line, line]},
        headers=admin.headers,
    )
    assert no_areas.status_code == 422 and "area" in no_areas.text
