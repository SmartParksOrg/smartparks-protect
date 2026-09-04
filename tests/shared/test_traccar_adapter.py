"""Traccar adapter: positions, events, device status, webhook, command proof of concept."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.traccar import (
    TraccarAdapter,
    TraccarCommands,
    TraccarConnector,
    TraccarManagement,
    event_type_of,
    parse_event,
    parse_position,
    socket_url,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "traccar"
FRAME = json.loads((FIXTURES / "socket_frame.json").read_text())
DEVICES = json.loads((FIXTURES / "devices.json").read_text())


def _source(credentials=None, config=None):
    return DataSourceContext(
        id=uuid.uuid4(),
        name="Traccar",
        adapter_key="traccar",
        config=config if config is not None else {"url": "https://tracks.example.org"},
        credentials=credentials if credentials is not None else {"email": "bot@example.org", "password": "pw"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_position_becomes_generic_json():
    position = FRAME["positions"][0]
    message = parse_position(_source(), position, DEVICES[0])
    assert message.external_id == "17" and message.identity_type == "traccar_device_id"
    assert message.event_type == "position"
    assert message.acquisition_channel == AcquisitionChannel.CELLULAR
    assert message.ingestion_method == IngestionMethod.WEBSOCKET
    payload = message.payload
    assert payload["time"] == "2026-09-04T09:15:00+00:00"
    assert payload["lat"] == -24.9012 and payload["lon"] == 31.5123
    assert payload["speed"] == round(21.6 * 0.514444, 3)  # knots to m/s
    assert payload["heading"] == 87.5 and payload["satellites"] == 11
    assert payload["measurements"] == {
        "battery_level": 87.0,
        "battery_voltage": 4.02,
        "external_voltage": 13.9,
        "odometer_m": 152340.0,
        "total_distance_m": 4523110.5,
    }
    assert payload["state"] == {"ignition": True, "motion": True}
    assert payload["raw"] == position
    assert message.network_received_at == datetime(2026, 9, 4, 9, 15, 3, tzinfo=UTC)
    assert message.identity_attributes == {
        "device_name": "Ranger truck 2",
        "unique_id": "356938035643809",
        "model": "FMB920",
        "category": "truck",
    }
    invalid = parse_position(_source(), {**position, "valid": False})
    assert invalid.event_type == "position_invalid" and "lat" not in invalid.payload
    with pytest.raises(ApplicationError):
        parse_position(_source(), {"latitude": 1})


def test_event_types_and_webhook():
    assert event_type_of("geofenceExit") == "GEOFENCE_EXIT"
    assert event_type_of("alarm") == "ALARM"
    assert event_type_of("deviceOnline") == "DEVICE_ONLINE"
    event = FRAME["events"][0]
    message = parse_event(_source(), event, DEVICES[0], FRAME["positions"][0])
    item = message.payload["events"][0]
    assert item["type"] == "GEOFENCE_EXIT" and item["severity"] == "warning"
    assert item["title"] == "Ranger truck 2: geofenceExit"
    assert item["lat"] == -24.9012 and item["context"]["geofence_id"] == 3
    assert message.payload["time"] == "2026-09-04T09:15:00+00:00"
    adapter = TraccarAdapter()
    hooked = adapter.parse_webhook(
        _source(), {"event": event, "device": DEVICES[0], "position": FRAME["positions"][0]}, {}
    )
    assert len(hooked) == 1 and hooked[0].ingestion_method == IngestionMethod.WEBHOOK
    positions = adapter.parse_webhook(_source(), {"position": FRAME["positions"][0]}, {})
    assert positions[0].event_type == "position"
    with pytest.raises(ApplicationError):
        adapter.parse_webhook(_source(), {"nothing": 1}, {})
    with pytest.raises(ApplicationError):
        adapter.parse_webhook(_source(), [], {})


@pytest.mark.asyncio
async def test_frames_emit_positions_events_and_status_changes():
    connector = TraccarConnector(_source())
    emitted = []

    async def emit(message):
        emitted.append(message)

    await connector.on_frame(json.dumps(FRAME), emit)
    assert [m.event_type for m in emitted] == ["state", "position", "event"]
    assert emitted[0].payload["state"] == {"connection": "online"}
    assert emitted[1].identity_attributes["device_name"] == "Ranger truck 2"
    emitted.clear()
    await connector.on_frame(json.dumps({"devices": [FRAME["devices"][0]]}), emit)
    assert emitted == []  # same status, nothing new
    await connector.on_frame(
        json.dumps({"devices": [{**FRAME["devices"][0], "status": "offline"}]}), emit
    )
    assert emitted[0].payload["state"] == {"connection": "offline"}
    await connector.on_frame("not json", emit)
    await connector.on_frame(json.dumps([1, 2]), emit)
    assert len(emitted) == 1


def test_socket_url_and_config_errors():
    assert socket_url(_source()) == "wss://tracks.example.org/api/socket"
    assert (
        socket_url(_source(config={"url": "http://localhost:8082/"}))
        == "ws://localhost:8082/api/socket"
    )
    with pytest.raises(ApplicationError):
        socket_url(_source(config={}))


@pytest.mark.asyncio
async def test_session_devices_and_commands(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("cookie")))
        if request.url.path == "/api/session" and request.method == "POST":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            if body.get("password") != "pw":
                return httpx.Response(401)
            return httpx.Response(
                200,
                json={"id": 1, "email": "bot@example.org"},
                headers={"set-cookie": "JSESSIONID=abc123; Path=/"},
            )
        if request.url.path == "/api/session" and request.method == "GET":
            return httpx.Response(
                200, json={"id": 1}, headers={"set-cookie": "JSESSIONID=tok; Path=/"}
            )
        if "JSESSIONID" not in (request.headers.get("cookie") or ""):
            return httpx.Response(401)
        if request.url.path == "/api/devices":
            return httpx.Response(200, json=DEVICES)
        if request.url.path == "/api/positions":
            return httpx.Response(200, json=FRAME["positions"])
        if request.url.path == "/api/commands/types":
            return httpx.Response(200, json=[{"type": "engineStop"}, {"type": "positionSingle"}])
        if request.url.path == "/api/commands/send":
            body = json.loads(request.content)
            if body["type"] == "unknown":
                return httpx.Response(400, text="bad type")
            return httpx.Response(202 if body["deviceId"] == 18 else 200, json={"id": 77, **body})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    management = TraccarManagement(_source())
    devices = await management.list_devices()
    assert [d["external_id"] for d in devices] == ["17", "18"]
    assert devices[0]["attributes"]["unique_id"] == "356938035643809"
    assert (await management.test_connection())["devices"] == 2
    assert calls[0] == ("POST", "/api/session", None) and calls[1][2] == "JSESSIONID=abc123"

    commands = TraccarCommands(_source())
    payload = json.dumps({"type": "engineStop", "attributes": {}}).encode()
    sent = await commands.submit("17", payload, {})
    assert (
        sent["statuses"] == ["accepted_by_network", "transmitted"] and sent["provider_ref"] == "77"
    )
    queued = await commands.submit("18", payload, {})
    assert queued["statuses"] == ["accepted_by_network", "queued"]
    with pytest.raises(ApplicationError) as rejected:
        await commands.submit("17", json.dumps({"type": "unknown"}).encode(), {})
    assert rejected.value.code == "COMMAND_REJECTED"
    with pytest.raises(ApplicationError):
        await commands.submit("17", b"\x01\x02", {})
    assert [t["type"] for t in await commands.command_types("17")] == [
        "engineStop",
        "positionSingle",
    ]

    token = TraccarManagement(_source(credentials={"token": "t"}))
    assert (await token.test_connection())["ok"]
    with pytest.raises(ApplicationError) as refused:
        await TraccarManagement(
            _source(credentials={"email": "x", "password": "wrong"})
        ).list_devices()
    assert refused.value.code == "CONNECTIVITY_AUTH_FAILED"
    with pytest.raises(ApplicationError):
        await TraccarManagement(_source(credentials={})).list_devices()


def test_adapter_metadata():
    adapter = TraccarAdapter()
    assert adapter.event_connector(_source()) is not None
    assert adapter.default_capabilities.device_management
    assert "OPEN_DEVICE" in adapter.default_link_templates
    assert adapter.acquisition_channel == AcquisitionChannel.CELLULAR
