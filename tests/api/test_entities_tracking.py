"""The entities list says what each entity's devices report today (decision D286): every device
assigned now with its health, the worst level, the newest record and the position the current
state holds. Read from the assignments, so a device that never sent a fix still counts; the list
took this from the live map's read before, which leaves out every entity without a position."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.models import DeviceCurrentState, EntityCurrentState
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_entities_list_carries_tracking(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("oc").replace("-", "_"),
                "label": "OpenCollar",
                "driver_key": "opencollar",
            },
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

    async def new_entity(name: str) -> dict:
        response = await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": name},
            headers=h,
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def new_device(name: str, entity: dict) -> dict:
        device = (
            await client.post(
                "/api/v1/devices",
                json={"device_type_id": device_type["id"], "name": name, "status": "active"},
                headers=h,
            )
        ).json()
        joined = await client.post(
            f"/api/v1/devices/{device['id']}/project-assignments",
            json={"project_id": project.id.hex, "valid_from": "2026-06-01T00:00:00+00:00"},
            headers=h,
        )
        assert joined.status_code == 201, joined.text
        assigned = await client.post(
            f"/api/v1/projects/{project.id}/entity-assignments",
            json={
                "device_id": device["id"],
                "entity_id": entity["id"],
                "valid_from": "2026-06-02T00:00:00+00:00",
            },
            headers=h,
        )
        assert assigned.status_code == 201, assigned.text
        return device

    rhino = await new_entity(unique_name("Rhino"))
    monitor = await new_entity(unique_name("Monitor"))
    untracked = await new_entity(unique_name("Untracked"))
    healthy = await new_device(unique_name("A-device"), rhino)
    flat = await new_device(unique_name("B-device"), rhino)
    silent_gps = await new_device(unique_name("Fence"), monitor)

    now = datetime.now(UTC)
    for device, volts, seen in (
        (healthy, 3.7, now - timedelta(hours=3)),
        (flat, 3.2, now - timedelta(minutes=10)),
        (silent_gps, 3.7, now - timedelta(minutes=30)),
    ):
        await db.merge(
            DeviceCurrentState(
                device_id=uuid.UUID(device["id"]),
                last_seen_at=seen,
                latest_state={},
                latest_measurements={"battery_voltage": {"value": volts, "time": seen.isoformat()}},
                battery_voltage=volts,
            )
        )
    # the rhino has a position and an open alert; the fence monitor has none of either
    await db.merge(
        EntityCurrentState(
            entity_id=uuid.UUID(rhino["id"]),
            project_id=project.id,
            last_seen_at=now - timedelta(minutes=10),
            latest_position_time=now - timedelta(hours=3),
            latest_position_kind="device",
            active_alert_count=2,
        )
    )
    await db.commit()

    response = await client.get(f"/api/v1/projects/{project.id}/entities", headers=h)
    assert response.status_code == 200, response.text
    rows = {e["id"]: e["tracking"] for e in response.json()["items"]}

    tracked = rows[rhino["id"]]
    assert [d["name"] for d in tracked["devices"]] == [healthy["name"], flat["name"]]
    assert tracked["level"] == "critical"  # the worst of the two devices
    assert tracked["devices"][1]["health"]["level"] == "critical"
    assert tracked["active_alert_count"] == 2
    assert tracked["position_kind"] == "device"
    assert datetime.fromisoformat(tracked["last_seen_at"]) == now - timedelta(minutes=10)

    # no position at all, and still its device and its last seen
    fence = rows[monitor["id"]]
    assert [d["id"] for d in fence["devices"]] == [silent_gps["id"]]
    assert fence["level"] == "ok"
    assert fence["position_time"] is None
    assert datetime.fromisoformat(fence["last_seen_at"]) == now - timedelta(minutes=30)
    assert fence["active_alert_count"] == 0

    assert rows[untracked["id"]]["devices"] == []
    assert rows[untracked["id"]]["level"] is None
    assert rows[untracked["id"]]["last_seen_at"] is None
