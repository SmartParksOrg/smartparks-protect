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
    assert body["returned"] == 5 and body["capped"] is False
    assert body["devices_scanned"] == 1 and body["devices_total"] == 1
    assert body["features"][0]["geometry"]["type"] == "Point"

    by_entity = await client.get(
        base, params={"hours": 48, "entity_id": entity["id"]}, headers=admin.headers
    )
    assert by_entity.json()["returned"] == 5
    by_device = await client.get(
        base, params={"hours": 48, "device_id": device["id"]}, headers=admin.headers
    )
    assert by_device.json()["returned"] == 5
    nobody = await client.get(
        base,
        params={"hours": 48, "entity_id": "00000000-0000-0000-0000-000000000001"},
        headers=admin.headers,
    )
    assert nobody.json()["returned"] == 0 and nobody.json()["devices_total"] == 0

    windowed = await client.get(base, params={"hours": 13}, headers=admin.headers)
    assert windowed.json()["returned"] == 3  # now, 6 h and 12 h ago

    viewed = await client.get(
        base, params={"hours": 48, "bbox": "31.45,-25,31.65,-24.8"}, headers=admin.headers
    )
    assert viewed.json()["returned"] == 2  # 31.5 and 31.6

    capped = await client.get(base, params={"hours": 48, "limit": 2}, headers=admin.headers)
    assert capped.json()["returned"] == 2 and capped.json()["capped"] is True

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
    assert everywhere.status_code == 200 and everywhere.json()["returned"] == 5


async def test_heat_points_since_assignment(client, db, bus):  # noqa: F811
    """`since_assigned`: an entity's window starts when the device tracking it today was
    assigned to it, a device's when it joined the project, and `hours` applies to an owner
    without such a moment, as the track length "since assignment" does."""
    from sqlalchemy import text

    admin, project, entity, source, device, external_id = await _setup(client, db)
    now = datetime.now(tz=UTC)
    for i in range(5):
        await _feed(
            db, bus, source["id"], external_id, now - timedelta(hours=i * 6), -24.9, 31.5 + i / 10
        )
    # the assignments were made for 2026-01-01; move their starts to inside the record
    await db.execute(
        text(
            "UPDATE device_entity_assignments SET validity = tstzrange(:start, upper(validity))"
            " WHERE device_id = :device_id"
        ),
        {"start": now - timedelta(hours=15), "device_id": device["id"]},
    )
    await db.execute(
        text(
            "UPDATE device_project_assignments SET validity = tstzrange(:start, upper(validity))"
            " WHERE device_id = :device_id"
        ),
        {"start": now - timedelta(hours=9), "device_id": device["id"]},
    )
    await db.commit()
    base = f"/api/v1/projects/{project.id}/map/heat"

    by_hours = await client.get(
        base, params={"hours": 48, "entity_id": entity["id"]}, headers=admin.headers
    )
    assert by_hours.json()["returned"] == 5 and by_hours.json()["since_assigned"] is False

    entity_window = await client.get(
        base,
        params={"hours": 48, "entity_id": entity["id"], "since_assigned": "true"},
        headers=admin.headers,
    )
    assert entity_window.status_code == 200, entity_window.text
    body = entity_window.json()
    assert body["returned"] == 3 and body["since_assigned"] is True  # now, 6 h and 12 h ago
    assert body["devices_total"] == 1

    device_window = await client.get(
        base,
        params={"hours": 48, "device_id": device["id"], "since_assigned": "true"},
        headers=admin.headers,
    )
    assert device_window.json()["returned"] == 2  # now and 6 h ago

    # both at once: each owner keeps its own start, and a position counts once
    both = await client.get(
        base,
        params={
            "hours": 48,
            "entity_id": entity["id"],
            "device_id": device["id"],
            "since_assigned": "true",
        },
        headers=admin.headers,
    )
    assert both.json()["returned"] == 3

    # the assignment's start wins over a shorter `hours`, and `hours` holds for an entity
    # without a device today (its device left it three hours ago)
    shorter = await client.get(
        base,
        params={"hours": 7, "entity_id": entity["id"], "since_assigned": "true"},
        headers=admin.headers,
    )
    assert shorter.json()["returned"] == 3
    await db.execute(
        text(
            "UPDATE device_entity_assignments SET validity = tstzrange(lower(validity), :end)"
            " WHERE device_id = :device_id"
        ),
        {"end": now - timedelta(hours=3), "device_id": device["id"]},
    )
    await db.commit()
    untracked = await client.get(
        base,
        params={"hours": 7, "entity_id": entity["id"], "since_assigned": "true"},
        headers=admin.headers,
    )
    assert untracked.json()["returned"] == 2  # now and 6 h ago: the custom length
    # beside a device with a start of its own, the entity still gets the custom length
    beside = await client.get(
        base,
        params={
            "hours": 7,
            "entity_id": entity["id"],
            "device_id": device["id"],
            "since_assigned": "true",
        },
        headers=admin.headers,
    )
    assert beside.json()["returned"] == 2
