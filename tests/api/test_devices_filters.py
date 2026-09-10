"""The server admin's device list finds devices by data source, type, entity and any identity
(the Admin > Devices page of 2026-09-10), and every read names the sources of its identities."""

import pytest

from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_devices_filter_by_source_type_entity_and_identity(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    types = []
    for label in ("Collar", "Tracker"):
        types.append(
            (
                await client.post(
                    "/api/v1/device-types",
                    json={
                        "key": unique_name("gj").replace("-", "_"),
                        "label": label,
                        "driver_key": "generic_json",
                    },
                    headers=h,
                )
            ).json()
        )
    sources = []
    for name in ("Alpha", "Beta"):
        sources.append(
            (
                await client.post(
                    "/api/v1/data-sources",
                    json={"name": unique_name(name), "adapter_key": "generic_http"},
                    headers=h,
                )
            ).json()
        )
    devices = []
    for index in range(2):
        device = (
            await client.post(
                "/api/v1/devices",
                json={
                    "device_type_id": types[index]["id"],
                    "name": unique_name(f"SP{index}"),
                    "status": "active",
                },
                headers=h,
            )
        ).json()
        devices.append(device)
        identity = await client.post(
            f"/api/v1/data-sources/{sources[index]['id']}/identities",
            json={
                "data_source_id": sources[index]["id"],
                "external_id": f"IMEI{index}{unique_name('').strip('-')}",
                "identity_type": "imei",
            },
            headers=h,
        )
        assert identity.status_code == 201, identity.text
        linked = await client.patch(
            f"/api/v1/data-sources/{sources[index]['id']}/identities/{identity.json()['id']}",
            json={"device_id": device["id"]},
            headers=h,
        )
        assert linked.status_code == 200, linked.text
        joined = await client.post(
            f"/api/v1/devices/{device['id']}/project-assignments",
            json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
            headers=h,
        )
        assert joined.status_code == 201, joined.text
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
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=h,
        )
    ).json()
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

    async def ids(**params):
        response = await client.get("/api/v1/devices", params=params, headers=h)
        assert response.status_code == 200, response.text
        return {d["id"] for d in response.json()["items"]}

    ours = {d["id"] for d in devices}
    assert await ids(data_source_id=sources[0]["id"]) == {devices[0]["id"]}
    assert await ids(data_source_id=sources[1]["id"]) == {devices[1]["id"]}
    assert await ids(device_type_id=types[1]["id"]) == {devices[1]["id"]}
    assert await ids(project_id=str(project.id), has_entity="true") == {devices[0]["id"]}
    assert await ids(project_id=str(project.id), has_entity="false") == {devices[1]["id"]}
    # the search matches an identity, not only the name and the serial
    assert await ids(q="IMEI1") & ours == {devices[1]["id"]}
    assert await ids(q=devices[0]["name"]) == {devices[0]["id"]}
    # every read names the sources of its identities
    listed = (
        await client.get("/api/v1/devices", params={"q": devices[0]["name"]}, headers=h)
    ).json()
    assert listed["items"][0]["data_source_names"] == [sources[0]["name"]]
