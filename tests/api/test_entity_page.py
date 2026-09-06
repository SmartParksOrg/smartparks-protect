"""The entity page (decision D106): a project admin assigns one of the project's unassigned
devices to an entity, the history names the device, the device names the entity, and ending
the assignment frees the device again."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_assign_from_the_entity_and_end_it(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    h = manager.headers
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
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
            },
            headers=admin.headers,
        )
    ).json()
    devices = []
    for name in ("SP0001", "SP0002"):
        device = (
            await client.post(
                "/api/v1/devices",
                json={
                    "device_type_id": device_type["id"],
                    "name": unique_name(name),
                    "status": "active",
                },
                headers=admin.headers,
            )
        ).json()
        joined = await client.post(
            f"/api/v1/devices/{device['id']}/project-assignments",
            json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
            headers=admin.headers,
        )
        assert joined.status_code == 201, joined.text
        devices.append(device)
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=h,
        )
    ).json()

    # both devices are candidates: in the project, tracking nothing
    candidates = await client.get(
        "/api/v1/devices",
        params={"project_id": str(project.id), "unassigned": "true"},
        headers=h,
    )
    assert candidates.status_code == 200, candidates.text
    assert {d["id"] for d in candidates.json()["items"]} == {d["id"] for d in devices}
    needs_project = await client.get("/api/v1/devices", params={"unassigned": "true"}, headers=h)
    assert needs_project.status_code == 422

    assigned = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": devices[0]["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-06-02T00:00:00+00:00",
        },
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text

    # the first device tracks the rhino now and is no longer a candidate
    candidates = (
        await client.get(
            "/api/v1/devices",
            params={"project_id": str(project.id), "unassigned": "true"},
            headers=h,
        )
    ).json()
    assert [d["id"] for d in candidates["items"]] == [devices[1]["id"]]
    history = (
        await client.get(
            f"/api/v1/projects/{project.id}/entity-assignments",
            params={"entity_id": entity["id"]},
            headers=h,
        )
    ).json()["items"]
    assert [(a["device_id"], a["device_name"], a["valid_to"]) for a in history] == [
        (devices[0]["id"], devices[0]["name"], None)
    ]
    detail = (await client.get(f"/api/v1/devices/{devices[0]['id']}", headers=h)).json()
    assert [a["entity_name"] for a in detail["entity_assignments"]] == ["Rhino 14"]

    # ending the assignment frees the device; the history keeps the row
    ended = await client.patch(
        f"/api/v1/projects/{project.id}/entity-assignments/{assigned.json()['id']}",
        json={"valid_to": "2026-06-03T00:00:00+00:00"},
        headers=h,
    )
    assert ended.status_code == 200, ended.text
    candidates = (
        await client.get(
            "/api/v1/devices",
            params={"project_id": str(project.id), "unassigned": "true"},
            headers=h,
        )
    ).json()
    assert {d["id"] for d in candidates["items"]} == {d["id"] for d in devices}
    history = (
        await client.get(
            f"/api/v1/projects/{project.id}/entity-assignments",
            params={"entity_id": entity["id"]},
            headers=h,
        )
    ).json()["items"]
    assert len(history) == 1 and history[0]["valid_to"].startswith("2026-06-03")

    # a viewer sees the history but cannot assign
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    seen = await client.get(
        f"/api/v1/projects/{project.id}/entity-assignments",
        params={"entity_id": entity["id"]},
        headers=viewer.headers,
    )
    assert seen.status_code == 200 and len(seen.json()["items"]) == 1
    refused = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": devices[1]["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-06-04T00:00:00+00:00",
        },
        headers=viewer.headers,
    )
    assert refused.status_code == 403
