"""The heatmap's points (decision D138): `GET /projects/{id}/map/heat` answers the newest
positions in the window and viewport for the given entities or devices, bounded, 403 for a
stranger, and in the all scope for a server admin."""

from datetime import UTC, datetime, timedelta

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_heat_points_by_entity_device_window_and_view(client, db, bus):  # noqa: F811
    admin, project, entity, source, device, external_id = await _setup(client, db)
    now = datetime.now(tz=UTC)
    for i in range(5):
        await _feed(
            db, bus, source["id"], external_id, now - timedelta(hours=i * 6), -24.9, 31.5 + i / 10
        )
    base = f"/api/v1/projects/{project.id}/map/heat"

    everything = await client.get(base, params={"hours": 48}, headers=admin.headers)
    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert body["total"] == 5 and body["returned"] == 5
    assert body["features"][0]["geometry"]["type"] == "Point"

    by_entity = await client.get(
        base, params={"hours": 48, "entity_id": entity["id"]}, headers=admin.headers
    )
    assert by_entity.json()["total"] == 5
    by_device = await client.get(
        base, params={"hours": 48, "device_id": device["id"]}, headers=admin.headers
    )
    assert by_device.json()["total"] == 5
    nobody = await client.get(
        base,
        params={"hours": 48, "entity_id": "00000000-0000-0000-0000-000000000001"},
        headers=admin.headers,
    )
    assert nobody.json()["total"] == 0

    windowed = await client.get(base, params={"hours": 13}, headers=admin.headers)
    assert windowed.json()["total"] == 3  # now, 6 h and 12 h ago

    viewed = await client.get(
        base, params={"hours": 48, "bbox": "31.45,-25,31.65,-24.8"}, headers=admin.headers
    )
    assert viewed.json()["total"] == 2  # 31.5 and 31.6

    capped = await client.get(base, params={"hours": 48, "limit": 2}, headers=admin.headers)
    assert capped.json()["total"] == 5 and capped.json()["returned"] == 2

    too_many = await client.get(
        base,
        params={"hours": 48, "entity_id": [entity["id"]] * 501},
        headers=admin.headers,
    )
    assert too_many.status_code == 422

    other = await create_project(db)
    stranger = await project_actor(client, db, other, Role.PROJECT_VIEWER)
    assert (await client.get(base, headers=stranger.headers)).status_code == 403

    superuser = await actor(client, db, superuser=True)
    everywhere = await client.get(
        "/api/v1/projects/all/map/heat",
        params={"hours": 48, "entity_id": entity["id"]},
        headers=superuser.headers,
    )
    assert everywhere.status_code == 200 and everywhere.json()["total"] == 5
