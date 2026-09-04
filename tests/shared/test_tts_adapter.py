"""The Things Stack adapter (decision D84) against the documented message shapes, the
downlink API and the gateway API; the Actility variant of the ThingPark adapter."""

import base64
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.connectivity.adapters.actility_thingpark import ActilityThingParkAdapter
from shared.connectivity.adapters.kpn_thingpark import KpnThingParkAdapter
from shared.connectivity.adapters.tts import (
    TtsAdapter,
    TtsCommands,
    TtsManagement,
    gateway_updates_from_listing,
    parse_message,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import ErrorCode
from shared.trace import ApplicationError

pytestmark = pytest.mark.asyncio

FRAME = bytes.fromhex("f40e0400a00095007f7f721444550000")
UPLINK = {
    "end_device_ids": {
        "device_id": "sp05-0001",
        "application_ids": {"application_id": "smart-parks-collars"},
        "dev_eui": "70B3D57ED0001234",
        "join_eui": "0000000000000000",
        "dev_addr": "260B1234",
    },
    "correlation_ids": ["as:up:01"],
    "received_at": "2026-09-04T10:12:03.123456789Z",
    "uplink_message": {
        "session_key_id": "AY",
        "f_port": 4,
        "f_cnt": 42,
        "frm_payload": base64.b64encode(FRAME).decode(),
        "rx_metadata": [
            {
                "gateway_ids": {"gateway_id": "eui-0016c001f153a14c", "eui": "0016C001F153A14C"},
                "time": "2026-09-04T10:12:03Z",
                "rssi": -101,
                "channel_rssi": -101,
                "snr": 7.5,
                "channel_index": 3,
                "location": {
                    "latitude": -24.9,
                    "longitude": 31.5,
                    "altitude": 300,
                    "source": "SOURCE_REGISTRY",
                },
            },
            {"gateway_ids": {"gateway_id": "eui-aabbccddeeff0011"}, "rssi": -110, "snr": 2.0},
        ],
        "settings": {
            "data_rate": {"lora": {"bandwidth": 125000, "spreading_factor": 9}},
            "frequency": "868100000",
        },
        "consumed_airtime": "0.205824s",
    },
}


def context(config=None, credentials=None):
    return DataSourceContext(
        id=uuid.uuid4(),
        name="tts",
        adapter_key="tts",
        config=config
        or {"application_id": "smart-parks-collars", "api_url": "https://eu1.example"},
        credentials=credentials or {"api_key": "NNSXS.KEY"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


async def test_uplink_becomes_a_lorawan_message_with_gateway_receptions():
    message = parse_message(context(), UPLINK)
    assert message.external_id == "70B3D57ED0001234" and message.event_type == "uplink"
    assert message.provider_metadata["frame_hex"] == FRAME.hex()
    assert message.provider_metadata["f_port"] == 4 and message.provider_metadata["f_cnt"] == 42
    assert message.provider_metadata["spreading_factor"] == 9
    assert (
        message.provider_metadata["best_rssi"] == -101
        and message.provider_metadata["best_snr"] == 7.5
    )
    assert message.provider_metadata["gateway_count"] == 2
    assert message.network_received_at == datetime(2026, 9, 4, 10, 12, 3, 123456, tzinfo=UTC)
    assert [r.gateway_id for r in message.gateway_receptions] == [
        "eui-0016c001f153a14c",
        "eui-aabbccddeeff0011",
    ]
    assert message.gateway_receptions[0].attributes["latitude"] == -24.9
    assert message.identity_attributes == {
        "application_id": "smart-parks-collars",
        "device_id": "sp05-0001",
        "join_eui": "0000000000000000",
        "dev_addr": "260B1234",
    }


async def test_other_message_types_and_downlink_references():
    ids = UPLINK["end_device_ids"]
    join = parse_message(
        context(),
        {
            "end_device_ids": ids,
            "received_at": "2026-09-04T10:00:00Z",
            "join_accept": {"session_key_id": "AY"},
        },
    )
    assert join.event_type == "join"
    sent = parse_message(
        context(),
        {
            "end_device_ids": ids,
            "correlation_ids": ["as:down:1"],
            "downlink_sent": {
                "f_port": 32,
                "f_cnt": 7,
                "frm_payload": "pAA=",
                "correlation_ids": ["smartparks-protect:cmd-1"],
            },
        },
    )
    assert (
        sent.event_type == "downlink_transmitted" and sent.provider_metadata["queue_ref"] == "cmd-1"
    )
    nack = parse_message(
        context(),
        {
            "end_device_ids": ids,
            "downlink_nack": {"f_port": 32, "correlation_ids": ["smartparks-protect:cmd-1"]},
        },
    )
    assert nack.event_type == "downlink_ack" and nack.provider_metadata["acknowledged"] is False
    failed = parse_message(
        context(),
        {
            "end_device_ids": ids,
            "downlink_failed": {
                "downlink": {"f_port": 32, "correlation_ids": ["smartparks-protect:cmd-2"]},
                "error": {"name": "device_not_found", "message_format": "no session"},
            },
        },
    )
    assert failed.event_type == "log" and failed.provider_metadata["level"] == "ERROR"
    assert (
        failed.provider_metadata["queue_ref"] == "cmd-2"
        and failed.provider_metadata["description"] == "no session"
    )
    solved = parse_message(
        context(),
        {
            "end_device_ids": ids,
            "location_solved": {
                "location": {"latitude": -24.9, "longitude": 31.5, "source": "SOURCE_GPS"}
            },
        },
    )
    assert solved.event_type == "location" and solved.provider_metadata["latitude"] == -24.9
    with pytest.raises(ApplicationError):
        parse_message(context(), {"hello": "world"})
    batch = TtsAdapter().parse_webhook(context(), [UPLINK, UPLINK], {})
    assert len(batch) == 2


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_downlink_push_with_correlation_id(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (request.method, request.url.path, request.headers.get("authorization"), request.read())
        )
        return httpx.Response(200, json={})

    _mock(monkeypatch, handler)
    result = await TtsCommands(context()).submit(
        "70B3D57ED0001234",
        bytes.fromhex("a400"),
        {
            "f_port": 32,
            "confirmed": False,
            "reference": "cmd-9",
            "identity_attributes": {
                "application_id": "smart-parks-collars",
                "device_id": "sp05-0001",
            },
        },
    )
    method, path, auth, body = calls[0]
    assert (
        method == "POST"
        and path == "/api/v3/as/applications/smart-parks-collars/devices/sp05-0001/down/push"
    )
    assert auth == "Bearer NNSXS.KEY"
    assert b'"frm_payload":"pAA="' in body.replace(
        b" ", b""
    ) and b'"correlation_ids":["smartparks-protect:cmd-9"]' in body.replace(b" ", b"")
    assert result["provider_ref"] == "cmd-9" and result["statuses"] == [
        "accepted_by_network",
        "queued",
    ]
    with pytest.raises(ApplicationError) as excinfo:
        await TtsCommands(context()).submit(
            "70B3D57ED0001234", b"\xa4\x00", {"f_port": 32, "identity_attributes": {}}
        )
    assert excinfo.value.code == ErrorCode.COMMAND_REJECTED and "device id" in str(excinfo.value)


async def test_gateways_and_devices(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/gateways":
            return httpx.Response(
                200,
                json={
                    "gateways": [
                        {
                            "ids": {
                                "gateway_id": "eui-0016c001f153a14c",
                                "eui": "0016C001F153A14C",
                            },
                            "name": "Kafue north",
                            "antennas": [
                                {
                                    "location": {
                                        "latitude": -24.9,
                                        "longitude": 31.5,
                                        "altitude": 300,
                                    }
                                }
                            ],
                            "frequency_plan_id": "EU_863_870",
                        }
                    ]
                },
            )
        if request.url.path.endswith("/connection/stats"):
            return httpx.Response(
                200,
                json={
                    "connected_at": "2026-09-04T09:00:00Z",
                    "last_uplink_received_at": "2026-09-04T10:12:03Z",
                    "uplink_count": "120",
                    "downlink_count": "3",
                },
            )
        if request.url.path == "/api/v3/applications/smart-parks-collars/devices":
            return httpx.Response(
                200,
                json={
                    "end_devices": [
                        {
                            "ids": {
                                "device_id": "sp05-0001",
                                "dev_eui": "70b3d57ed0001234",
                                "join_eui": "0000000000000000",
                            },
                            "name": "Rhino 14 collar",
                        }
                    ]
                },
            )
        if request.url.path == "/api/v3/applications/smart-parks-collars":
            return httpx.Response(200, json={"name": "Smart Parks collars"})
        return httpx.Response(404)

    _mock(monkeypatch, handler)
    management = TtsManagement(context())
    updates = await management.list_gateway_updates()
    assert len(updates) == 1 and updates[0].gateway_id == "eui-0016c001f153a14c"
    assert (
        updates[0].status == "online"
        and updates[0].latitude == -24.9
        and updates[0].stats == {"uplink_count": "120", "downlink_count": "3"}
    )
    assert updates[0].seen_at == datetime(2026, 9, 4, 10, 12, 3, tzinfo=UTC)
    devices = await management.list_devices()
    assert devices == [
        {
            "external_id": "70B3D57ED0001234",
            "identity_type": "dev_eui",
            "name": "Rhino 14 collar",
            "attributes": {
                "application_id": "smart-parks-collars",
                "device_id": "sp05-0001",
                "join_eui": "0000000000000000",
            },
        }
    ]
    assert (await management.test_connection())["application"] == "Smart Parks collars"
    assert gateway_updates_from_listing([{"ids": {}}]) == []


def test_actility_is_the_thingpark_adapter_with_its_own_face():
    adapter = ActilityThingParkAdapter()
    assert isinstance(adapter, KpnThingParkAdapter)
    assert adapter.key == "actility_thingpark" and adapter.label == "Actility ThingPark"
    assert adapter.config_example["downlink_url"].startswith("https://community.thingpark.io")
    assert adapter.default_capabilities == KpnThingParkAdapter.default_capabilities
