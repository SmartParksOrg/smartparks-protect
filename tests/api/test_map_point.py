"""A click on a track point (phase 19): `GET /projects/{id}/positions/at` answers with the
position of an entity or device at one device time and the measurements of that moment, 404
when nothing was recorded then, 403 for a stranger, and the all scope for a server admin."""

from datetime import UTC, datetime, timedelta

import pytest

from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_position_at_a_time_with_its_measurements(client, db, bus):  # noqa: F811
    admin, project, entity, source, device, external_id = await _setup(client, db)
    start = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    for i in range(3):
        await _feed(
            db, bus, source["id"], external_id, start + timedelta(minutes=i), -24.9, 31.5 + i / 100
        )
    at = (start + timedelta(minutes=1)).isoformat()

    by_entity = await client.get(
        f"/api/v1/projects/{project.id}/positions/at",
        params={"entity_id": entity["id"], "time": at},
        headers=admin.headers,
    )
    assert by_entity.status_code == 200, by_entity.text
    body = by_entity.json()
    assert body["position"]["entity_id"] == entity["id"]
    assert body["position"]["device_id"] == device["id"]
    assert body["position"]["geometry"]["coordinates"][0] == pytest.approx(31.51)
    assert body["entity_name"] == "Rhino 14"
    assert body["device_name"] == device["name"]
    assert [m["metric_key"] for m in body["measurements"]] == ["battery_voltage"]
    assert body["measurements"][0]["value"] == pytest.approx(3.8)
    assert body["measurements"][0]["unit"] == "V"

    by_device = await client.get(
        f"/api/v1/projects/{project.id}/positions/at",
        params={"device_id": device["id"], "time": at},
        headers=admin.headers,
    )
    assert by_device.status_code == 200
    assert by_device.json()["position"]["id"] == body["position"]["id"]

    nothing = await client.get(
        f"/api/v1/projects/{project.id}/positions/at",
        params={"entity_id": entity["id"], "time": (start + timedelta(hours=1)).isoformat()},
        headers=admin.headers,
    )
    assert nothing.status_code == 404

    both = await client.get(
        f"/api/v1/projects/{project.id}/positions/at",
        params={"entity_id": entity["id"], "device_id": device["id"], "time": at},
        headers=admin.headers,
    )
    assert both.status_code == 422

    other = await create_project(db)
    stranger = await project_actor(client, db, other, Role.PROJECT_VIEWER)
    refused = await client.get(
        f"/api/v1/projects/{project.id}/positions/at",
        params={"entity_id": entity["id"], "time": at},
        headers=stranger.headers,
    )
    assert refused.status_code == 403

    # the all scope (decision D115) for a server admin
    superuser = await actor(client, db, superuser=True)
    everywhere = await client.get(
        "/api/v1/projects/all/positions/at",
        params={"entity_id": entity["id"], "time": at},
        headers=superuser.headers,
    )
    assert everywhere.status_code == 200
    assert everywhere.json()["position"]["id"] == body["position"]["id"]


async def test_device_state_for_the_last_status(client, db, bus):  # noqa: F811
    """A click on "Last status" (2026-09-13): the newest status with the driver's health lines
    and every raw value, its source event, 404 before any status and from another project."""
    import uuid

    from protect_decoder.pipeline import process_source_event
    from shared.connectivity.base import InboundMessage
    from shared.enums import AcquisitionChannel, IngestionMethod
    from shared.ingest import commit_and_publish, store_inbound
    from shared.models import DataSource

    admin, project, _entity, source, device, external_id = await _setup(client, db)
    url = f"/api/v1/projects/{project.id}/devices/{device['id']}/state"
    assert (await client.get(url, headers=admin.headers)).status_code == 404

    when = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    message = InboundMessage(
        external_id=external_id,
        event_type="uplink",
        payload={
            "time": when.isoformat(),
            "lat": -24.9,
            "lon": 31.5,
            "state": {"firmware_version": "1.2.3", "uptime": 3600.0, "reset_reason": "power"},
        },
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
    )
    stored = await store_inbound(db, row, message)
    await commit_and_publish(db, bus, [stored])
    await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    await db.commit()

    read = await client.get(url, headers=admin.headers)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["device_name"] == device["name"] and body["time"].startswith("2026-04-01T12:00:00")
    assert body["state"]["firmware_version"] == "1.2.3" and body["state"]["reset_reason"] == "power"
    assert body["source_event_id"] == stored.source_event.id
    assert isinstance(body["health"]["fields"], list)

    other = await create_project(db)
    assert (
        await client.get(
            f"/api/v1/projects/{other.id}/devices/{device['id']}/state", headers=admin.headers
        )
    ).status_code == 404
