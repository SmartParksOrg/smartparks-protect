"""One test per role on a project resource and on a server-level resource."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _entity_type(client, admin):
    response = await client.post(
        "/api/v1/entity-types",
        json={
            "key": unique_name("t").replace("-", "_"),
            "label": "T",
            "group_key": "tracked",
            "icon_key": "wildlife.generic",
        },
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    ("role", "read", "write"),
    [
        (None, 403, 403),
        (Role.PROJECT_VIEWER, 200, 403),
        (Role.PROJECT_ADMIN, 200, 201),
        ("server-admin", 200, 201),
    ],
)
async def test_project_resource_by_role(client, db, role, read, write):
    server_admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    entity_type_id = await _entity_type(client, server_admin)
    if role == "server-admin":
        person = server_admin
    elif role is None:
        person = await actor(client, db)
    else:
        person = await project_actor(client, db, project, role)

    listed = await client.get(f"/api/v1/projects/{project.id}/entities", headers=person.headers)
    assert listed.status_code == read
    created = await client.post(
        f"/api/v1/projects/{project.id}/entities",
        json={"entity_type_id": entity_type_id, "name": unique_name("Rhino")},
        headers=person.headers,
    )
    assert created.status_code == write


async def test_anonymous_is_401(client, db):
    project = await create_project(db)
    assert (await client.get(f"/api/v1/projects/{project.id}/entities")).status_code == 401
    assert (await client.get("/api/v1/devices")).status_code == 401
    assert (await client.get("/api/v1/admin/users")).status_code == 401


async def test_unknown_project_is_404_for_everyone(client, db):
    person = await actor(client, db)
    admin = await actor(client, db, superuser=True)
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.get(f"/api/v1/projects/{missing}", headers=person.headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{missing}", headers=admin.headers)
    ).status_code == 404


async def test_server_level_resources_need_server_admin(client, db):
    project = await create_project(db)
    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    server_admin = await actor(client, db, superuser=True)
    body = {"key": unique_name("k").replace("-", "_"), "label": "K", "driver_key": "generic_json"}
    assert (
        await client.post("/api/v1/device-types", json=body, headers=project_admin.headers)
    ).status_code == 403
    assert (
        await client.post("/api/v1/device-types", json=body, headers=server_admin.headers)
    ).status_code == 201
    assert (
        await client.get("/api/v1/device-types", headers=project_admin.headers)
    ).status_code == 200
    assert (
        await client.get("/api/v1/admin/users", headers=project_admin.headers)
    ).status_code == 403
    assert (
        await client.get("/api/v1/data-sources", headers=project_admin.headers)
    ).status_code == 403


async def test_project_list_shows_only_memberships(client, db):
    mine = await create_project(db)
    await create_project(db)
    viewer = await project_actor(client, db, mine, Role.PROJECT_VIEWER)
    response = await client.get("/api/v1/projects", headers=viewer.headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["id"] for i in items] == [str(mine.id)]
    assert items[0]["role"] == "project-viewer"
