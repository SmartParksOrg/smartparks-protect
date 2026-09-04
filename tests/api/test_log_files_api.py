"""Log files, browser syncs, command routes and the WebBLE command path through the API, and
the Cloudloop webhook with its token in the URL (phase 11)."""

import base64
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from shared.bus import RedisStreamsBus
from shared.connectivity.adapters.chirpstack import ChirpStackCommands
from shared.connectivity.adapters.webble import SOURCE_ID as WEBBLE_SOURCE_ID
from shared.enums import Role
from shared.models import DeviceType, ExternalIdentity, Position, SourceEvent
from tests.api.conftest import actor, project_actor
from tests.api.test_control_api import fake_submit
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name
from tests.decoder.test_logfiles import FLASH
from tests.shared.test_cloudloop_adapter import LINGO

pytestmark = pytest.mark.asyncio

LINE = base64.b64encode(bytes.fromhex("1d" + FLASH)).decode()
STATUS_FRAME = "04f40e0400a00095007f7f721444550000"


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _opencollar_device(client, db, device, headers) -> None:
    device_type = DeviceType(
        key=unique_name("oc").replace("-", "_"), label="OpenCollar", driver_key="opencollar"
    )
    db.add(device_type)
    await db.commit()
    response = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"device_type_id": str(device_type.id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def _decode(bus, log_file_id: str, *, reprocess: bool = False) -> None:
    """Run the file worker over what the API stored; the worker is not running in tests."""
    from protect_decoder.logfiles import process_log_file

    await process_log_file(bus, uuid.UUID(log_file_id), reprocess=reprocess)


async def test_upload_list_download_and_redecode(client, db, bus):
    admin, project, _entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    await _opencollar_device(client, db, device, h)
    content = (LINE + "\n").encode()
    files = {"file": ("raw_logs-all-SP05.txt", content, "text/plain")}
    response = await client.post(
        f"/api/v1/devices/{device['id']}/log-files", files=files, headers=h
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "queued" and row["acquisition_channel"] == "log_file"
    assert row["original_filename"] == "raw_logs-all-SP05.txt" and row["project_id"] == str(
        project.id
    )

    duplicate = await client.post(
        f"/api/v1/devices/{device['id']}/log-files", files=files, headers=h
    )
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["log_file_id"] == row["id"]
    garbage = await client.post(
        f"/api/v1/devices/{device['id']}/log-files",
        files={"file": ("x.txt", b"not a frame\n", "text/plain")},
        headers=h,
    )
    assert garbage.status_code == 422

    await _decode(bus, row["id"])
    got = (await client.get(f"/api/v1/log-files/{row['id']}", headers=h)).json()
    assert got["status"] == "complete", got
    frames = (
        await db.scalars(
            select(SourceEvent).where(
                SourceEvent.provider_metadata["log_file_id"].astext == row["id"]
            )
        )
    ).all()
    assert [(e.processing_status, e.error_code) for e in frames] == [("processed", None)]
    assert (got["frames_total"], got["records_found"], got["records_new"]) == (1, 3, 3)
    assert got["trace_id"] and got["period_start"] < got["period_end"]
    listing = (await client.get(f"/api/v1/devices/{device['id']}/log-files", headers=h)).json()
    assert [f["id"] for f in listing] == [row["id"]]
    download = await client.get(f"/api/v1/log-files/{row['id']}/download", headers=h)
    assert download.status_code == 200 and download.content == content
    assert 'filename="raw_logs-all-SP05.txt"' in download.headers["content-disposition"]

    redecode = await client.post(f"/api/v1/log-files/{row['id']}/redecode", headers=h)
    assert redecode.status_code == 200 and redecode.json()["status"] == "queued"
    await _decode(bus, row["id"], reprocess=True)
    got = (await client.get(f"/api/v1/log-files/{row['id']}", headers=h)).json()
    assert got["status"] == "complete" and (got["records_new"], got["records_duplicate"]) == (0, 3)

    trace = (await client.get(f"/api/v1/traces/{got['trace_id']}", headers=h)).json()
    assert trace["root_object_type"] == "log_file" and trace["status"] == "success"
    assert [s["operation"] for s in trace["steps"]][-1] == "file decoded"

    # The fixture's fixes are from 2023, before the project assignment; read them by device.
    positions = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(device["id"])))
    ).all()
    assert len(positions) == 3
    deliveries = (
        await client.get(
            "/api/v1/deliveries",
            params={"canonical_type": "position", "canonical_id": positions[0].id},
            headers=h,
        )
    ).json()
    assert len(deliveries) == 1
    assert deliveries[0]["acquisition_channel"] == "log_file" and deliveries[0]["first"] is True
    assert (
        deliveries[0]["file_uploaded_at"] and deliveries[0]["data_source_name"] == "Log file upload"
    )

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (
        await client.get(f"/api/v1/devices/{device['id']}/log-files", headers=viewer.headers)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/devices/{device['id']}/log-files", files=files, headers=viewer.headers
        )
    ).status_code == 403
    catalog = (await client.get(f"/api/v1/devices/{device['id']}/driver-catalog", headers=h)).json()
    assert catalog["driver_key"] == "opencollar" and len(catalog["catalog"]["settings"]) == 123


