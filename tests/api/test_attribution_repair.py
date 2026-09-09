"""Assignment dates from the data and the attribution repair (decision D103): records that
arrived before a device was assigned become visible when the assignment start moves back."""

import uuid

import pytest
import pytest_asyncio

from shared.bus import Topic
from tests.api.conftest import actor, create_project
from tests.api.test_ingest_and_attention import _decode_pending
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _device_with_early_records(client, db, bus):
    """A device whose records (May) predate any assignment; decoded like the worker does."""
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
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
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("Webhook"), "adapter_key": "generic_http"},
            headers=h,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("dev"),
                "status": "active",
            },
            headers=h,
        )
    ).json()
    external_id = uuid.uuid4().hex[:16].upper()
    await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": external_id},
        headers=h,
    )
    group, handler, _walk = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    for day in (3, 4, 5):
        body = {
            "device_id": external_id,
            "time": f"2026-05-0{day}T10:00:00+00:00",
            "lat": -24.9,
            "lon": 31.5,
            "measurements": {"battery_voltage": 3.9},
        }
        accepted = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
        assert accepted.status_code == 202, accepted.text
        await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    await db.rollback()
    return admin, project, device_type, device


async def test_records_before_the_assignment_are_repaired_by_moving_the_start(client, db, bus):
    admin, project, _type, device = await _device_with_early_records(client, db, bus)
    h = admin.headers
    span = (await client.get(f"/api/v1/devices/{device['id']}/data-span", headers=h)).json()
    assert span["first_record_at"].startswith("2026-05-03") and span["last_record_at"].startswith(
        "2026-05-05"
    )
    assert span["first_data_at"].startswith("2026-05-03")
    assert span["earliest_project_from"] is None and span["before_project"] == {
        "positions": 0,
        "measurements": 0,
    }

    # assigned from June: the May records have no project and the project sees nothing
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    span = (await client.get(f"/api/v1/devices/{device['id']}/data-span", headers=h)).json()
    assert span["earliest_project_from"].startswith("2026-06-01")
    assert span["before_project"] == {"positions": 3, "measurements": 3}
    window = {"from": "2026-05-01T00:00:00+00:00", "to": "2026-05-31T00:00:00+00:00"}
    listed = await client.get(f"/api/v1/projects/{project.id}/positions", params=window, headers=h)
    assert listed.status_code == 200 and listed.json() == []

    # the repair: move the start back to the first data
    extended = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments/{assigned.json()['id']}/extend-start",
        json={"valid_from": span["first_data_at"]},
        headers=h,
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["valid_from"].startswith("2026-05-03")
    assert extended.json()["reattributed"] == {"positions": 3, "measurements": 3}
    listed = (
        await client.get(f"/api/v1/projects/{project.id}/positions", params=window, headers=h)
    ).json()
    assert len(listed) == 3
    span = (await client.get(f"/api/v1/devices/{device['id']}/data-span", headers=h)).json()
    assert span["before_project"] == {"positions": 0, "measurements": 0}

    # moving it forward is not this endpoint's job
    refused = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments/{assigned.json()['id']}/extend-start",
        json={"valid_from": "2026-07-01T00:00:00+00:00"},
        headers=h,
    )
    assert refused.status_code == 422

    # the entity assignment: refused while the device is not in the project at that time,
    # then repaired the same way
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
    entity_assignment = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-05-05T00:00:00+00:00",
        },
        headers=h,
    )
    assert entity_assignment.status_code == 201, entity_assignment.text
    # creating the assignment attributes the record already inside its range (May 5)
    listed = (
        await client.get(f"/api/v1/projects/{project.id}/positions", params=window, headers=h)
    ).json()
    assert sorted((p["time"][:10], p["entity_id"]) for p in listed) == [
        ("2026-05-03", None),
        ("2026-05-04", None),
        ("2026-05-05", entity["id"]),
    ]
    assignment_id = entity_assignment.json()["id"]
    too_early = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments/{assignment_id}/extend-start",
        json={"valid_from": "2026-04-01T00:00:00+00:00"},
        headers=h,
    )
    assert too_early.status_code == 409
    extended = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments/{assignment_id}/extend-start",
        json={"valid_from": span["first_data_at"]},
        headers=h,
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["reattributed"] == {"positions": 2, "measurements": 2}
    listed = (
        await client.get(f"/api/v1/projects/{project.id}/positions", params=window, headers=h)
    ).json()
    assert len(listed) == 3 and {p["entity_id"] for p in listed} == {entity["id"]}
    span = (await client.get(f"/api/v1/devices/{device['id']}/data-span", headers=h)).json()
    assert span["before_entity"] == {"positions": 0, "measurements": 0}
    # the entity had no current state before the repair (no record arrived while assigned);
    # the repair gives it one, so it is on the map with last seen at once
    current = (await client.get(f"/api/v1/projects/{project.id}/map/current", headers=h)).json()
    feature = next(f for f in current["features"] if f["properties"]["entity_id"] == entity["id"])
    assert feature["properties"]["last_seen_at"].startswith("2026-05-05")
    assert feature["properties"]["position_time"].startswith("2026-05-05")
    assert feature["properties"]["device_id"] == device["id"]
    audit = (await client.get("/api/v1/admin/audit?limit=30", headers=h)).json()
    assert {e["action"] for e in audit} >= {
        "project_assignment.start_moved",
        "entity_assignment.start_moved",
    }


async def test_records_inside_an_assignment_without_an_entity_are_repaired(client, db, bus):
    """The gap seen on the dev server on 2026-09-09: records decoded before the entity
    assignment existed, under the code of that day, carry no entity although they fall inside
    the assignment. The reattribute action rewrites them from the assignments as they stand."""
    from sqlalchemy import select, update

    from shared.models import Measurement, Position

    admin, project, _device_type, device = await _device_with_early_records(client, db, bus)
    h = admin.headers
    # the id is captured before the commits below expire the instance (async SQLAlchemy)
    project_id = project.id
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.rhino",
            },
            headers=h,
        )
    ).json()
    entity = (
        await client.post(
            f"/api/v1/projects/{project_id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Cow 2081"},
            headers=h,
        )
    ).json()
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project_id), "valid_from": "2026-05-01T00:00:00+00:00"},
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    tracked = await client.post(
        f"/api/v1/projects/{project_id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-05-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert tracked.status_code == 201, tracked.text
    # the gap: the rows lose their entity as if decoded before the assignment existed
    device_id = uuid.UUID(device["id"])
    for model in (Position, Measurement):
        await db.execute(update(model).where(model.device_id == device_id).values(entity_id=None))
    await db.commit()
    without = await db.scalar(
        select(Position).where(Position.device_id == device_id, Position.entity_id.is_(None))
    )
    assert without is not None
    repaired = await client.post(f"/api/v1/devices/{device['id']}/reattribute", json={}, headers=h)
    assert repaired.status_code == 200, repaired.text
    body = repaired.json()
    assert body["reattributed"]["positions"] == 3 and body["reattributed"]["measurements"] == 3
    assert body["valid_from"].startswith("2026-05-03T10:00:00")
    db.expire_all()
    left = (
        await db.scalars(
            select(Position).where(Position.device_id == device_id, Position.entity_id.is_(None))
        )
    ).all()
    assert left == []
    # a member who is not a project admin is refused
    from shared.enums import Role
    from tests.api.conftest import project_actor

    await db.refresh(project)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/devices/{device['id']}/reattribute", json={}, headers=viewer.headers
    )
    assert refused.status_code == 403
