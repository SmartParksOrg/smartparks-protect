"""The server admin's user page (decision D189): one account with its memberships across
projects, name and email editing, and a password reset mail on the person's behalf."""

import uuid

import pytest
from sqlalchemy import select

from shared.enums import Role
from shared.models import Invitation
from tests.api.conftest import (
    actor,
    add_member,
    create_project,
    create_user,
    login,
    project_actor,
)

pytestmark = pytest.mark.asyncio


async def test_detail_lists_memberships_with_role_and_scope(client, db):
    admin = await actor(client, db, superuser=True)
    first = await create_project(db, "Alpha park")
    second = await create_project(db, "Beta park")
    user = await create_user(db)
    await add_member(db, user, first, Role.PROJECT_VIEWER)
    h = admin.headers

    # a custom role and a scope on the second project, set through the members endpoints
    role = (
        await client.post(
            f"/api/v1/projects/{second.id}/roles",
            json={"name": "Ranger", "permissions": ["events:write"]},
            headers=h,
        )
    ).json()
    added = await client.post(
        f"/api/v1/projects/{second.id}/members",
        json={"email": user.email, "role": "project-viewer", "role_id": role["id"]},
        headers=h,
    )
    assert added.status_code == 201, added.text

    detail = await client.get(f"/api/v1/admin/users/{user.id}", headers=h)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["email"] == user.email
    by_project = {m["project_name"]: m for m in body["memberships"]}
    assert set(by_project) == {"Alpha park", "Beta park"}
    assert by_project["Alpha park"]["role_name"] == "Viewer"
    assert by_project["Alpha park"]["scope"] is None
    assert by_project["Alpha park"]["membership_id"]
    ranger = by_project["Beta park"]
    assert ranger["role_id"] == role["id"] and ranger["role_name"] == "Ranger"
    assert ranger["permissions"] == ["events:write", "project:read"]

    # the membership row's id is the one the members endpoints take
    narrowed = await client.patch(
        f"/api/v1/projects/{second.id}/members/{ranger['membership_id']}",
        json={"scope": {"groups": [], "entities": [], "devices": []}},
        headers=h,
    )
    assert narrowed.status_code == 200, narrowed.text
    again = (await client.get(f"/api/v1/admin/users/{user.id}", headers=h)).json()
    assert {m["project_name"] for m in again["memberships"]} == {"Alpha park", "Beta park"}


async def test_edit_name_and_email(client, db):
    admin = await actor(client, db, superuser=True)
    user = await create_user(db)
    other = await create_user(db)
    h = admin.headers

    renamed = await client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={"full_name": "Ada Ranger", "email": "Ada.Ranger@example.org"},
        headers=h,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["full_name"] == "Ada Ranger"
    assert renamed.json()["email"] == "ada.ranger@example.org"
    assert "memberships" in renamed.json()
    # the person signs in with the new address
    assert await login(client, "ada.ranger@example.org")

    taken = await client.patch(
        f"/api/v1/admin/users/{user.id}", json={"email": other.email}, headers=h
    )
    assert taken.status_code == 409, taken.text
    malformed = await client.patch(
        f"/api/v1/admin/users/{user.id}", json={"email": "not an address"}, headers=h
    )
    assert malformed.status_code == 422


async def test_password_reset_on_behalf(client, db):
    admin = await actor(client, db, superuser=True)
    user = await create_user(db)
    h = admin.headers

    sent = await client.post(f"/api/v1/admin/users/{user.id}/password-reset", headers=h)
    assert sent.status_code == 202, sent.text
    assert sent.json() == {"status": "sent"}
    audit = (await client.get("/api/v1/admin/audit", params={"limit": 20}, headers=h)).json()
    assert any(
        row["action"] == "user.password_reset_sent" and row["object_id"] == str(user.id)
        for row in audit
    )

    off = await client.patch(f"/api/v1/admin/users/{user.id}", json={"is_active": False}, headers=h)
    assert off.status_code == 200
    refused = await client.post(f"/api/v1/admin/users/{user.id}/password-reset", headers=h)
    assert refused.status_code == 409


async def test_user_page_is_server_admin_only(client, db):
    project = await create_project(db)
    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    target = await create_user(db)
    for method, path in (
        ("GET", f"/api/v1/admin/users/{target.id}"),
        ("PATCH", f"/api/v1/admin/users/{target.id}"),
        ("POST", f"/api/v1/admin/users/{target.id}/password-reset"),
    ):
        response = await client.request(
            method, path, headers=project_admin.headers, json={} if method == "PATCH" else None
        )
        assert response.status_code == 403, (method, path, response.text)
    admin = await actor(client, db, superuser=True)
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.get(f"/api/v1/admin/users/{missing}", headers=admin.headers)
    ).status_code == 404


