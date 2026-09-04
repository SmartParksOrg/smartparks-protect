"""Traffic, traces, health, current state, tiles and tracks, fed through the real pipeline."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from protect_decoder.pipeline import process_source_event
from shared.bus import RedisStreamsBus
from shared.connectivity.base import GatewayReceptionData, InboundMessage
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _setup(client, db):
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
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=h,
        )
    ).json()
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("CS"),
                "adapter_key": "chirpstack",
                "config": {"mqtt_host": "x"},
            },
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
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        headers=h,
    )
    return admin, project, entity, source, device, external_id


async def _feed(
    db, bus, source_id, external_id, when: datetime, lat: float, lon: float, rssi=-60.0
):
    from shared.models import DataSource

    source = await db.get(DataSource, uuid.UUID(source_id))
    message = InboundMessage(
        external_id=external_id,
        event_type="uplink",
        payload={
            "time": when.isoformat(),
            "lat": lat,
            "lon": lon,
            "measurements": {"battery_voltage": 3.8},
        },
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        provider_metadata={
            "f_port": 13,
            "f_cnt": 7,
            "spreading_factor": 9,
            "gateway_count": 1,
            "best_rssi": rssi,
            "best_snr": 7.5,
        },
        network_received_at=when + timedelta(seconds=2),
        gateway_receptions=[
            GatewayReceptionData(
                gateway_id="0016c001f153a14c", rssi=rssi, snr=7.5, frequency_hz=867100000
            )
        ],
    )
    stored = await store_inbound(db, source, message)
    await commit_and_publish(db, bus, [stored])
    await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    await db.commit()
    return stored


async def test_traffic_traces_and_health(client, db, bus):
    admin, project, _entity, source, device, external_id = await _setup(client, db)
    now = datetime.now(UTC).replace(microsecond=0)
    await _feed(db, bus, source["id"], external_id, now - timedelta(minutes=10), -24.9, 31.5)
    await _feed(db, bus, source["id"], external_id, now - timedelta(minutes=5), -24.91, 31.51)

    traffic = await client.get(f"/api/v1/projects/{project.id}/traffic", headers=admin.headers)
    assert traffic.status_code == 200, traffic.text
    rows = [r for r in traffic.json() if r["device_id"] == device["id"]]
    assert len(rows) == 2
    assert (
        rows[0]["f_port"] == 13
        and rows[0]["best_rssi"] == -60.0
        and rows[0]["processing_status"] == "processed"
    )
    assert rows[0]["receptions"][0]["gateway_id"] == "0016c001f153a14c"
    assert rows[0]["payload"] is None
    with_payload = (
        await client.get(
            f"/api/v1/projects/{project.id}/traffic",
            params={"include_payload": "true", "limit": 1},
            headers=admin.headers,
        )
    ).json()
    assert with_payload[0]["payload"]["lat"] == -24.91

    traces = await client.get(
        f"/api/v1/projects/{project.id}/traces",
        params={"device_id": device["id"]},
        headers=admin.headers,
    )
    assert traces.status_code == 200 and len(traces.json()) == 2
    assert all(t["status"] == "success" for t in traces.json())
    by_status = (
        await client.get(
            f"/api/v1/projects/{project.id}/traces",
            params={"status": "failed"},
            headers=admin.headers,
        )
    ).json()
    assert by_status == []

    health = await client.get("/api/v1/system/health", headers=admin.headers)
    assert health.status_code == 200
    body = health.json()
    assert {w["name"] for w in body["workers"]} == {
        "ingest",
        "decoder",
        "export",
        "rules",
        "automation",
        "integration",
    }
    assert any(s["id"] == source["id"] and s["events_last_hour"] == 2 for s in body["data_sources"])


def _tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    import math

    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


async def test_current_state_tiles_and_track(client, db, bus):
    admin, project, entity, source, device, external_id = await _setup(client, db)
    start = datetime(2026, 4, 1, tzinfo=UTC)
    for i in range(30):
        await _feed(
            db,
            bus,
            source["id"],
            external_id,
            start + timedelta(minutes=i),
            -24.9 + i * 0.001,
            31.5 + i * 0.001,
        )

    current = await client.get(f"/api/v1/projects/{project.id}/map/current", headers=admin.headers)
    assert current.status_code == 200, current.text
    body = current.json()
    assert body["total"] == 1 and body["returned"] == 1 and body["use_tiles"] is False
    feature = body["features"][0]
    assert (
        feature["properties"]["name"] == "Rhino 14"
        and feature["properties"]["icon_key"] == "wildlife.rhino"
    )
    assert feature["geometry"]["coordinates"] == [pytest.approx(31.529), pytest.approx(-24.871)]

    outside = (
        await client.get(
            f"/api/v1/projects/{project.id}/map/current",
            params={"bbox": "0,0,1,1"},
            headers=admin.headers,
        )
    ).json()
    assert outside["returned"] == 0 and outside["total"] == 1
    assert (
        await client.get(
            f"/api/v1/projects/{project.id}/map/current",
            params={"bbox": "bad"},
            headers=admin.headers,
        )
    ).status_code == 422

    x, y = _tile(31.529, -24.871, 5)
    tile = await client.get(
        f"/api/v1/projects/{project.id}/map/tiles/5/{x}/{y}.mvt", headers=admin.headers
    )
    assert (
        tile.status_code == 200
        and tile.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    )
    assert len(tile.content) > 20 and b"entities" in tile.content
    empty = await client.get(
        f"/api/v1/projects/{project.id}/map/tiles/5/0/0.mvt", headers=admin.headers
    )
    assert empty.status_code == 200 and len(empty.content) == 0

    track = await client.get(
        f"/api/v1/projects/{project.id}/tracks",
        params={
            "entity_id": entity["id"],
            "from": start.isoformat(),
            "to": (start + timedelta(hours=1)).isoformat(),
            "max_points": 10,
        },
        headers=admin.headers,
    )
    assert track.status_code == 200, track.text
    body = track.json()
    assert body["total_points"] == 30 and body["step"] == 3
    assert body["returned_points"] == len(body["times"]) == len(body["geometry"]["coordinates"])
    assert 10 <= body["returned_points"] <= 11
    assert body["geometry"]["type"] == "LineString"
    assert body["times"][0].startswith("2026-04-01T00:00:00") and body["times"][-1].startswith(
        "2026-04-01T00:29:00"
    )

    full = (
        await client.get(
            f"/api/v1/projects/{project.id}/tracks",
            params={
                "device_id": device["id"],
                "from": start.isoformat(),
                "to": (start + timedelta(hours=1)).isoformat(),
            },
            headers=admin.headers,
        )
    ).json()
    assert full["returned_points"] == 30 and full["step"] == 1
    assert (
        await client.get(f"/api/v1/projects/{project.id}/tracks", headers=admin.headers)
    ).status_code == 422
