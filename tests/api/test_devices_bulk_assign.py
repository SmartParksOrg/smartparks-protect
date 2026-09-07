"""Bulk assignment (decision D122): devices in no project join a project in one call, from
their first data, optionally with an entity each; devices assigned elsewhere are skipped."""

import pytest

from tests.api.conftest import actor, create_project
from tests.api.test_attention_bulk import _unknown_identities
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_bulk_assign_from_first_data_with_entities_and_skips(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    other = await create_project(db)
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
    _source, identities = await _unknown_identities(client, h, 3)
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
    first, second, third = created["device_ids"]
    # the third device is elsewhere already
    elsewhere = await client.post(
        f"/api/v1/devices/{third}/project-assignments",
        json={"project_id": str(other.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    assert elsewhere.status_code == 201, elsewhere.text

    result = await client.post(
        "/api/v1/devices/bulk-assign",
        json={
            "device_ids": [first, second, third, first],
            "project_id": str(project.id),
            "entity_type_id": entity_type["id"],
        },
        headers=h,
    )
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["assigned"] == 2 and body["entities"] == 2
    assert [s["device_id"] for s in body["skipped"]] == [third]
    assert body["skipped"][0]["reason"].startswith("assigned to ")

    detail = (await client.get(f"/api/v1/devices/{first}", headers=h)).json()
    assignment = detail["project_assignments"][0]
    assert assignment["project_id"] == str(project.id)
    # from the identity's first seen, the earliest thing known about the device
    assert assignment["valid_from"] == identities[0]["first_seen_at"]
    assert detail["entity_assignments"][0]["valid_from"] == assignment["valid_from"]
    entities = (
        await client.get(f"/api/v1/projects/{project.id}/entities?limit=100", headers=h)
    ).json()["items"]
    assert detail["name"] in [e["name"] for e in entities]

    # a second run skips what is in the project already, with a fixed start
    again = (
        await client.post(
            "/api/v1/devices/bulk-assign",
            json={
                "device_ids": [first],
                "project_id": str(project.id),
                "valid_from": "2026-09-01T00:00:00+00:00",
            },
            headers=h,
        )
    ).json()
    assert again["assigned"] == 0 and again["skipped"][0]["reason"] == "already in this project"

    # not a server admin: no
    member = await actor(client, db, superuser=False)
    denied = await client.post(
        "/api/v1/devices/bulk-assign",
        json={"device_ids": [second], "project_id": str(project.id)},
        headers=member.headers,
    )
    assert denied.status_code == 403
