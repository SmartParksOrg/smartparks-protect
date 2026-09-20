"""Archiving and deleting a project (decision D267): an archived project leaves the members'
list, the switcher and the all scope and refuses its members, while a server admin still
opens it; only a server admin archives; a delete takes an archived project whose name is
typed, and leaves the devices and the readings behind, released from the project."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from shared.enums import Role
from shared.models import AuditLog, Device, DeviceProjectAssignment, Entity, Position, Project
from tests.api.conftest import project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_an_archived_project_hides_from_members_and_the_all_scope(client, db):
    admin, project, entity, _source, _device, _external_id = await _setup(client, db)
    member = await project_actor(client, db, project, Role.PROJECT_ADMIN)

    refused = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"archived_at": datetime.now(UTC).isoformat()},
        headers=member.headers,
    )
    assert refused.status_code == 403, refused.text

    archived = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"archived_at": datetime.now(UTC).isoformat()},
        headers=admin.headers,
    )
    assert archived.status_code == 200 and archived.json()["archived_at"], archived.text
    audit = (
        await db.scalars(
            select(AuditLog).where(AuditLog.object_id == str(project.id)).order_by(AuditLog.id)
        )
    ).all()
    assert audit[-1].action == "project.archived"

    listed = await client.get("/api/v1/projects", headers=member.headers)
    assert str(project.id) not in {p["id"] for p in listed.json()["items"]}
    opened = await client.get(f"/api/v1/projects/{project.id}", headers=member.headers)
    assert opened.status_code == 403 and "archived" in opened.text
    for_admin = await client.get("/api/v1/projects", params={"limit": 500}, headers=admin.headers)
    row = next(p for p in for_admin.json()["items"] if p["id"] == str(project.id))
    assert row["archived_at"]
    still_open = await client.get(f"/api/v1/projects/{project.id}", headers=admin.headers)
    assert still_open.status_code == 200
    everywhere = await client.get(
        "/api/v1/projects/all/entities", params={"limit": 500}, headers=admin.headers
    )
    assert entity["id"] not in {e["id"] for e in everywhere.json()["items"]}

    back = await client.patch(
        f"/api/v1/projects/{project.id}", json={"archived_at": None}, headers=admin.headers
    )
    assert back.status_code == 200 and back.json()["archived_at"] is None
    reopened = await client.get(f"/api/v1/projects/{project.id}", headers=member.headers)
    assert reopened.status_code == 200


async def test_delete_takes_an_archived_project_by_name_and_releases_its_devices(
    client,
    db,
    bus,  # noqa: F811
):
    admin, project, entity, source, device, external_id = await _setup(client, db)
    when = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    await _feed(db, bus, source["id"], external_id, when, -24.9, 31.5)
    base = f"/api/v1/projects/{project.id}"

    live = await client.delete(base, params={"confirm": project.name}, headers=admin.headers)
    assert live.status_code == 409, live.text
    archived = await client.patch(
        base, json={"archived_at": datetime.now(UTC).isoformat()}, headers=admin.headers
    )
    assert archived.status_code == 200
    wrong = await client.delete(base, params={"confirm": "something else"}, headers=admin.headers)
    assert wrong.status_code == 422, wrong.text
    member = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    not_admin = await client.delete(base, params={"confirm": project.name}, headers=member.headers)
    assert not_admin.status_code == 403

    project_name = project.name
    gone = await client.delete(base, params={"confirm": project_name}, headers=admin.headers)
    assert gone.status_code == 204, gone.text
    project_id = project.id
    db.expunge_all()
    assert await db.scalar(select(Project).where(Project.id == project_id)) is None
    assert await db.scalar(select(Entity).where(Entity.id == uuid.UUID(entity["id"]))) is None
    kept = await db.scalar(select(Device).where(Device.id == uuid.UUID(device["id"])))
    assert kept is not None
    assignments = (
        await db.scalars(
            select(DeviceProjectAssignment).where(DeviceProjectAssignment.device_id == kept.id)
        )
    ).all()
    assert assignments == []
    positions = (await db.scalars(select(Position).where(Position.device_id == kept.id))).all()
    assert positions and all(p.project_id is None for p in positions)
    audit = (await db.scalars(select(AuditLog).where(AuditLog.action == "project.deleted"))).all()
    assert any(a.details.get("name") == project_name for a in audit)
    after = await client.get(base, headers=admin.headers)
    assert after.status_code == 404
    assert (datetime.now(UTC) - when) > timedelta(0)
