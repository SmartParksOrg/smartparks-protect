"""Site-wide search (decision D99): one endpoint over what the caller may see."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_search_respects_what_the_caller_may_see(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    mine = await create_project(db, name=unique_name("Kruger search"))
    other = await create_project(db, name=unique_name("Elsewhere search"))
    member = await project_actor(client, db, mine, Role.PROJECT_VIEWER)
    tag = unique_name("zx").replace("-", "")[:8]
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
    for project, name in ((mine, f"Rhino {tag} mine"), (other, f"Rhino {tag} other")):
        created = await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": name},
            headers=h,
        )
        assert created.status_code == 201, created.text
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": f"Network {tag}", "adapter_key": "generic_http"},
            headers=h,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type["id"], "name": f"Collar {tag}", "status": "active"},
            headers=h,
        )
    ).json()
    eui = f"{tag.upper()}DEADBEEF"[:16]
    await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": eui},
        headers=h,
    )
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": mine.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
        headers=h,
    )

    # the server admin sees both entities, the device by its DevEUI, and the data source
    found = await client.get("/api/v1/search", params={"q": tag}, headers=h)
    assert found.status_code == 200, found.text
    body = found.json()
    assert {e["name"] for e in body["entities"]} == {f"Rhino {tag} mine", f"Rhino {tag} other"}
    assert [d["name"] for d in body["devices"]] == [f"Collar {tag}"]
    assert body["devices"][0]["project_id"] == str(mine.id)
    assert [s["name"] for s in body["data_sources"]] == [f"Network {tag}"]
    by_eui = (await client.get("/api/v1/search", params={"q": eui[:10]}, headers=h)).json()
    assert [d["name"] for d in by_eui["devices"]] == [f"Collar {tag}"]
    assert {
        p["name"]
        for p in (await client.get("/api/v1/search", params={"q": "search"}, headers=h)).json()[
            "projects"
        ]
    } >= {mine.name, other.name}

    # the member sees only the own project's entity, the device, no data sources
    seen = (await client.get("/api/v1/search", params={"q": tag}, headers=member.headers)).json()
    assert [e["name"] for e in seen["entities"]] == [f"Rhino {tag} mine"]
    assert seen["entities"][0]["subtitle"] == mine.name
    assert [d["name"] for d in seen["devices"]] == [f"Collar {tag}"]
    assert seen["data_sources"] == []
    assert [
        p["name"]
        for p in (
            await client.get("/api/v1/search", params={"q": "search"}, headers=member.headers)
        ).json()["projects"]
    ] == [mine.name]

    # bounded
    assert (
        await client.get("/api/v1/search", params={"q": tag, "limit": 51}, headers=h)
    ).status_code == 422
    assert (await client.get("/api/v1/search", params={"q": ""}, headers=h)).status_code == 422
