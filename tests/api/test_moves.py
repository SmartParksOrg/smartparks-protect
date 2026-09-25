"""Moves between projects with the history (decisions D292 and D293, ADR 0038): a device from
a moment, with the entity along when its whole history moves and staying otherwise; an entity
whole, with its devices over the spans they tracked it; the preview says the same as the move."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from shared.enums import Role
from shared.models import Entity, Position
from tests.api.conftest import create_project, project_actor
from tests.api.test_attribution_repair import _device_with_early_records, _finish_jobs
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _entity_type(client, h):
    return (
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


async def _in_project_since_first_data(client, db, bus, *, entity: bool = True):
    """A device with three May records, in a project since its first data, tracking a new
    entity from the same moment when asked; the jobs run."""
    admin, project, _type, device = await _device_with_early_records(client, db, bus)
    h = admin.headers
    span = (await client.get(f"/api/v1/devices/{device['id']}/data-span", headers=h)).json()
    first = span["first_data_at"]
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": first},
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    entity_id = None
    if entity:
        entity_type = await _entity_type(client, h)
        tracked = await client.post(
            f"/api/v1/projects/{project.id}/entity-assignments",
            json={
                "device_id": device["id"],
                "valid_from": first,
                "new_entity": {"name": "Rhino 14", "entity_type_id": entity_type["id"]},
            },
            headers=h,
        )
        assert tracked.status_code == 201, tracked.text
        entity_id = tracked.json()["entity_id"]
    await _finish_jobs(client, device["id"], h)
    return admin, project, device, entity_id, first


async def _positions(db, device_id):
    """The device's positions by day with their project and entity; the caller rolled back."""
    rows = (
        await db.scalars(
            select(Position).where(Position.device_id == device_id).order_by(Position.time)
        )
    ).all()
    return [(p.time.day, p.project_id, p.entity_id) for p in rows]


async def test_a_device_moves_with_its_history_and_the_entity_comes_along(client, db, bus):
    admin, old, device, entity_id, _first = await _in_project_since_first_data(client, db, bus)
    h = admin.headers
    new = await create_project(db)
    new_id = new.id
    body = {"device_ids": [device["id"]], "project_id": str(new.id), "start": "first_data"}

    preview = await client.post("/api/v1/devices/move", json={**body, "preview": True}, headers=h)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["preview"] and plan["moved_devices"] == 1 and plan["moved_entities"] == 1
    [outcome] = plan["devices"]
    assert outcome["skipped"] is None and outcome["project_id"] == str(old.id)
    assert (
        outcome["spans"][0]["start"].startswith("2026-05-03") and outcome["spans"][0]["end"] is None
    )
    assert [e["name"] for e in outcome["entities_along"]] == ["Rhino 14"]
    assert outcome["entities_staying"] == []
    # nothing was written
    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    assert [a["project_id"] for a in detail["project_assignments"]] == [str(old.id)]

    moved = await client.post("/api/v1/devices/move", json=body, headers=h)
    assert moved.status_code == 200, moved.text
    assert moved.json()["moved_devices"] == 1 and moved.json()["attribution_jobs"] == 1
    jobs = await _finish_jobs(client, device["id"], h)
    assert jobs[0]["status"] == "complete" and jobs[0]["reason"] == "device.moved"

    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    assert [(a["project_id"], a["valid_to"]) for a in detail["project_assignments"]] == [
        (str(new.id), None)
    ]
    assert detail["project_assignments"][0]["valid_from"].startswith("2026-05-03")
    assert [(a["entity_id"], a["valid_to"]) for a in detail["entity_assignments"]] == [
        (entity_id, None)
    ]
    await db.rollback()
    entity = await db.get(Entity, entity_id)
    assert entity is not None and entity.project_id == new_id
    assert await _positions(db, uuid.UUID(device["id"])) == [
        (3, new_id, entity.id),
        (4, new_id, entity.id),
        (5, new_id, entity.id),
    ]
    # the old project lost the device: its admin no longer sees it, the new one does
    old_admin = await project_actor(client, db, old, Role.PROJECT_ADMIN)
    assert (
        await client.get(f"/api/v1/devices/{device['id']}", headers=old_admin.headers)
    ).status_code == 404
    new_admin = await project_actor(client, db, new, Role.PROJECT_ADMIN)
    assert (
        await client.get(f"/api/v1/devices/{device['id']}", headers=new_admin.headers)
    ).status_code == 200
    listed = (
        await client.get(f"/api/v1/projects/{new.id}/entities?limit=10", headers=new_admin.headers)
    ).json()["items"]
    assert [e["name"] for e in listed] == ["Rhino 14"]


