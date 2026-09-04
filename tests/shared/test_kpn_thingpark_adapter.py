"""KPN/ThingPark: uplink and downlink status parsing, the downlink token, the connector."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.kpn_thingpark import (
    KpnThingParkAdapter,
    ThingParkCommands,
    downlink_token,
    parse_event,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.registry import ADAPTERS, describe_adapter
from shared.device_drivers.base import lorawan_frame
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "kpn_thingpark"


def source(config=None, credentials=None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="kpn",
        adapter_key="kpn_thingpark",
        config=config
        or {"downlink_url": "https://lrc.example/thingpark/lrc/rest/downlink", "as_id": "TWA_1.1"},
        credentials=credentials or {"as_key": "secret"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def test_uplink_event():
    body = json.loads((FIXTURES / "uplink.json").read_text())
    message = parse_event(source(), body)
    assert message.external_id == "70B3D57ED0001234" and message.event_type == "uplink"
    assert message.acquisition_channel == AcquisitionChannel.LORAWAN
    assert message.ingestion_method == IngestionMethod.WEBHOOK
    assert message.network_received_at == datetime(2026, 9, 4, 8, 12, 3, 421000, tzinfo=UTC)
    meta = message.provider_metadata
    assert meta["f_port"] == 2 and meta["f_cnt"] == 1834 and meta["spreading_factor"] == 9
    assert meta["best_rssi"] == -97.0 and meta["gateway_count"] == 2
    assert [r.gateway_id for r in message.gateway_receptions] == ["ff010a2b", "ff010c71"]
    assert message.gateway_receptions[1].snr == -2.5
    frame, port = lorawan_frame(message.payload, meta)
    assert port == 2 and frame is not None and frame[0] == 0xF2 and len(frame) == 32
    assert message.identity_attributes["customer_id"] == "100000123"


def test_downlink_sent_event():
    body = json.loads((FIXTURES / "downlink_sent.json").read_text())
    message = parse_event(source(), body)
    assert message.event_type == "downlink_transmitted"
    assert message.provider_metadata["queue_ref"] == "5f3e4d2c-0000-1111-2222-333344445555"
    assert message.provider_metadata["delivery_status"] == "1"


def test_unknown_document_is_rejected():
    with pytest.raises(ApplicationError) as excinfo:
        parse_event(source(), {"Something": {}})
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED


def test_webhook_accepts_a_list():
    body = json.loads((FIXTURES / "uplink.json").read_text())
    messages = KpnThingParkAdapter().parse_webhook(source(), [body, body], {})
    assert len(messages) == 2


def test_downlink_token_is_sha256_of_query_and_key():
    query = {"DevEUI": "AA", "FPort": "1", "Payload": "00", "AS_ID": "x", "Time": "t"}
    import hashlib

    expected = hashlib.sha256(b"DevEUI=AA&FPort=1&Payload=00&AS_ID=x&Time=tsecret").hexdigest()
    assert downlink_token(query, "secret") == expected


@pytest.mark.asyncio
async def test_submit_token_mode(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"CorrelationID": "corr-1"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    result = await ThingParkCommands(source()).submit(
        "70b3d57ed0001234", b"\xa4\x00", {"f_port": 32}
    )
    assert result["provider_ref"] == "corr-1" and result["statuses"] == ["accepted_by_network"]
    params = dict(calls[0].url.params)
    assert (
        params["DevEUI"] == "70B3D57ED0001234"
        and params["FPort"] == "32"
        and params["Payload"] == "A400"
    )
    assert params["AS_ID"] == "TWA_1.1" and len(params["Token"]) == 64
    query = {k: params[k] for k in ("DevEUI", "FPort", "Payload", "AS_ID", "Time")}
    assert params["Token"] == downlink_token(query, "secret")


@pytest.mark.asyncio
async def test_submit_bearer_mode_and_errors(monkeypatch):
    real = httpx.AsyncClient
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(403, text="forbidden")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    connector = ThingParkCommands(
        source({"downlink_url": "https://x/dl", "auth_mode": "bearer"}, {"api_token": "tok"})
    )
    with pytest.raises(ApplicationError) as excinfo:
        await connector.submit("AA", b"\x00", {"f_port": 1})
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED and seen["auth"] == "Bearer tok"
    with pytest.raises(ApplicationError) as missing:
        await ThingParkCommands(source({"auth_mode": "bearer"}, {})).submit(
            "AA", b"\x00", {"f_port": 1}
        )
    assert missing.value.code == ErrorCode.COMMAND_REJECTED


def test_registered_and_described():
    described = describe_adapter(ADAPTERS["kpn_thingpark"])
    assert described["push"] is True and described["can_send_commands"] is True
    assert (
        described["acquisition_channel"] == "lorawan"
        and "downlink_url" in described["config_schema"]["properties"]
    )
    assert described["credentials_schema"]["as_key"]
