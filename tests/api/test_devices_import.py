import pytest

from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _setup(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("dt").replace("-", "_"),
                "label": "T",
                "driver_key": "opencollar",
            },
            headers=h,
        )
    ).json()
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("KPN"), "adapter_key": "kpn_thingpark"},
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
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Elephant 3"},
            headers=h,
        )
    ).json()
    return admin, project, device_type, source, entity


def _csv(rows: list[str]) -> bytes:
    header = (
        "device_name,external_identifier,device_type,datasource,project,effective_from,entity\n"
    )
    return (header + "\n".join(rows) + "\n").encode()


async def test_import_creates_devices_identities_and_assignments(client, db):
    admin, project, device_type, source, entity = await _setup(client, db)
    n1, n2 = unique_name("SP05"), unique_name("SP05")
    content = _csv(
        [
            f"{n1},70B3D57ED000AAAA,{device_type['key']},{source['name']},{project.name},2026-03-01T00:00:00+00:00,Elephant 3",
            f"{n2},70B3D57ED000BBBB,{device_type['key']},{source['name']},{project.name},2026-03-01T00:00:00+00:00,",
        ]
    )
    response = await client.post(
        "/api/v1/devices/import",
        files={"file": ("devices.csv", content, "text/csv")},
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 2
    first = response.json()["rows"][0]["device_id"]
    detail = (await client.get(f"/api/v1/devices/{first}", headers=admin.headers)).json()
    assert detail["project_assignments"][0]["project_id"] == str(project.id)
    assert detail["entity_assignments"][0]["entity_id"] == entity["id"]
    assert detail["external_identities"][0]["external_id"] == "70B3D57ED000AAAA"


async def test_import_is_all_or_nothing(client, db):
    admin, project, device_type, source, _ = await _setup(client, db)
    good, bad = unique_name("SP05"), unique_name("SP05")
    content = _csv(
        [
            f"{good},70B3D57ED000CCCC,{device_type['key']},{source['name']},{project.name},2026-03-01T00:00:00+00:00,",
            f"{bad},70B3D57ED000DDDD,{device_type['key']},{source['name']},{project.name},2026-03-01,",  # naive time
        ]
    )
    response = await client.post(
        "/api/v1/devices/import",
        files={"file": ("devices.csv", content, "text/csv")},
        headers=admin.headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["rows"][1]["status"] == "error"
    listed = (await client.get("/api/v1/devices", params={"q": good}, headers=admin.headers)).json()
    assert listed["items"] == []


async def test_data_source_credentials_are_write_only(client, db):
    admin = await actor(client, db, superuser=True)
    created = await client.post(
        "/api/v1/data-sources",
        json={
            "name": unique_name("LORIOT"),
            "adapter_key": "loriot",
            "credentials": {"token": "abc"},
        },
        headers=admin.headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["has_credentials"] is True and "credentials" not in body
    fetched = (await client.get(f"/api/v1/data-sources/{body['id']}", headers=admin.headers)).json()
    assert "credentials" not in fetched and "credentials_encrypted" not in fetched


async def test_pagination_cursor_walks_all_items(client, db):
    admin = await actor(client, db, superuser=True)
    for _ in range(3):
        await client.post(
            "/api/v1/metrics",
            json={
                "key": unique_name("m").replace("-", "_"),
                "label": "M",
                "value_type": "numeric",
                "category": "test",
            },
            headers=admin.headers,
        )
    seen, cursor = [], None
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        pageresp = (
            await client.get("/api/v1/metrics", params=params, headers=admin.headers)
        ).json()
        seen += [i["key"] for i in pageresp["items"]]
        cursor = pageresp["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) >= 3
