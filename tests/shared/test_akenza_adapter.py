"""akenza: the webhook sample, identity by akenza id, the REST downlink."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.akenza import AkenzaAdapter, AkenzaCommands, parse_sample
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.registry import ADAPTERS, describe_adapter
from shared.device_drivers.base import lorawan_frame
from shared.enums import ErrorCode, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "akenza"


def source(config=None, credentials=None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="akenza",
        adapter_key="akenza",
        config=config if config is not None else {"workspace_id": "ws1"},
        credentials=credentials if credentials is not None else {"api_key": "k3y"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def test_webhook_sample():
    body = json.loads((FIXTURES / "uplink.json").read_text())
    messages = AkenzaAdapter().parse_webhook(source(), body, {})
    assert len(messages) == 1
    m = messages[0]
    assert m.external_id == "0000000000000fff" and m.identity_type == "akenza_device_id"
    assert (
        m.identity_attributes["dev_eui"] == "70B3D57ED0001234"
        and m.identity_attributes["name"] == "Rhino 14 collar"
    )
    assert m.identity_attributes["workspace_id"] == "ws1"
    assert m.event_type == "uplink" and m.ingestion_method == IngestionMethod.WEBHOOK
    assert m.network_received_at == datetime(2026, 9, 4, 12, 43, 46, 83000, tzinfo=UTC)
    meta = m.provider_metadata
    assert (
        meta["f_port"] == 2
        and meta["f_cnt"] == 4325
        and meta["spreading_factor"] == 7
        and meta["best_rssi"] == -114.0
    )
    frame, port = lorawan_frame(m.payload, meta)
    assert port == 2 and frame is not None and frame[0] == 0xF2 and len(frame) == 32


def test_decoded_sample_is_refused():
    with pytest.raises(ApplicationError) as excinfo:
        parse_sample(
            source(), {"data": {"temperature": 21.5}, "device": {"id": "x"}, "topic": "climate"}
        )
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED and excinfo.value.user_actionable


@pytest.mark.asyncio
async def test_downlink_body_and_headers(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "dl-1"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    result = await AkenzaCommands(source()).submit(
        "0000000000000fff", b"\xa4\x00", {"f_port": 32, "confirmed": True}
    )
    assert result["provider_ref"] == "dl-1" and result["statuses"] == ["accepted_by_network"]
    request = calls[0]
    assert (
        request.url.path == "/v3/devices/0000000000000fff/downlink"
        and request.headers["x-api-key"] == "k3y"
    )
    assert json.loads(request.content) == {
        "raw": True,
        "loraDownlink": {"port": 32, "payloadHex": "a400", "confirmed": True},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "code"),
    [
        (401, ErrorCode.CONNECTIVITY_AUTH_FAILED),
        (404, ErrorCode.DEVICE_NOT_FOUND),
        (400, ErrorCode.COMMAND_REJECTED),
        (503, ErrorCode.CONNECTIVITY_UNAVAILABLE),
    ],
)
async def test_downlink_errors(monkeypatch, status_code, code):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(status_code, text="no")), **kw
        ),
    )
    with pytest.raises(ApplicationError) as excinfo:
        await AkenzaCommands(source()).submit("x", b"\x00", {"f_port": 1})
    assert excinfo.value.code == code


@pytest.mark.asyncio
async def test_missing_api_key():
    with pytest.raises(ApplicationError):
        await AkenzaCommands(source(credentials={})).submit("x", b"\x00", {"f_port": 1})


def test_registered():
    described = describe_adapter(ADAPTERS["akenza"])
    assert described["push"] is True and described["can_send_commands"] is True
    assert described["default_capabilities"]["gateway_metadata"] is False
