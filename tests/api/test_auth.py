import asyncio

import pytest

from shared.enums import Role
from tests.api.conftest import PASSWORD, actor, create_invitation, create_project, login
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_register_with_invitation_creates_membership(client, db):
    project = await create_project(db)
    email = f"{unique_name('invitee')}@example.org"
    invitation = await create_invitation(db, email=email, project=project, role=Role.PROJECT_ADMIN)

    info = await client.get("/api/v1/auth/invitation", params={"token": invitation.token})
    assert info.status_code == 200
    assert info.json()["project_name"] == project.name

    response = await client.post(
        "/api/v1/auth/register",
        json={"token": invitation.token, "password": PASSWORD, "full_name": "Test Person"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["email"] == email
    assert response.json()["is_verified"] is True

    token = await login(client, email)
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["is_superuser"] is False

    reused = await client.post(
        "/api/v1/auth/register", json={"token": invitation.token, "password": PASSWORD}
    )
    assert reused.status_code == 410


async def test_server_admin_invitation_sets_superuser(client, db):
    email = f"{unique_name('admin')}@example.org"
    invitation = await create_invitation(db, email=email, server_admin=True)
    response = await client.post(
        "/api/v1/auth/register", json={"token": invitation.token, "password": PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["is_superuser"] is True


async def test_expired_and_unknown_invitations(client, db):
    expired = await create_invitation(db, email="x@example.org", server_admin=True, expired=True)
    assert (
        await client.get("/api/v1/auth/invitation", params={"token": expired.token})
    ).status_code == 410
    assert (
        await client.get("/api/v1/auth/invitation", params={"token": "nope" * 5})
    ).status_code == 404


async def test_short_password_is_rejected(client, db):
    invitation = await create_invitation(db, email="short@example.org", server_admin=True)
    response = await client.post(
        "/api/v1/auth/register", json={"token": invitation.token, "password": "short"}
    )
    assert response.status_code == 422


async def test_password_change_invalidates_other_sessions(client, db):
    person = await actor(client, db)
    other_session_token = await login(client, person.user.email)
    await asyncio.sleep(1.1)  # JWT iat has whole seconds; the change must land in a later second

    response = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "another-good-password"},
        headers=person.headers,
    )
    assert response.status_code == 200, response.text
    fresh_token = response.json()["access_token"]

    assert (
        await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {other_session_token}"}
        )
    ).status_code == 401
    assert (
        await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {fresh_token}"})
    ).status_code == 200
    assert await login(client, person.user.email, "another-good-password")


async def test_wrong_password_and_anonymous(client, db):
    person = await actor(client, db)
    bad = await client.post(
        "/api/v1/auth/login", data={"username": person.user.email, "password": "wrong-password"}
    )
    assert bad.status_code == 400
    assert (await client.get("/api/v1/users/me")).status_code == 401
