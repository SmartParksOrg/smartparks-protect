"""The device layer (decision D111): the map's devices endpoint lists every device assigned to
the project today, with a position from its own current state whether or not it tracks an
entity, leaves out a device whose assignment ended, keeps the entity it tracks, and answers
inside the viewport only with positioned devices."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func

from shared.enums import Role
from shared.models import DeviceCurrentState
from tests.api.conftest import create_project, project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_device_layer_lists_assigned_devices(client, db, bus):  # noqa: F811
    admin, project, entity, source, device, external_id = await _setup(client, db)
    start = datetime(2026, 4, 1, tzinfo=UTC)
    for i in range(3):
        await _feed(db, bus, source["id"], external_id, start + timedelta(minutes=i), -24.9, 31.5)
    types = (await client.get("/api/v1/device-types", headers=admin.headers)).json()["items"]
    device_type_id = device["device_type_id"]
    assert any(t["id"] == device_type_id for t in types)

    # a device in the project without an entity, with a position of its own
    loose = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type_id, "name": unique_name("SP-loose")},
            headers=admin.headers,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{loose['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-02-01T00:00:00+00:00"},
        headers=admin.headers,
    )
    db.add(
        DeviceCurrentState(
            device_id=loose["id"],
            last_seen_at=start,
            latest_position_time=start,
            latest_position=func.ST_SetSRID(func.ST_MakePoint(31.6, -24.8), 4326),
        )
    )
    # a device whose assignment to the project ended
    gone = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type_id, "name": unique_name("SP-gone")},
            headers=admin.headers,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{gone['id']}/project-assignments",
        json={
            "project_id": str(project.id),
            "valid_from": "2026-01-01T00:00:00+00:00",
            "valid_to": "2026-03-01T00:00:00+00:00",
        },
        headers=admin.headers,
    )
    # a device in the project without any position yet
    silent = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type_id, "name": unique_name("SP-silent")},
            headers=admin.headers,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{silent['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-02-01T00:00:00+00:00"},
        headers=admin.headers,
    )
    await db.commit()

    response = await client.get(f"/api/v1/projects/{project.id}/map/devices", headers=admin.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {f["properties"]["device_id"]: f for f in body["features"]}
    assert body["total"] == 3 and body["returned"] == 3 and body["use_tiles"] is False
    assert gone["id"] not in by_id

    tracked = by_id[device["id"]]
    assert tracked["properties"]["entity_id"] == entity["id"]
    assert tracked["properties"]["entity_name"] == "Rhino 14"
    assert tracked["properties"]["project_since"] == "2026-01-01T00:00:00+00:00"
    assert tracked["geometry"]["coordinates"] == [pytest.approx(31.5), pytest.approx(-24.9)]
    assert tracked["properties"]["last_seen_at"] is not None

    untracked = by_id[loose["id"]]
    assert untracked["properties"]["entity_id"] is None
    assert untracked["geometry"]["coordinates"] == [pytest.approx(31.6), pytest.approx(-24.8)]

    assert by_id[silent["id"]]["geometry"] is None

    # inside a viewport only positioned devices in it
    inside = (
        await client.get(
            f"/api/v1/projects/{project.id}/map/devices",
            params={"bbox": "31.55,-24.85,31.65,-24.75"},
            headers=admin.headers,
        )
    ).json()
    assert [f["properties"]["device_id"] for f in inside["features"]] == [loose["id"]]
    assert inside["total"] == 3

    # a member of another project may not read it
    other = await create_project(db)
    stranger = await project_actor(client, db, other, Role.PROJECT_VIEWER)
    assert (
        await client.get(f"/api/v1/projects/{project.id}/map/devices", headers=stranger.headers)
    ).status_code == 403


async def test_all_scope_lists_devices_in_no_project_for_server_admins(client, db, bus):  # noqa: F811
    """Decision D120: a device without a project assignment shows in the all scope with its
    position and no project; a project admin cannot use the scope."""
    admin, project, entity, source, device, external_id = await _setup(client, db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    inventory = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device["device_type_id"], "name": unique_name("SP-inv")},
            headers=admin.headers,
        )
    ).json()
    when = datetime(2026, 5, 1, tzinfo=UTC)
    db.add(
        DeviceCurrentState(
            device_id=inventory["id"],
            last_seen_at=when,
            latest_position_time=when,
            latest_position=func.ST_SetSRID(func.ST_MakePoint(31.7, -24.7), 4326),
        )
    )
    await db.commit()
    body = (await client.get("/api/v1/projects/all/map/devices", headers=admin.headers)).json()
    by_id = {f["properties"]["device_id"]: f for f in body["features"]}
    assert inventory["id"] in by_id
    assert by_id[inventory["id"]]["properties"]["project_id"] is None
    assert by_id[inventory["id"]]["geometry"]["coordinates"] == [
        pytest.approx(31.7),
        pytest.approx(-24.7),
    ]
    assert by_id[device["id"]]["properties"]["project_id"] == str(project.id)
    # not in a project's own scope
    own = (
        await client.get(f"/api/v1/projects/{project.id}/map/devices", headers=admin.headers)
    ).json()
    assert inventory["id"] not in {f["properties"]["device_id"] for f in own["features"]}
    assert (
        await client.get("/api/v1/projects/all/map/devices", headers=manager.headers)
    ).status_code == 403
    # the devices list filters them on the server, for server admins only
    listed = (
        await client.get(
            "/api/v1/devices", params={"in_no_project": "true", "limit": 500}, headers=admin.headers
        )
    ).json()["items"]
    names = {d["id"] for d in listed}
    assert inventory["id"] in names and device["id"] not in names
    assert (
        await client.get(
            "/api/v1/devices", params={"in_no_project": "true"}, headers=manager.headers
        )
    ).status_code == 403
    assert entity and source and external_id and bus
