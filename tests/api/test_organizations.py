"""Organizations as a grouping of projects (decision D92): server admin CRUD, the project
filter, and the rule that only a server admin moves a project between organizations."""

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor

pytestmark = pytest.mark.asyncio


async def test_organizations_group_projects(client, db):
    admin = await actor(client, db, superuser=True)
    created = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Kempen-Broek partners", "slug": "kempen-broek"},
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    organization = created.json()
    assert organization["project_count"] == 0
    duplicate = await client.post(
        "/api/v1/admin/organizations",
        json={"name": "Kempen-Broek partners", "slug": "other"},
        headers=admin.headers,
    )
    assert duplicate.status_code == 409
    project = await create_project(db)
    other = await create_project(db)
    moved = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"organization_id": organization["id"]},
        headers=admin.headers,
    )
    assert moved.status_code == 200 and moved.json()["organization_id"] == organization["id"]
    listed = await client.get("/api/v1/admin/organizations", headers=admin.headers)
    assert [o["project_count"] for o in listed.json() if o["id"] == organization["id"]] == [1]
    filtered = await client.get(
        "/api/v1/projects",
        params={"organization_id": organization["id"], "limit": 50},
        headers=admin.headers,
    )
    ids = {p["id"] for p in filtered.json()["items"]}
    assert str(project.id) in ids and str(other.id) not in ids
    renamed = await client.patch(
        f"/api/v1/admin/organizations/{organization['id']}",
        json={"name": "Kempen-Broek"},
        headers=admin.headers,
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Kempen-Broek"

    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    refused = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"organization_id": None},
        headers=project_admin.headers,
    )
    assert refused.status_code == 403
    same = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"organization_id": organization["id"], "description": "unchanged grouping"},
        headers=project_admin.headers,
    )
    assert same.status_code == 200
    member_view = await client.get(
        "/api/v1/projects",
        params={"organization_id": organization["id"]},
        headers=project_admin.headers,
    )
    assert [p["id"] for p in member_view.json()["items"]] == [str(project.id)]
    forbidden = await client.get("/api/v1/admin/organizations", headers=project_admin.headers)
    assert forbidden.status_code == 403

    deleted = await client.delete(
        f"/api/v1/admin/organizations/{organization['id']}", headers=admin.headers
    )
    assert deleted.status_code == 204
    orphaned = await client.get(f"/api/v1/projects/{project.id}", headers=admin.headers)
    assert orphaned.json()["organization_id"] is None
