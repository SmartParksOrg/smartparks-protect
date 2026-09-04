"""Netmore: the export format (default and all fields), downlink responses, the MQTT connector,
the Connect REST downlink connector."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.netmore import (
    DEFAULT_TOPICS,
    NetmoreAdapter,
    NetmoreConnectCommands,
    NetmoreMqttConnector,
    NetmorePortalCommands,
    command_connector_for_platform,
    parse_message,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.registry import ADAPTERS, describe_adapter
from shared.device_drivers.base import lorawan_frame
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "netmore"


def source(config=None, credentials=None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="netmore",
        adapter_key="netmore",
        config=config if config is not None else {},
        credentials=credentials if credentials is not None else {"api_key": "k3y"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def test_all_fields_export():
    body = json.loads((FIXTURES / "uplink_all.json").read_text())
    messages = NetmoreAdapter().parse_webhook(source(), body, {})
    assert len(messages) == 1
    m = messages[0]
    assert m.external_id == "70B3D57ED0001234" and m.event_type == "uplink"
    assert (
        m.acquisition_channel == AcquisitionChannel.LORAWAN
        and m.ingestion_method == IngestionMethod.WEBHOOK
    )
    assert m.network_received_at == datetime(2026, 9, 4, 8, 0, 8, 599602, tzinfo=UTC)
    meta = m.provider_metadata
    assert meta["f_port"] == 2 and meta["f_cnt"] == 15800 and meta["spreading_factor"] == 7
    assert (
        meta["frequency_hz"] == 868300000
        and meta["best_rssi"] == -73.0
        and meta["gateway_count"] == 2
    )
    assert [r.gateway_id for r in m.gateway_receptions] == [
        "7276ff0039040879",
        "647fdaffff016c40".replace("ffff", "fffe"),
    ]
    assert (
        m.gateway_receptions[1].rssi == -47.0
        and m.gateway_receptions[0].attributes["mac"] == "7076FF02123C"
    )
    frame, port = lorawan_frame(m.payload, meta)
    assert port == 2 and frame is not None and frame[0] == 0xF2 and len(frame) == 32
    assert m.identity_attributes["tags"] == {"building": ["A"], "type": ["MOTION", "TEMP"]}


def test_default_export_has_one_reception():
    body = json.loads((FIXTURES / "uplink_default.json").read_text())
    m = parse_message(source(), body[0], IngestionMethod.WEBHOOK)
    assert m.provider_metadata["f_port"] == 1 and m.provider_metadata["frame_hex"] == "1234"
    assert [r.gateway_id for r in m.gateway_receptions] == ["506"] and m.gateway_receptions[
        0
    ].snr == 10.0


def test_downlink_response():
    body = json.loads((FIXTURES / "downlink_response.json").read_text())
    m = parse_message(source(), body, IngestionMethod.MQTT)
    assert (
        m.event_type == "downlink_transmitted"
        and m.provider_metadata["queue_ref"] == "MyRequestId-123"
    )
    error = parse_message(
        source(),
        {
            "requestId": "x",
            "deliveryStatus": "ERROR_SENDING",
            "devEui": "AA",
            "errorCode": "PAYLOAD_MISSING",
            "errorDescription": "Payload can't be empty",
        },
        IngestionMethod.MQTT,
    )
    assert error.event_type == "log" and error.provider_metadata["level"] == "ERROR"
    queued = parse_message(
        source(),
        {"requestId": "x", "deliveryStatus": "QUEUED", "devEui": "AA"},
        IngestionMethod.MQTT,
    )
    assert queued.event_type == "downlink_queued"


def test_decoded_format_is_refused():
    with pytest.raises(ApplicationError) as excinfo:
        parse_message(
            source(), {"devEui": "AA", "data": [{"n": "snr", "v": 7.5}]}, IngestionMethod.WEBHOOK
        )
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED and excinfo.value.user_actionable


def test_mqtt_connector_only_with_a_host():
    adapter = NetmoreAdapter()
    assert adapter.event_connector(source()) is None
    connector = adapter.event_connector(source({"mqtt_host": "mq.netmoregroup.com"}))
    assert isinstance(connector, NetmoreMqttConnector)
    assert DEFAULT_TOPICS == ["sensor/+/+/payload", "sensor/+/+/downlink-response"]


@pytest.mark.asyncio
async def test_rest_downlink_and_clear(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/downlink"):
            return httpx.Response(200, json=4711)
        return httpx.Response(204)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    commands = NetmoreConnectCommands(source({"platform": "connect", "validity_seconds": 600}))
    result = await commands.submit(
        "70B3D57ED0001234", b"\xa4\x00", {"f_port": 32, "confirmed": False}
    )
    assert result["provider_ref"] == "4711" and result["statuses"] == [
        "accepted_by_network",
        "queued",
    ]
    request = calls[0]
    assert (
        request.method == "POST"
        and request.url.path == "/api/v1/devices/LoRaWAN/70b3d57ed0001234/LoRaWAN/downlink"
    )
    params = dict(request.url.params)
    assert params == {"payloadHex": "a400", "fPort": "32", "confirmed": "false", "validity": "600"}
    assert request.headers["api-key"] == "k3y"
    await commands.flush("70B3D57ED0001234")
    assert calls[1].url.path.endswith("/LoRaWAN/clearDownlink")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (401, ErrorCode.CONNECTIVITY_AUTH_FAILED),
        (404, ErrorCode.DEVICE_NOT_FOUND),
        (400, ErrorCode.COMMAND_REJECTED),
        (502, ErrorCode.CONNECTIVITY_UNAVAILABLE),
    ],
)
async def test_rest_errors(monkeypatch, status_code, code):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(status_code, text="no")), **kw
        ),
    )
    with pytest.raises(ApplicationError) as excinfo:
        await NetmoreConnectCommands(source()).submit("AA", b"\x00", {"f_port": 1})
    assert excinfo.value.code == code


@pytest.mark.asyncio
async def test_missing_api_key():
    with pytest.raises(ApplicationError) as excinfo:
        await NetmoreConnectCommands(source(credentials={})).submit("AA", b"\x00", {"f_port": 1})
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED


def test_registered():
    described = describe_adapter(ADAPTERS["netmore"])
    assert described["push"] is True and described["can_send_commands"] is True
    assert "api_key" in described["credentials_schema"]


def test_platform_selects_the_connector():
    assert isinstance(
        command_connector_for_platform(source({"platform": "connect"})), NetmoreConnectCommands
    )
    assert isinstance(command_connector_for_platform(source()), NetmorePortalCommands)
    assert isinstance(NetmoreAdapter().command_connector(source({})), NetmorePortalCommands)
    with pytest.raises(ApplicationError):
        command_connector_for_platform(source({"platform": "nope"}))


@pytest.mark.asyncio
async def test_portal_login_downlink_queue_and_flush(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/core/login/tim"):
            assert json.loads(request.content) == {"password": "pw"}
            return httpx.Response(200, json={"success": True, "token": "tok-1"})
        assert request.headers["authorization"] == "Bearer tok-1"
        if request.url.path.endswith("/downlink") and request.method == "POST":
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith("/downlink") and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "requestFPort": "32",
                        "requestPayloadHex": "A400",
                        "requestFCnt": 12,
                        "deliveryStatus": "QUEUED",
                    }
                ],
            )
        return httpx.Response(200)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    portal = NetmorePortalCommands(source({}, {"username": "tim", "password": "pw"}))
    result = await portal.submit(
        "70b3d57ed0001234", b"\xa4\x00", {"f_port": 32, "reference": "cmd-1"}
    )
    assert result["provider_ref"] == "cmd-1" and result["statuses"] == [
        "accepted_by_network",
        "queued",
    ]
    post = calls[1]
    assert post.url.path == "/rest/net/sensors/70B3D57ED0001234/downlink"
    assert dict(post.url.params) == {
        "fPort": "32",
        "payloadHex": "A400",
        "confirmed": "false",
        "validity": "3600",
        "requestId": "cmd-1",
    }
    queue = await portal.queue("70B3D57ED0001234")
    assert queue == [
        {
            "id": "7",
            "fPort": 32,
            "data": None,
            "data_hex": "A400",
            "confirmed": None,
            "isPending": True,
            "fCntDown": 12,
            "deliveryStatus": "QUEUED",
        }
    ]
    await portal.flush("70B3D57ED0001234")
    assert calls[-1].url.path.endswith("/downlink/clear")
    assert len([c for c in calls if "login" in c.url.path]) == 1  # the token is cached


@pytest.mark.asyncio
async def test_portal_relogin_on_401_and_bad_password(monkeypatch):
    state = {"logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "login" in request.url.path:
            state["logins"] += 1
            return httpx.Response(200, json={"token": f"tok-{state['logins'] + 1}"})
        if request.headers["authorization"] == "Bearer tok-1":
            return httpx.Response(401, text="expired")
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    portal = NetmorePortalCommands(source({}, {"username": "tim", "password": "pw"}))
    portal._token = "tok-1"
    await portal.submit("AA", b"\x00", {"f_port": 1})
    assert state["logins"] == 1

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"success": False, "message": "bad password"})
            ),
            **kw,
        ),
    )
    with pytest.raises(ApplicationError) as excinfo:
        await NetmorePortalCommands(source({}, {"username": "tim", "password": "no"})).submit(
            "AA", b"\x00", {"f_port": 1}
        )
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED and "bad password" in str(
        excinfo.value
    )
    with pytest.raises(ApplicationError):
        await NetmorePortalCommands(source({}, {})).submit("AA", b"\x00", {"f_port": 1})
