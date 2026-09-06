"""Entity groups (decision D98, ADR 0020): folders nested as deep as needed, an entity in at most one,
filters that include subgroups, devices grouped through their entity, and the map feature
carrying the group."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _catalogue(client, headers):
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=headers,
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
            headers=headers,
        )
    ).json()
    return device_type, entity_type


async def test_groups_two_levels_filters_and_devices(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    h = manager.headers
    base = f"/api/v1/projects/{project.id}"
    device_type, entity_type = await _catalogue(client, admin.headers)

    north = await client.post(
        f"{base}/groups", json={"name": "North", "color": "#52735E"}, headers=h
    )
    assert north.status_code == 201, north.text
    north = north.json()
    herd = (
        await client.post(
            f"{base}/groups", json={"name": "Herd A", "parent_id": north["id"]}, headers=h
        )
    ).json()
    south = (await client.post(f"{base}/groups", json={"name": "South"}, headers=h)).json()

    # any depth, but a tree: a group cannot move into itself or below itself
    family = (
        await client.post(
            f"{base}/groups", json={"name": "Family", "parent_id": herd["id"]}, headers=h
        )
    ).json()
    assert family["parent_id"] == herd["id"]
    into_itself = await client.patch(
        f"{base}/groups/{north['id']}", json={"parent_id": north["id"]}, headers=h
    )
    assert into_itself.status_code == 422
    into_own_subgroup = await client.patch(
        f"{base}/groups/{north['id']}", json={"parent_id": family["id"]}, headers=h
    )
    assert into_own_subgroup.status_code == 422
    moved = await client.patch(
        f"{base}/groups/{south['id']}", json={"parent_id": family["id"]}, headers=h
    )
    assert moved.status_code == 200, moved.text
    back = await client.patch(f"{base}/groups/{south['id']}", json={"parent_id": None}, headers=h)
    assert back.status_code == 200 and back.json()["parent_id"] is None
    same_name = await client.post(f"{base}/groups", json={"name": "North"}, headers=h)
    assert same_name.status_code == 409
    bad_colour = await client.post(
        f"{base}/groups", json={"name": "X", "color": "green"}, headers=h
    )
    assert bad_colour.status_code == 422

    # entities in the subgroup, the parent and none
    async def entity(name, group_id=None):
        created = await client.post(
            f"{base}/entities",
            json={"entity_type_id": entity_type["id"], "name": name, "group_id": group_id},
            headers=h,
        )
        assert created.status_code == 201, created.text
        return created.json()

    rhino = await entity("Rhino 14", herd["id"])
    ranger = await entity("Ranger 1", north["id"])
    calf = await entity("Calf", family["id"])
    loose = await entity("Loose")
    assert rhino["group_id"] == herd["id"] and loose["group_id"] is None
    other_project = await create_project(db)
    foreign = (
        await client.post(
            f"/api/v1/projects/{other_project.id}/groups",
            json={"name": "Elsewhere"},
            headers=admin.headers,
        )
    ).json()
    refused = await client.patch(
        f"{base}/entities/{loose['id']}", json={"group_id": foreign["id"]}, headers=h
    )
    assert refused.status_code == 404

    listed = (await client.get(f"{base}/groups", headers=h)).json()
    assert {(g["name"], g["parent_id"], g["entity_count"]) for g in listed} == {
        ("North", None, 1),
        ("South", None, 0),
        ("Herd A", north["id"], 1),
        ("Family", herd["id"], 1),
    }
    in_north = (
        await client.get(f"{base}/entities", params={"group_id": north["id"]}, headers=h)
    ).json()
    assert {e["name"] for e in in_north["items"]} == {"Rhino 14", "Ranger 1", "Calf"}
    in_herd = (
        await client.get(f"{base}/entities", params={"group_id": herd["id"]}, headers=h)
    ).json()
    assert {e["name"] for e in in_herd["items"]} == {"Rhino 14", "Calf"}
    ungrouped = (
        await client.get(f"{base}/entities", params={"ungrouped": "true"}, headers=h)
    ).json()
    assert [e["name"] for e in ungrouped["items"]] == ["Loose"]

    # a device is grouped through the entity it tracks today
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("SP"),
                "status": "active",
            },
            headers=admin.headers,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
        headers=admin.headers,
    )
    assigned = await client.post(
        f"{base}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": rhino["id"],
            "valid_from": "2026-06-02T00:00:00+00:00",
        },
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    devices = (
        await client.get(
            "/api/v1/devices",
            params={"project_id": str(project.id), "group_id": north["id"]},
            headers=h,
        )
    ).json()["items"]
    assert [(d["id"], d["entity_name"], d["group_id"]) for d in devices] == [
        (device["id"], "Rhino 14", herd["id"])
    ]
    none_in_south = (
        await client.get(
            "/api/v1/devices",
            params={"project_id": str(project.id), "group_id": south["id"]},
            headers=h,
        )
    ).json()["items"]
    assert none_in_south == []

    # deleting the top group removes everything below it and ungroups the three entities
    deleted = await client.delete(f"{base}/groups/{north['id']}", headers=h)
    assert deleted.status_code == 204
    assert [g["name"] for g in (await client.get(f"{base}/groups", headers=h)).json()] == ["South"]
    for e in (rhino, ranger, calf):
        read = (await client.get(f"{base}/entities/{e['id']}", headers=h)).json()
        assert read["group_id"] is None
    audit = (await client.get("/api/v1/admin/audit?limit=40", headers=admin.headers)).json()
    deletion = next(e for e in audit if e["action"] == "entity_group.deleted")
    assert deletion["details"] == {"name": "North", "subgroups": 2, "entities_ungrouped": 3}

    # a viewer reads groups and cannot write them
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(f"{base}/groups", headers=viewer.headers)).status_code == 200
    assert (
        await client.post(f"{base}/groups", json={"name": "Mine"}, headers=viewer.headers)
    ).status_code == 403


async def test_bulk_onboarding_puts_entities_in_a_group(client, db):
    from tests.api.test_attention_bulk import _unknown_identities

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    device_type, entity_type = await _catalogue(client, h)
    herd = (
        await client.post(f"/api/v1/projects/{project.id}/groups", json={"name": "Herd"}, headers=h)
    ).json()
    _source, identities = await _unknown_identities(client, h, 2)
    without_entities = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [i["id"] for i in identities],
            "device_type_id": device_type["id"],
            "project_id": str(project.id),
            "group_id": herd["id"],
        },
        headers=h,
    )
    assert without_entities.status_code == 422
    created = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [i["id"] for i in identities],
            "device_type_id": device_type["id"],
            "project_id": str(project.id),
            "entity_type_id": entity_type["id"],
            "group_id": herd["id"],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    assert created.json()["entities"] == 2
    in_herd = (
        await client.get(
            f"/api/v1/projects/{project.id}/entities", params={"group_id": herd["id"]}, headers=h
        )
    ).json()
    assert len(in_herd["items"]) == 2
    listed = (await client.get(f"/api/v1/projects/{project.id}/groups", headers=h)).json()
    assert listed[0]["entity_count"] == 2
