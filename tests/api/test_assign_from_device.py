"""Assigning from the device's side (decision D170): the entity assignment call takes an
existing entity or makes a new one in the same transaction, and refuses both or neither."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _device_in_project(client, admin, project):
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=admin.headers,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type["id"], "name": unique_name("SP-new")},
            headers=admin.headers,
        )
    ).json()
    joined = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
        headers=admin.headers,
    )
    assert joined.status_code == 201, joined.text
    return device


async def test_assign_to_a_new_entity_or_an_existing_one(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    h = manager.headers
    types = (await client.get("/api/v1/entity-types", params={"limit": 500}, headers=h)).json()
    elephant = next(t for t in types["items"] if t["key"] == "elephant")
    device = await _device_in_project(client, admin, project)

    both = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": device["id"],
            "new_entity": {"entity_type_id": elephant["id"], "name": "x"},
            "valid_from": "2026-07-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert both.status_code == 422
    neither = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={"device_id": device["id"], "valid_from": "2026-07-01T00:00:00+00:00"},
        headers=h,
    )
    assert neither.status_code == 422

    name = unique_name("Elephant")
    created = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "new_entity": {"entity_type_id": elephant["id"], "name": name},
            "valid_from": "2026-07-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    assignment = created.json()
    assert assignment["entity_name"] == name and assignment["device_id"] == device["id"]
    entity = (
        await client.get(
            f"/api/v1/projects/{project.id}/entities/{assignment['entity_id']}", headers=h
        )
    ).json()
    assert entity["name"] == name and entity["entity_type_id"] == elephant["id"]

    # the device tracks it from that moment: a second assignment over the same time is refused
    other = await client.post(
        f"/api/v1/projects/{project.id}/entities",
        json={"entity_type_id": elephant["id"], "name": unique_name("Other")},
        headers=h,
    )
    overlap = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": other.json()["id"],
            "valid_from": "2026-08-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert overlap.status_code == 409
    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    assert [a["entity_name"] for a in detail["entity_assignments"] if not a["valid_to"]] == [name]
    assert [a["project_name"] for a in detail["project_assignments"]] == [project.name]
