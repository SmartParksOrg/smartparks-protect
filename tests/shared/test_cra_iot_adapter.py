"""CRA IoT adapter (decision D90): the documented envelope and message, the single sign-on
token, the downlink call and the device listing."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters import cra_iot
from shared.connectivity.adapters.cra_iot import (
    CraCommands,
    CraIotAdapter,
    CraManagement,
    battery_percent,
    parse_message,
    unwrap_envelope,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import ErrorCode, IngestionMethod
from shared.trace import ApplicationError

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "cra_iot"


def source(config=None, credentials=None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="cra",
        adapter_key="cra_iot",
        config=config if config is not None else {},
        credentials=credentials
        if credentials is not None
        else {"username": "collars@smartparks.org", "password": "pw"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def test_documented_envelope_becomes_an_uplink_with_receptions():
    body = json.loads((FIXTURES / "envelope.json").read_text())
    messages = CraIotAdapter().parse_webhook(source(), body, {})
    assert len(messages) == 1
    message = messages[0]
    assert message.event_type == "uplink" and message.external_id == "000DB53112743570"
    assert message.ingestion_method == IngestionMethod.WEBHOOK
    meta = message.provider_metadata
    assert meta["frame_hex"] == "010af0061e01c8" and meta["f_port"] == 2 and meta["f_cnt"] == 787465
    assert meta["spreading_factor"] == 8 and meta["frequency_hz"] == 867900000
    assert meta["cra_cmd"] == "gw" and meta["cra_tags"] == ["geolocation"]
    assert meta["message_id"] == "65a0fb2bed4643031c768ce8" and "battery_percent" not in meta
    assert message.network_received_at == datetime(2024, 1, 12, 8, 41, 15, 592000, tzinfo=UTC)
    assert len(message.gateway_receptions) == 4
    first = message.gateway_receptions[0]
    assert first.gateway_id == "647fdaffff0069f5"
    assert first.rssi == -108 and first.snr == 4.2 and first.attributes["lat"] == 50.054771


def test_rx_gw_geo_and_encrypted_rules():
    gw = {"cmd": "gw", "EUI": "abc", "ts": 1705048875592, "port": 1, "data": "01", "gws": []}
    rx = {"cmd": "rx", "EUI": "abc", "ts": 1705048875592, "port": 1, "data": "01", "rssi": -100}
    assert parse_message(source(), rx) is None
    assert parse_message(source(), gw) is not None
    only_rx = source({"uplink_cmd": "rx"})
    assert parse_message(only_rx, gw) is None
    from_rx = parse_message(only_rx, rx)
    assert from_rx is not None and from_rx.provider_metadata["best_rssi"] == -100
    geo = parse_message(
        source(),
        {
            "cmd": "geo",
            "EUI": "abc",
            "ts": "2022-11-23T21:24:08.979Z",
            "lat": 50.1,
            "lon": 14.4,
            "alt": 311,
            "method": "TDOA",
        },
    )
    assert geo is not None and geo.event_type == "location"
    assert geo.provider_metadata["latitude"] == 50.1 and geo.provider_metadata["method"] == "TDOA"
    assert geo.network_received_at == datetime(2022, 11, 23, 21, 24, 8, 979000, tzinfo=UTC)
    assert parse_message(source(), {"cmd": "tx", "EUI": "abc"}) is None
    with pytest.raises(ApplicationError) as excinfo:
        parse_message(source(), {"cmd": "gw", "EUI": "abc", "encdata": "ff"})
    assert "AppSKey" in excinfo.value.message
    with pytest.raises(ApplicationError):
        parse_message(source(), "not an object")
    assert battery_percent(255) is None and battery_percent(0) is None
    assert battery_percent(1) == 0 and battery_percent(254) == 100 and battery_percent(128) == 50
    assert parse_message(source(), {**gw, "bat": 128}).provider_metadata["battery_percent"] == 50


def test_unwrap_accepts_bare_messages_lists_and_skips_other_types():
    assert unwrap_envelope({"cmd": "gw"}) == [({"cmd": "gw"}, [])]
    assert unwrap_envelope(
        [{"type": "X", "data": "{}"}, {"type": "D", "data": {"cmd": "gw"}, "tags": ["a"]}]
    ) == [({"cmd": "gw"}, ["a"])]
    with pytest.raises(ApplicationError):
        unwrap_envelope({"type": "D", "data": "{not json"})


async def test_downlink_and_device_listing_through_the_api(monkeypatch):
    calls = []
    cra_iot._tokens.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        calls.append(
            (request.method, request.url.host, request.url.path, dict(request.url.params), auth)
        )
        if request.url.host == "sso.cra.cz":
            form = dict(httpx.QueryParams(request.content.decode()))
            assert form["grant_type"] == "password" and form["client_id"] == "iot-api-client"
            assert form["client_secret"] == cra_iot.DOCUMENTED_CLIENT_SECRET
            if form["password"] != "pw":
                return httpx.Response(
                    401,
                    json={
                        "error": "invalid_grant",
                        "error_description": "Invalid user credentials",
                    },
                )
            return httpx.Response(200, json={"access_token": "acc", "expires_in": 300})
        assert auth == "Bearer acc"
        if request.url.path.endswith("/down/messages") and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "cmd": "tx",
                "EUI": "70B3D57ED0001234",
                "port": 4,
                "data": "0102",
                "confirmed": True,
                "clear": False,
            }
            return httpx.Response(200, json={"status": "success"})
        if request.url.path.endswith("/lora/devices"):
            offset = int(request.url.params["offset"])
            items = [
                {
                    "deviceId": f"70B3D57ED000{i:04X}",
                    "custDeviceName": f"Collar {i}",
                    "status": "active",
                    "enabled": True,
                }
                for i in range(offset, min(offset + 100, 150))
            ]
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "metadata": {"count": 150, "result": len(items)},
                    "data": items,
                },
            )
        return httpx.Response(404, json={"status": "error", "code": 404, "errors": ["not found"]})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )
    result = await CraCommands(source()).submit(
        "70b3d57ed0001234", bytes.fromhex("0102"), {"f_port": 4, "confirmed": True}
    )
    assert result["statuses"] == ["accepted_by_network", "queued"] and result["response"] == {
        "status": "success"
    }
    devices = await CraManagement(source()).list_devices()
    assert len(devices) == 150 and devices[0] == {
        "external_id": "70B3D57ED0000000",
        "identity_type": "dev_eui",
        "name": "Collar 0",
        "attributes": {"status": "active", "enabled": True},
    }
    assert sum(1 for c in calls if c[1] == "sso.cra.cz") == 1  # token cached
    check = await CraManagement(source()).test_connection()
    assert check == {"ok": True, "device_count": 150}
    cra_iot._tokens.clear()
    with pytest.raises(ApplicationError) as excinfo:
        await CraManagement(
            source(credentials={"username": "x@y", "password": "bad"})
        ).test_connection()
    assert (
        excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
        and "Invalid user credentials" in excinfo.value.message
    )
    with pytest.raises(ApplicationError):
        await CraCommands(source(credentials={})).submit("a", b"", {"f_port": 1})
    with pytest.raises(ApplicationError):
        await CraCommands(source()).flush("70B3D57ED0001234")
