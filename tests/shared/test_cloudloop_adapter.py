"""Cloudloop adapter (decision D78) against the documented Lingo and Core shapes and the
Postman collection's endpoint forms."""

import base64
from datetime import UTC, datetime

import httpx
import pytest

from shared.connectivity.adapters.cloudloop import (
    CloudloopAdapter,
    CloudloopCommands,
    CloudloopManagement,
    parse_lingo,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.trace import ApplicationError
from tests.shared.test_adapters_and_drivers import context as base_context

pytestmark = pytest.mark.asyncio

# The LingoMO example of the knowledge base (destinations/http), an SBD session from a
# RockBLOCK-class device. The payload bytes are opaque to the adapter.
LINGO = {
    "id": "fb1f8a90-cb47-4795-b11e-f5b804edf310",
    "receivedAt": {"year": 2023, "month": 10, "day": 18, "hour": 12, "minute": 26, "second": 10},
    "identity": {
        "accountId": "yJGjpPobLlmOdanVkPWAKYzNMgwVZkrR",
        "subscriber": {
            "id": "XgwyNPpDmebJLWXmwgEoARqxMdZOVGva",
            "type": "SUBSCRIBER_TYPE_SBD",
            "description": "",
        },
        "hardware": {
            "id": "joGRxQrXpzkPJEglMOBydwYZbqmDagNA",
            "type": "HARDWARE_TYPE_LEOPARD3",
            "imei": "300234065366010",
            "serial": "",
        },
        "identifier": "300234065366010",
        "thingId": "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ",
    },
    "sbd": {
        "imei": "300234065366010",
        "cdrReference": "3301853709",
        "momsn": 5394,
        "mtmsn": 0,
        "sessionAt": {"year": 2023, "month": 10, "day": 18, "hour": 12, "minute": 26, "second": 9},
        "status": "SESSION_STATUS_OK",
        "location": {"latitude": 50.898133333333334, "longitude": -1.1946666666666665, "cep": 4.0},
    },
    "message": "JgBrey0iF+0K7YvAAAQBx0QwBQ==",
    "signature": "",
}
CORE = {
    "imei": "300534985236430",
    "device_type": "LEOPARD3",
    "serial": "",
    "momsn": "5394",
    "transmit_time": "2023-10-18T15:22:09Z",
    "id": "d94a6f6c-4e8e-4f11-bfdb-3a113002f6c5",
    "iridium_latitude": "50.8696",
    "iridium_longitude": "-1.2503",
    "cep": "4",
    "data": "0d930ef9636865aba50d1f8e090e031500006468",
}


def context(**overrides):
    base = base_context("cloudloop")
    return DataSourceContext(
        id=base.id,
        name=base.name,
        adapter_key="cloudloop",
        config=overrides.get("config", {}),
        credentials=overrides.get("credentials", {"token": "f7ba9e62-50c9-4a72-906a-d4da9822322"}),
        capabilities=AdapterCapabilities(uplink=True, downlink=True, device_management=True),
    )


async def test_lingo_message_keeps_satellite_time_apart_from_the_payload():
    message = parse_lingo(LINGO)
    assert message.external_id == "300234065366010" and message.identity_type == "imei"
    assert message.acquisition_channel == AcquisitionChannel.IRIDIUM
    assert message.ingestion_method == IngestionMethod.WEBHOOK
    assert message.event_type == "uplink"
    assert message.payload["data_hex"] == base64.b64decode(LINGO["message"]).hex()
    assert message.provider_metadata["bytes"] == 19
    assert message.satellite_delivered_at == datetime(2023, 10, 18, 12, 26, 9, tzinfo=UTC)
    assert message.network_received_at == datetime(2023, 10, 18, 12, 26, 10, tzinfo=UTC)
    assert message.provider_metadata["momsn"] == 5394
    assert message.provider_metadata["iridium_cep_km"] == 4.0
    assert message.provider_metadata["cloudloop_message_id"] == LINGO["id"]
    assert message.identity_attributes["thing_id"] == "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ"
    assert message.identity_attributes["hardware_type"] == "HARDWARE_TYPE_LEOPARD3"


async def test_webhook_accepts_lingo_and_core_and_rejects_others():
    adapter = CloudloopAdapter()
    lingo = adapter.parse_webhook(context(), LINGO, {})
    assert len(lingo) == 1 and lingo[0].external_id == "300234065366010"
    core = adapter.parse_webhook(context(), CORE, {})[0]
    assert core.external_id == "300534985236430"
    assert core.payload["data_hex"] == CORE["data"]
    assert core.satellite_delivered_at == datetime(2023, 10, 18, 15, 22, 9, tzinfo=UTC)
    assert core.provider_metadata["iridium_latitude"] == 50.8696
    with pytest.raises(ApplicationError):
        adapter.parse_webhook(context(), {"hello": "world"}, {})
    session_only = adapter.parse_webhook(context(), {**LINGO, "message": ""}, {})[0]
    assert session_only.event_type == "sbd_session" and "data_hex" not in session_only.payload


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_sbd_command_posts_the_satellite_frame_to_the_thing(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (request.method, str(request.url), dict(httpx.QueryParams(request.content.decode())))
        )
        return httpx.Response(200, json={"id": "MTmsg123"})

    _mock_client(monkeypatch, handler)
    commands = CloudloopCommands(context())
    result = await commands.submit(
        "300234065366010",
        bytes.fromhex("a400"),
        {
            "f_port": 32,
            "identity_type": "imei",
            "identity_attributes": {"thing_id": "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ"},
        },
    )
    method, url, fields = calls[0]
    assert method == "POST" and url == "https://api.cloudloop.com/Data/DoSendSbdMessage"
    assert fields == {
        "token": "f7ba9e62-50c9-4a72-906a-d4da9822322",
        "thing": "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ",
        "message": "20A400",
    }
    assert result["provider_ref"] == "MTmsg123"
    assert result["statuses"] == ["accepted_by_network", "queued"]
    assert result["frame_hex"] == "20a400"


async def test_sbd_command_needs_a_thing_and_fits_the_sbd_limit(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={}))
    commands = CloudloopCommands(context())
    with pytest.raises(ApplicationError) as excinfo:
        await commands.submit(
            "300234065366010", b"\xa4\x00", {"f_port": 32, "identity_type": "imei"}
        )
    assert excinfo.value.code == ErrorCode.COMMAND_REJECTED and "thing id" in str(excinfo.value)
    with pytest.raises(ApplicationError) as excinfo:
        await commands.submit(
            "thing", bytes(270), {"f_port": 3, "identity_type": "cloudloop_thing"}
        )
    assert "270" in str(excinfo.value)
    # a thing identity is used as is
    result = await commands.submit(
        "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ",
        b"\x02\x04\x10\x0e\x00\x00",
        {"f_port": 3, "identity_type": "cloudloop_thing"},
    )
    assert result["thing"] == "DgXeoxwVPMyrdOBJeEGlqKRJLbajQkzZ"