async def test_server_invitation_for_several_projects(client, db):
    """A server admin's invitation carries memberships in several projects (D190): one row,
    one link, every membership created at registration, with a custom role and a scope."""
    admin = await actor(client, db, superuser=True)
    first = await create_project(db, "Alpha park")
    second = await create_project(db, "Beta park")
    h = admin.headers
    role = (
        await client.post(
            f"/api/v1/projects/{second.id}/roles",
            json={"name": "Ranger", "permissions": ["events:write"]},
            headers=h,
        )
    ).json()
    email = f"{uuid.uuid4().hex[:8]}@example.org"

    empty = await client.post("/api/v1/admin/invitations", json={"email": email}, headers=h)
    assert empty.status_code == 422
    twice = await client.post(
        "/api/v1/admin/invitations",
        json={
            "email": email,
            "memberships": [{"project_id": str(first.id)}, {"project_id": str(first.id)}],
        },
        headers=h,
    )
    assert twice.status_code == 422
    wrong_role = await client.post(
        "/api/v1/admin/invitations",
        json={
            "email": email,
            "memberships": [{"project_id": str(first.id), "role_id": role["id"]}],
        },
        headers=h,
    )
    assert wrong_role.status_code == 422

    created = await client.post(
        "/api/v1/admin/invitations",
        json={
            "email": email,
            "server_admin": False,
            "memberships": [
                {"project_id": str(first.id), "role": "project-analyst"},
                {
                    "project_id": str(second.id),
                    "role": "project-viewer",
                    "role_id": role["id"],
                    "scope": {"groups": [], "entities": [], "devices": []},
                },
            ],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["user_id"] is None and result["added_projects"] == []
    invitation = result["invitation"]
    assert invitation["server_admin"] is False and invitation["project_id"] is None
    assert [m["project_id"] for m in invitation["memberships"]] == [str(first.id), str(second.id)]
    assert invitation["registration_link"] or invitation["mail_sent"]
    listed = (await client.get("/api/v1/admin/invitations", headers=h)).json()["items"]
    assert any(i["id"] == invitation["id"] and i["memberships"] for i in listed)

    # the link names both projects; registration creates both memberships
    token = (
        await db.execute(select(Invitation.token).where(Invitation.id == invitation["id"]))
    ).scalar_one()
    info = await client.get("/api/v1/auth/invitation", params={"token": token})
    assert info.status_code == 200, info.text
    assert info.json()["project_names"] == ["Alpha park", "Beta park"]
    registered = await client.post(
        "/api/v1/auth/register",
        json={"token": token, "password": "Newcomer-pass-123456", "full_name": "N"},
    )
    assert registered.status_code == 201, registered.text
    user_id = registered.json()["id"]
    detail = (await client.get(f"/api/v1/admin/users/{user_id}", headers=h)).json()
    by_project = {m["project_name"]: m for m in detail["memberships"]}
    assert by_project["Alpha park"]["role"] == "project-analyst"
    assert by_project["Beta park"]["role_name"] == "Ranger"
    assert by_project["Beta park"]["scope"] is None
    mine = (
        await client.get(
            "/api/v1/projects",
            headers={
                "Authorization": f"Bearer {await login(client, email, 'Newcomer-pass-123456')}"
            },
        )
    ).json()["items"]
    assert {p["name"] for p in mine} == {"Alpha park", "Beta park"}


async def test_server_invitation_for_an_existing_account_adds_now(client, db):
    admin = await actor(client, db, superuser=True)
    first = await create_project(db, "Alpha park")
    second = await create_project(db, "Beta park")
    user = await create_user(db)
    await add_member(db, user, first, Role.PROJECT_VIEWER)
    h = admin.headers

    added = await client.post(
        "/api/v1/admin/invitations",
        json={
            "email": user.email.upper(),
            "server_admin": True,
            "memberships": [
                {"project_id": str(first.id), "role": "project-admin"},
                {"project_id": str(second.id), "role": "project-operator"},
            ],
        },
        headers=h,
    )
    assert added.status_code == 201, added.text
    result = added.json()
    assert result["invitation"] is None and result["user_id"] == str(user.id)
    assert result["added_projects"] == ["Beta park"]
    detail = (await client.get(f"/api/v1/admin/users/{user.id}", headers=h)).json()
    assert detail["is_superuser"] is True
    by_project = {m["project_name"]: m["role"] for m in detail["memberships"]}
    # the membership that existed keeps its role; the new one has the role asked
    assert by_project == {"Alpha park": "project-viewer", "Beta park": "project-operator"}
    invitations = (await client.get("/api/v1/admin/invitations", headers=h)).json()["items"]
    assert not any(i["email"] == user.email for i in invitations)