async def test_ble_sync_and_the_webble_command_route(client, db, bus, monkeypatch):
    admin, _project, _entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    await _opencollar_device(client, db, device, h)
    routes = (await client.get(f"/api/v1/devices/{device['id']}/routes", headers=h)).json()
    assert [r["adapter_key"] for r in routes] == ["chirpstack"] and routes[0]["default"] is True

    connected = await client.post(f"/api/v1/devices/{device['id']}/routes/webble", headers=h)
    assert connected.status_code == 200, connected.text
    webble = connected.json()
    assert webble["channel"] == "webble" and webble["requires_client"] and webble["available"]
    assert webble["default"] is False and webble["data_source_id"] == str(WEBBLE_SOURCE_ID)
    routes = (await client.get(f"/api/v1/devices/{device['id']}/routes", headers=h)).json()
    assert {r["adapter_key"] for r in routes} == {"chirpstack", "webble"}
    assert [r["adapter_key"] for r in routes if r["default"]] == ["chirpstack"]

    submit, _calls = fake_submit(
        [{"provider_ref": "q1", "statuses": ["accepted_by_network", "queued"]}]
    )
    monkeypatch.setattr(ChirpStackCommands, "submit", submit)
    auto = (
        await client.post(
            f"/api/v1/devices/{device['id']}/commands",
            json={"action_key": "REQUEST_STATUS"},
            headers=h,
        )
    ).json()
    assert auto["route"] == "lorawan" and auto["status"] == "queued"

    command = (
        await client.post(
            f"/api/v1/devices/{device['id']}/commands",
            json={"action_key": "REQUEST_STATUS", "route_data_source_id": webble["data_source_id"]},
            headers=h,
        )
    ).json()
    assert command["route"] == "webble" and command["status"] == "queued"
    assert command["provider_response"]["executor"] == "browser"
    assert command["provider_response"]["frame_hex"] == "20a400"
    assert command["f_port"] == 32 and command["payload_hex"] == "a400"

    result = await client.post(
        f"/api/v1/commands/{command['id']}/browser-result",
        json={"status": "transmitted", "detail": {"executed": True}},
        headers=h,
    )
    assert result.status_code == 200 and result.json()["status"] == "transmitted"
    assert (
        await client.post(
            f"/api/v1/commands/{auto['id']}/browser-result",
            json={"status": "transmitted"},
            headers=h,
        )
    ).status_code == 409

    bad = await client.post(
        f"/api/v1/devices/{device['id']}/log-files/ble-sync",
        json={"frames": ["zz"]},
        headers=h,
    )
    assert bad.status_code == 422
    sync = await client.post(
        f"/api/v1/devices/{device['id']}/log-files/ble-sync",
        json={"frames": [STATUS_FRAME], "label": "command", "attributes": {"device_name": "SP05"}},
        headers=h,
    )
    assert sync.status_code == 201, sync.text
    row = sync.json()
    assert row["acquisition_channel"] == "webble" and row["ble_synced_at"]
    assert (
        row["original_filename"].startswith("command-")
        and row["attributes"]["device_name"] == "SP05"
    )
    await _decode(bus, row["id"])
    got = (await client.get(f"/api/v1/log-files/{row['id']}", headers=h)).json()
    assert got["status"] == "complete" and got["records_new"] >= 1
    assert got["firmware_version"] == "4.4"
    detail = (await client.get(f"/api/v1/commands/{command['id']}", headers=h)).json()
    assert detail["command"]["status"] == "confirmed_by_device"
    assert [e["source"] for e in detail["executions"]][-2:] == ["browser", "device"]


async def test_cloudloop_webhook_with_query_token_and_address_allow_list(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("Cloudloop"),
                "adapter_key": "cloudloop",
                "config": {"allowed_source_ips": ["35.178.100.117", "52.56.155.169"]},
            },
            headers=h,
        )
    ).json()
    assert source["webhook_token_in_query"] is True
    token = source["webhook_token"]
    assert source["webhook_url"].endswith(f"/api/v1/ingest/http/{source['id']}?token={token}")
    url = f"/api/v1/ingest/http/{source['id']}"
    assert (await client.post(url, json=LINGO)).status_code == 401
    assert (
        await client.post(
            url, params={"token": token}, json=LINGO, headers={"X-Forwarded-For": "1.2.3.4"}
        )
    ).status_code == 403
    accepted = await client.post(
        url,
        params={"token": token},
        json=LINGO,
        headers={"X-Forwarded-For": "35.178.100.117, 10.0.0.1"},
    )
    assert accepted.status_code == 202 and accepted.json()["accepted"] == 1
    identity = await db.scalar(
        select(ExternalIdentity).where(ExternalIdentity.data_source_id == uuid.UUID(source["id"]))
    )
    assert identity.external_id == "300234065366010" and identity.identity_type == "imei"
    assert identity.attributes["thing_id"] == "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ"
    assert identity.device_id is None  # unknown until linked, kept for Needs Attention

    builtin = (await client.get(f"/api/v1/data-sources/{WEBBLE_SOURCE_ID}", headers=h)).json()
    assert builtin["builtin"] is True and builtin["adapter_key"] == "webble"
    assert (
        await client.delete(f"/api/v1/data-sources/{WEBBLE_SOURCE_ID}", headers=h)
    ).status_code == 409
