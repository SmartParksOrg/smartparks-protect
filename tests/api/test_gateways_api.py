"""Gateways per project, detail, connectivity analysis, the server registry, the sync action
and polling cursors."""

import uuid

import pytest

from shared.connectivity.base import GatewayReceptionData, GatewayUpdate, InboundMessage
from shared.connectivity.registry import ADAPTERS
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource
from tests.api.test_network_and_map import _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _uplink(db, bus, source, external_id, receptions, when):  # noqa: F811
    message = InboundMessage(
        external_id=external_id,
        event_type="uplink",
        payload={"time": when, "lat": -24.9, "lon": 31.5},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        gateway_receptions=[GatewayReceptionData(gateway_id=g, rssi=r, snr=s) for g, r, s in receptions],
    )
    stored = await store_inbound(db, source, message)
    await commit_and_publish(db, bus, [stored])


async def test_gateways_connectivity_and_admin(client, db, bus, monkeypatch):  # noqa: F811
    admin, project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    external_id = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()[
        "external_identities"
    ][0]["external_id"]
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    for i, receptions in enumerate(
        [
            [("gw-a", -100, 8.0), ("gw-b", -115, 1.0)],
            [("gw-a", -102, 7.0)],
            [("gw-a", -98, 9.0), ("gw-b", -118, -1.0)],
        ]
    ):
        await _uplink(db, bus, row, external_id, receptions, (now - timedelta(minutes=i)).isoformat())

    base = f"/api/v1/projects/{project.id}"
    gateways = (await client.get(f"{base}/gateways", headers=h)).json()
    assert [g["external_id"] for g in gateways] == ["gw-a", "gw-b"]
    best = gateways[0]
    assert best["receptions"] == 3 and best["devices"] == 1 and best["status"] == "online"
    assert best["display_name"] == "gw-a" and best["mean_rssi"] == -100.0
    assert best["data_source_name"] == source["name"]
    assert (await client.get(f"{base}/gateways", params={"hours": 0}, headers=h)).status_code == 422

    detail = (await client.get(f"{base}/gateways/{best['id']}", headers=h)).json()
    assert detail["gateway"]["id"] == best["id"]
    assert detail["devices"][0]["device_name"] == device["name"]
    assert detail["devices"][0]["receptions"] == 3

    connectivity = (await client.get(f"{base}/connectivity", headers=h)).json()
    assert len(connectivity) == 1
    item = connectivity[0]
    assert item["device_id"] == device["id"] and item["gateway_count"] == 2
    assert item["uplinks"] == 3 and item["receptions"] == 5
    assert item["best_gateway_id"] == best["id"] and item["best_gateway_share"] == 1.0
    assert item["gateways"][0]["external_id"] == "gw-a" and item["gateways"][1]["uplinks"] == 2

    # another project sees nothing
    from tests.api.conftest import create_project

    other = await create_project(db)
    assert (await client.get(f"/api/v1/projects/{other.id}/gateways", headers=h)).json() == []
    assert (await client.get(f"/api/v1/projects/{other.id}/connectivity", headers=h)).json() == []

    # the server registry and overrides
    registry = (await client.get("/api/v1/admin/gateways", params={"data_source_id": source["id"]}, headers=h)).json()
    assert {g["external_id"] for g in registry["items"]} == {"gw-a", "gw-b"}
    patched = await client.patch(
        f"/api/v1/admin/gateways/{best['id']}",
        json={"name_override": "North ridge", "latitude": -24.95, "longitude": 31.55},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "North ridge"
    assert patched.json()["geometry"]["coordinates"] == [31.55, -24.95]
    half = await client.patch(f"/api/v1/admin/gateways/{best['id']}", json={"latitude": 1}, headers=h)
    assert half.status_code == 422

    # sync against the platform through the adapter's management connector
    class FakeManagement:
        async def list_gateway_updates(self):
            return [
                GatewayUpdate(gateway_id="gw-b", name="South mast", status="offline", latitude=-24.7, longitude=31.3),
                GatewayUpdate(gateway_id="gw-c", name="Spare", status="unknown"),
            ]

    adapter = ADAPTERS[row.adapter_key]
    monkeypatch.setattr(type(adapter), "management_connector", lambda self, ctx: FakeManagement(), raising=False)
    synced = await client.post(f"/api/v1/data-sources/{source['id']}/sync-gateways", headers=h)
    assert synced.status_code == 200, synced.text
    assert synced.json()["synced"] == 2
    registry = (await client.get("/api/v1/admin/gateways", params={"data_source_id": source["id"]}, headers=h)).json()
    by_id = {g["external_id"]: g for g in registry["items"]}
    assert by_id["gw-b"]["name"] == "South mast" and by_id["gw-b"]["status"] == "offline"
    assert by_id["gw-c"]["status"] == "unknown" and by_id["gw-c"]["geometry"] is None

    generic = await client.post(
        "/api/v1/data-sources",
        json={"name": f"HTTP-{uuid.uuid4().hex[:6]}", "adapter_key": "generic_http"},
        headers=h,
    )
    assert (
        await client.post(f"/api/v1/data-sources/{generic.json()['id']}/sync-gateways", headers=h)
    ).status_code == 422

    # viewers cannot reach the server registry
    from shared.enums import Role
    from tests.api.conftest import project_actor

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(f"{base}/gateways", headers=viewer.headers)).status_code == 200
    assert (await client.get("/api/v1/admin/gateways", headers=viewer.headers)).status_code == 403


async def test_polling_cursor_reset(client, db):
    from tests.api.conftest import actor

    admin = await actor(client, db, superuser=True)
    h = admin.headers
    polling_key = next(k for k, a in ADAPTERS.items() if getattr(a, "polling", False))
    created = await client.post(
        "/api/v1/data-sources",
        json={
            "name": f"Poll-{uuid.uuid4().hex[:6]}",
            "adapter_key": polling_key,
            "config": {"url": "https://example.org"},
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    assert (await client.get(f"/api/v1/data-sources/{source_id}/cursor", headers=h)).json() == {}
    reset = await client.post(
        f"/api/v1/data-sources/{source_id}/cursor",
        json={"since": "2026-08-01T00:00:00+00:00"},
        headers=h,
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["since"] == "2026-08-01T00:00:00+00:00"
    state = (await client.get(f"/api/v1/data-sources/{source_id}/cursor", headers=h)).json()
    assert state["since"] == "2026-08-01T00:00:00+00:00" and state["reset_by"]
    pushed = await client.post(
        "/api/v1/data-sources",
        json={"name": f"HTTP-{uuid.uuid4().hex[:6]}", "adapter_key": "generic_http"},
        headers=h,
    )
    assert (
        await client.post(f"/api/v1/data-sources/{pushed.json()['id']}/cursor", json={}, headers=h)
    ).status_code == 422
