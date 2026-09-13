"""Roles, custom roles and a member's scope (decisions D185 to D188): the catalogue, the
roles endpoints, a member with a custom role, and a scoped member across the reads."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.enums import Role
from shared.models import Group, ProjectMembership
from tests.api.conftest import create_project, create_user, login, project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_catalogue_and_custom_roles(client, db, bus):  # noqa: F811
    admin, project, _entity, _source, _device, _external = await _setup(client, db)
    h = admin.headers
    catalogue = (await client.get("/api/v1/permissions", headers=h)).json()
    assert next(a["key"] for a in catalogue["areas"]) == "see"
    assert {r["key"] for r in catalogue["roles"]} == set(Role)
    base = f"/api/v1/projects/{project.id}/roles"
    assert (await client.get(base, headers=h)).json() == []

    bad = await client.post(
        base, json={"name": "Ranger", "permissions": ["exports:everything"]}, headers=h
    )
    assert bad.status_code == 422 and "exports:everything" in bad.text
    created = await client.post(
        base,
        json={
            "name": "Ranger",
            "description": "Events and control, no exports",
            "permissions": ["events:write", "devices:control"],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["permissions"] == ["devices:control", "events:write", "project:read"]
    assert (await client.post(base, json={"name": "Ranger"}, headers=h)).status_code == 409

    # a member with the custom role: events yes, exports and rules no
    user = await create_user(db)
    added = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"email": user.email, "role": "project-viewer", "role_id": role["id"]},
        headers=h,
    )
    assert added.status_code == 201, added.text
    member = added.json()
    assert member["role_name"] == "Ranger" and "events:write" in member["permissions"]
    token = await login(client, user.email)
    ranger = {"Authorization": f"Bearer {token}"}
    mine = (await client.get("/api/v1/projects", headers=ranger)).json()["items"]
    assert mine[0]["permissions"] == ["devices:control", "events:write", "project:read"]
    assert mine[0]["scope_limited"] is False
    event = await client.post(
        f"/api/v1/projects/{project.id}/events",
        json={
            "event_type": "SIGHTING",
            "severity": "info",
            "title": "Seen by the ranger",
            "time": datetime.now(UTC).isoformat(),
        },
        headers=ranger,
    )
    assert event.status_code == 201, event.text
    assert (
        await client.get(f"/api/v1/projects/{project.id}/exports", headers=ranger)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={
                "dataset": "positions",
                "format": "csv",
                "time_from": "2026-01-01T00:00:00+00:00",
                "time_to": "2026-01-02T00:00:00+00:00",
            },
            headers=ranger,
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/projects/{project.id}/roles", json={"name": "X"}, headers=ranger
        )
    ).status_code == 403

    # the role in use cannot be deleted; renamed and narrowed it can
    assert (await client.delete(f"{base}/{role['id']}", headers=h)).status_code == 409
    patched = await client.patch(
        f"{base}/{role['id']}", json={"permissions": ["events:write"]}, headers=h
    )
    assert patched.json()["permissions"] == ["events:write", "project:read"]
    assert patched.json()["members"] == 1
    cleared = await client.patch(
        f"/api/v1/projects/{project.id}/members/{member['id']}", json={"role_id": None}, headers=h
    )
    assert cleared.json()["role_name"] == "Viewer" and cleared.json()["role_id"] is None
    assert (await client.delete(f"{base}/{role['id']}", headers=h)).status_code == 204


async def test_a_scoped_member_sees_only_the_scope(client, db, bus):  # noqa: F811
    admin, project, entity, source, device, external_id = await _setup(client, db)
    h = admin.headers
    # a second entity in a group, with its own device and data
    group = Group(project_id=project.id, name=unique_name("North"))
    db.add(group)
    await db.commit()
    other_entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={
                "name": unique_name("Buffalo"),
                "entity_type_id": entity["entity_type_id"],
                "group_id": str(group.id),
            },
            headers=h,
        )
    ).json()
    other_device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device["device_type_id"], "name": unique_name("SP-north")},
            headers=h,
        )
    ).json()
    for path, body in (
        (
            f"/api/v1/devices/{other_device['id']}/project-assignments",
            {"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        ),
        (
            f"/api/v1/projects/{project.id}/entity-assignments",
            {
                "entity_id": other_entity["id"],
                "device_id": other_device["id"],
                "valid_from": "2026-01-01T00:00:00+00:00",
            },
        ),
    ):
        response = await client.post(path, json=body, headers=h)
        assert response.status_code == 201, response.text
    identity = await client.post(
        f"/api/v1/devices/{other_device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": uuid.uuid4().hex[:16].upper()},
        headers=h,
    )
    assert identity.status_code == 201, identity.text
    other_external = identity.json()["external_id"]
    now = datetime.now(UTC).replace(microsecond=0)
    await _feed(db, bus, source["id"], external_id, now - timedelta(minutes=5), -24.9, 31.5)
    await _feed(db, bus, source["id"], other_external, now - timedelta(minutes=4), -24.8, 31.6)

    # a viewer scoped to the group sees the buffalo and its device, not the rhino
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    membership = await db.scalar(
        select_membership := __import__("sqlalchemy")
        .select(ProjectMembership)
        .where(
            ProjectMembership.user_id == viewer.user.id, ProjectMembership.project_id == project.id
        )
    )
    del select_membership
    scoped = await client.patch(
        f"/api/v1/projects/{project.id}/members/{membership.id}",
        json={"scope": {"groups": [str(group.id)]}},
        headers=h,
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["scope"]["groups"] == [str(group.id)]
    v = viewer.headers
    base = f"/api/v1/projects/{project.id}"
    assert (await client.get("/api/v1/projects", headers=v)).json()["items"][0][
        "scope_limited"
    ] is True
    names = {e["name"] for e in (await client.get(f"{base}/entities", headers=v)).json()["items"]}
    assert names == {other_entity["name"]}
    assert (await client.get(f"{base}/entities/{entity['id']}", headers=v)).status_code == 404
    assert (await client.get(f"{base}/entities/{other_entity['id']}", headers=v)).status_code == 200
    groups = (await client.get(f"{base}/groups", headers=v)).json()
    assert [g["id"] for g in groups] == [str(group.id)]
    devices = (
        await client.get("/api/v1/devices", params={"project_id": str(project.id)}, headers=v)
    ).json()["items"]
    assert {d["id"] for d in devices} == {other_device["id"]}
    assert (await client.get(f"/api/v1/devices/{device['id']}", headers=v)).status_code == 404
    current = (await client.get(f"{base}/map/current", headers=v)).json()
    assert [f["properties"]["entity_id"] for f in current["features"]] == [other_entity["id"]]
    assert current["total"] == 1
    positions = (await client.get(f"{base}/positions", headers=v)).json()
    assert {p["entity_id"] for p in positions} == {other_entity["id"]}
    events = (await client.get(f"{base}/events", headers=v)).json()["items"]
    assert all(e["entity_id"] in (other_entity["id"], None) for e in events)
    at = (now - timedelta(minutes=5)).isoformat()
    assert (
        await client.get(
            f"{base}/positions/at", params={"entity_id": entity["id"], "time": at}, headers=v
        )
    ).status_code == 404
    records = await client.get(f"{base}/records", params={"entity_id": entity["id"]}, headers=v)
    assert records.status_code == 404
    connectivity = (await client.get(f"{base}/connectivity", headers=v)).json()
    assert {c["device_id"] for c in connectivity} <= {other_device["id"]}
    found = (await client.get("/api/v1/search", params={"q": entity["name"][:6]}, headers=v)).json()
    assert entity["id"] not in {e["id"] for e in found["entities"]}

    # an export narrows to the scope
    analyst = await project_actor(client, db, project, Role.PROJECT_ANALYST)
    analyst_membership = await db.scalar(
        __import__("sqlalchemy")
        .select(ProjectMembership)
        .where(
            ProjectMembership.user_id == analyst.user.id, ProjectMembership.project_id == project.id
        )
    )
    await client.patch(
        f"{base}/members/{analyst_membership.id}",
        json={"scope": {"entities": [other_entity["id"]]}},
        headers=h,
    )
    job = await client.post(
        f"{base}/exports",
        json={
            "dataset": "positions",
            "format": "csv",
            "time_from": (now - timedelta(hours=1)).isoformat(),
            "time_to": now.isoformat(),
        },
        headers=analyst.headers,
    )
    assert job.status_code == 201, job.text
    assert job.json()["parameters"]["entity_ids"] == [other_entity["id"]]
    outside = await client.post(
        f"{base}/exports",
        json={
            "dataset": "positions",
            "format": "csv",
            "time_from": (now - timedelta(hours=1)).isoformat(),
            "time_to": now.isoformat(),
            "entity_ids": [entity["id"]],
        },
        headers=analyst.headers,
    )
    assert outside.status_code == 422

    # the admin sees everything, and an unscoped viewer too
    assert len((await client.get(f"{base}/entities", headers=h)).json()["items"]) == 2
    plain = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert len((await client.get(f"{base}/entities", headers=plain.headers)).json()["items"]) == 2

    # a scope of another project's group is refused
    other_project = await create_project(db)
    stranger_group = Group(project_id=other_project.id, name=unique_name("Elsewhere"))
    db.add(stranger_group)
    await db.commit()
    refused = await client.patch(
        f"{base}/members/{membership.id}",
        json={"scope": {"groups": [str(stranger_group.id)]}},
        headers=h,
    )
    assert refused.status_code == 422


async def test_an_invitation_carries_role_and_scope(client, db, bus):  # noqa: F811
    admin, project, entity, _source, _device, _external = await _setup(client, db)
    h = admin.headers
    role = (
        await client.post(
            f"/api/v1/projects/{project.id}/roles",
            json={"name": "Watcher", "permissions": ["events:write"]},
            headers=h,
        )
    ).json()
    email = f"{unique_name('watcher').lower()}@example.org"
    invited = await client.post(
        f"/api/v1/projects/{project.id}/invitations",
        json={
            "email": email,
            "role": "project-viewer",
            "role_id": role["id"],
            "scope": {"entities": [entity["id"]]},
        },
        headers=h,
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    assert body["role_id"] == role["id"] and body["scope"]["entities"] == [entity["id"]]
    from shared.models import Invitation

    invitation = await db.get(Invitation, uuid.UUID(body["id"]))
    registered = await client.post(
        "/api/v1/auth/register",
        json={"token": invitation.token, "password": "Watcher-pass-123456", "full_name": "W"},
    )
    assert registered.status_code in (200, 201), registered.text
    token = await login(client, email, "Watcher-pass-123456")
    mine = (
        await client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    ).json()["items"]
    assert (
        mine[0]["permissions"] == ["events:write", "project:read"]
        and mine[0]["scope_limited"] is True
    )