async def test_management_lists_things_and_pings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("Platform/Ping"):
            return httpx.Response(200, json={"pong": True})
        if request.url.path.endswith("Data/GetThings"):
            return httpx.Response(
                200,
                json={
                    "things": [
                        {
                            "supportsSbd": True,
                            "id": "DanGRxQrXpzkPJEgyKnydwYZbqmDagNA",
                            "subscriberSbd": "KXeNzdgDqZwrQBbNoDjBxMLlmoGpaOAR",
                            "account": "ejoGRxQrXpzkPJngbjBydwYZbqmDagNA",
                        }
                    ]
                },
            )
        return httpx.Response(401)

    _mock_client(monkeypatch, handler)
    management = CloudloopManagement(context())
    things = await management.list_devices()
    assert things == [
        {
            "external_id": "DanGRxQrXpzkPJEgyKnydwYZbqmDagNA",
            "identity_type": "cloudloop_thing",
            "name": None,
            "attributes": {
                "thing_id": "DanGRxQrXpzkPJEgyKnydwYZbqmDagNA",
                "subscriber_sbd": "KXeNzdgDqZwrQBbNoDjBxMLlmoGpaOAR",
                "supports_sbd": True,
                "account_id": "ejoGRxQrXpzkPJngbjBydwYZbqmDagNA",
            },
        }
    ]
    assert (await management.test_connection())["ok"] is True
    with pytest.raises(ApplicationError) as excinfo:
        await CloudloopManagement(context(credentials={})).test_connection()
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED


async def test_refused_token_is_an_auth_failure(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(403, text="denied"))
    with pytest.raises(ApplicationError) as excinfo:
        await CloudloopManagement(context()).test_connection()
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
