"""Bulk actions in the project scope (decision D294): an entity per device from a selection,
named per row; the bulk assignment with names per device, open to the target's admins."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_attention_bulk import _unknown_identities
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _devices_in_project(client, db, count: int = 3):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=h,
        )
    ).json()
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
            },
            headers=h,
        )
    ).json()
    _source, identities = await _unknown_identities(client, h, count)
    created = (
        await client.post(
            "/api/v1/attention/identities/bulk-create-devices",
            json={
                "identity_ids": [i["id"] for i in identities],
                "device_type_id": device_type["id"],
                "project_id": str(project.id),
                "reprocess": False,
            },
            headers=h,
        )
    ).json()
    return admin, project, entity_type, created["device_ids"], identities


async def test_an_entity_per_device_named_per_row(client, db):
    admin, project, entity_type, device_ids, identities = await _devices_in_project(client, db)
    h = admin.headers
    first, second, third = device_ids
    # the third tracks something already
    tracked = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": third,
            "valid_from": identities[2]["first_seen_at"],
            "new_entity": {"name": "Taken", "entity_type_id": entity_type["id"]},
        },
        headers=h,
    )
    assert tracked.status_code == 201, tracked.text
    result = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments/bulk",
        json={
            "items": [
                {"device_id": first, "name": "Rhino 14"},
                {"device_id": second, "name": "Taken"},
                {"device_id": third, "name": "Rhino 16"},
            ],
            "entity_type_id": entity_type["id"],
            "start": "joined",
        },
        headers=h,
    )
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["created"] == 1
    assert [(s["name"], s["reason"]) for s in body["skipped"]] == [
        ("Taken", "an entity of that name exists"),
        ("Rhino 16", "tracks an entity from the start on; release it first"),
    ]
    detail = (await client.get(f"/api/v1/devices/{first}", headers=h)).json()
    [assignment] = detail["entity_assignments"]
    assert assignment["entity_name"] == "Rhino 14"
    # since it joined: the project assignment's start
    assert assignment["valid_from"] == detail["project_assignments"][0]["valid_from"]
    entities = (
        await client.get(f"/api/v1/projects/{project.id}/entities?limit=10", headers=h)
    ).json()["items"]
    assert sorted(e["name"] for e in entities) == ["Rhino 14", "Taken"]
    # a project admin may; a viewer may not
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    denied = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments/bulk",
        json={"items": [{"device_id": second, "name": "X"}], "entity_type_id": entity_type["id"]},
        headers=viewer.headers,
    )
    assert denied.status_code == 403


async def test_bulk_assign_takes_names_and_the_target_admin(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=h,
        )
    ).json()
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
            },
            headers=h,
        )
    ).json()
    _source, identities = await _unknown_identities(client, h, 2)
    created = (
        await client.post(
            "/api/v1/attention/identities/bulk-create-devices",
            json={
                "identity_ids": [i["id"] for i in identities],
                "device_type_id": device_type["id"],
                "reprocess": False,
            },
            headers=h,
        )
    ).json()
    first, second = created["device_ids"]
    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    result = await client.post(
        "/api/v1/devices/bulk-assign",
        json={
            "device_ids": [first, second],
            "project_id": str(project.id),
            "entity_type_id": entity_type["id"],
            "names": {first: "Elephant 3"},
        },
        headers=project_admin.headers,
    )
    assert result.status_code == 201, result.text
    assert result.json()["assigned"] == 2 and result.json()["entities"] == 2
    entities = (
        await client.get(f"/api/v1/projects/{project.id}/entities?limit=10", headers=h)
    ).json()["items"]
    second_name = (await client.get(f"/api/v1/devices/{second}", headers=h)).json()["name"]
    assert sorted(e["name"] for e in entities) == sorted(["Elephant 3", second_name])
