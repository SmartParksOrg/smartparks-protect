"""The speed and course a fix carries (phase 37): the decoder writes them as `speed` and
`heading` measurements beside the position, the map's entity and device features carry them
for the newest fix only, and a fix without a speed clears them again."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _features(client, project, admin):
    current = await client.get(f"/api/v1/projects/{project.id}/map/current", headers=admin.headers)
    devices = await client.get(f"/api/v1/projects/{project.id}/map/devices", headers=admin.headers)
    assert current.status_code == 200 and devices.status_code == 200, current.text
    return current.json()["features"][0]["properties"], devices.json()["features"][0]["properties"]


async def test_speed_and_course_ride_with_the_newest_fix(client, db, bus):  # noqa: F811
    admin, project, _entity, source, device, external_id = await _setup(client, db)
    start = datetime(2026, 9, 25, 15, 0, tzinfo=UTC)
    await _feed(db, bus, source["id"], external_id, start, 51.54, 3.78, speed=12.0, heading=52.5)

    entity_props, device_props = await _features(client, project, admin)
    for props in (entity_props, device_props):
        assert props["speed"] == pytest.approx(12.0) and props["heading"] == pytest.approx(52.5)

    summary = await client.get(
        f"/api/v1/projects/{project.id}/measurements/summary",
        params={"device_id": device["id"]},
        headers=admin.headers,
    )
    assert summary.status_code == 200, summary.text
    keys = {m["metric_key"]: m for m in summary.json()}
    assert keys["speed"]["value"] == pytest.approx(12.0) and keys["speed"]["unit"] == "m/s"
    assert keys["heading"]["value"] == pytest.approx(52.5)

    # a standstill keeps its speed and drops the course; a fix without a speed shows neither
    await _feed(
        db,
        bus,
        source["id"],
        external_id,
        start + timedelta(minutes=1),
        51.54,
        3.78,
        speed=0.0,
        heading=52.5,
    )
    entity_props, _ = await _features(client, project, admin)
    assert entity_props["speed"] == 0.0 and entity_props["heading"] is None
    await _feed(db, bus, source["id"], external_id, start + timedelta(minutes=2), 51.54, 3.79)
    entity_props, device_props = await _features(client, project, admin)
    assert entity_props["speed"] is None and device_props["speed"] is None
    assert entity_props["heading"] is None