async def test_a_device_moved_from_a_date_leaves_the_entity_and_the_earlier_part(client, db, bus):
    admin, old, device, entity_id, _first = await _in_project_since_first_data(client, db, bus)
    h = admin.headers
    new = await create_project(db)
    old_id, new_id = old.id, new.id
    moment = "2026-05-05T00:00:00+00:00"
    moved = await client.post(
        "/api/v1/devices/move",
        json={"device_ids": [device["id"]], "project_id": str(new.id), "start": moment},
        headers=h,
    )
    assert moved.status_code == 200, moved.text
    [outcome] = moved.json()["devices"]
    assert outcome["entities_along"] == []
    [staying] = outcome["entities_staying"]
    assert staying["name"] == "Rhino 14" and "tracked it before" in staying["reason"]
    await _finish_jobs(client, device["id"], h)

    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    projects = sorted(detail["project_assignments"], key=lambda a: a["valid_from"])
    assert [(a["project_id"], (a["valid_to"] or "")[:10]) for a in projects] == [
        (str(old.id), "2026-05-05"),
        (str(new.id), ""),
    ]
    assert detail["entity_assignments"][0]["valid_to"].startswith("2026-05-05")
    await db.rollback()
    entity = await db.get(Entity, entity_id)
    assert entity is not None and entity.project_id == old_id
    assert await _positions(db, uuid.UUID(device["id"])) == [
        (3, old_id, entity.id),
        (4, old_id, entity.id),
        (5, new_id, None),
    ]


async def test_an_entity_moves_whole_and_a_reused_device_keeps_the_rest_behind(client, db, bus):
    admin, old, device, first_entity, _first = await _in_project_since_first_data(client, db, bus)
    h = admin.headers
    # from the 5th the device tracks another animal of the old project
    entity_type = await _entity_type(client, h)
    ended = await client.patch(
        f"/api/v1/projects/{old.id}/entity-assignments/"
        + (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()[
            "entity_assignments"
        ][0]["id"],
        json={"valid_to": "2026-05-05T00:00:00+00:00"},
        headers=h,
    )
    assert ended.status_code == 200, ended.text
    second = await client.post(
        f"/api/v1/projects/{old.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "valid_from": "2026-05-05T00:00:00+00:00",
            "new_entity": {"name": "Rhino 15", "entity_type_id": entity_type["id"]},
        },
        headers=h,
    )
    assert second.status_code == 201, second.text
    second_entity = second.json()["entity_id"]
    await _finish_jobs(client, device["id"], h)

    new = await create_project(db)
    old_id, new_id = old.id, new.id
    preview = await client.post(
        f"/api/v1/projects/{old.id}/entities/move",
        json={"entity_ids": [first_entity], "project_id": str(new.id), "preview": True},
        headers=h,
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["moved_entities"] == 1 and plan["moved_devices"] == 1
    [outcome] = plan["devices"]
    assert outcome["spans"][0]["start"].startswith("2026-05-03")
    assert outcome["spans"][0]["end"].startswith("2026-05-05")

    moved = await client.post(
        f"/api/v1/projects/{old.id}/entities/move",
        json={"entity_ids": [first_entity], "project_id": str(new.id)},
        headers=h,
    )
    assert moved.status_code == 200, moved.text
    await _finish_jobs(client, device["id"], h)
    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    projects = sorted(detail["project_assignments"], key=lambda a: a["valid_from"])
    assert [
        (a["project_id"], a["valid_from"][:10], (a["valid_to"] or "")[:10]) for a in projects
    ] == [
        (str(new.id), "2026-05-03", "2026-05-05"),
        (str(old.id), "2026-05-05", ""),
    ]
    await db.rollback()
    moved_entity = await db.get(Entity, first_entity)
    kept_entity = await db.get(Entity, second_entity)
    assert moved_entity is not None and moved_entity.project_id == new_id
    assert kept_entity is not None and kept_entity.project_id == old_id
    assert await _positions(db, uuid.UUID(device["id"])) == [
        (3, new_id, moved_entity.id),
        (4, new_id, moved_entity.id),
        (5, old_id, kept_entity.id),
    ]


async def test_moves_need_admins_of_every_project_and_skip_what_cannot_move(client, db, bus):
    admin, old, device, _entity, _first = await _in_project_since_first_data(client, db, bus)
    h = admin.headers
    new = await create_project(db)
    body = {"device_ids": [device["id"]], "project_id": str(new.id), "start": "first_data"}
    old_admin = await project_actor(client, db, old, Role.PROJECT_ADMIN)
    denied = await client.post("/api/v1/devices/move", json=body, headers=old_admin.headers)
    assert denied.status_code == 403
    # a name the target has blocks the entity, and with it the device
    entity_type = await _entity_type(client, h)
    taken = await client.post(
        f"/api/v1/projects/{new.id}/entities",
        json={"name": "Rhino 14", "entity_type_id": entity_type["id"]},
        headers=h,
    )
    assert taken.status_code == 201, taken.text
    blocked = (await client.post("/api/v1/devices/move", json=body, headers=h)).json()
    assert blocked["moved_devices"] == 0
    assert "Rhino 14" in blocked["devices"][0]["skipped"]
    # already there: skipped
    same = (
        await client.post(
            "/api/v1/devices/move",
            json={**body, "project_id": str(old.id)},
            headers=h,
        )
    ).json()
    assert same["devices"][0]["skipped"] == "already in this project"
    # the entity move refuses the same project and skips a name the target has
    refused = await client.post(
        f"/api/v1/projects/{old.id}/entities/move",
        json={"entity_ids": [_entity], "project_id": str(old.id)},
        headers=h,
    )
    assert refused.status_code == 409
    skipped = (
        await client.post(
            f"/api/v1/projects/{old.id}/entities/move",
            json={"entity_ids": [_entity], "project_id": str(new.id)},
            headers=h,
        )
    ).json()
    assert skipped["moved_entities"] == 0
    assert "of that name" in skipped["entities"][0]["reason"]
