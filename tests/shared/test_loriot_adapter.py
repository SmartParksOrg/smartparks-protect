"""LORIOT: websocket frames to messages, gateway receptions, downlink over a tx frame."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.connectivity.adapters import loriot
from shared.connectivity.adapters.loriot import (
    LoriotAdapter,
    LoriotCommands,
    LoriotConnector,
    parse_frame,
    ws_url,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.device_drivers.base import lorawan_frame
from shared.enums import ErrorCode, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "loriot"


def source(config=None, credentials=None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="loriot",
        adapter_key="loriot",
        config=config if config is not None else {"server": "eu1.loriot.io", "app_id": "BE7A0001"},
        credentials=credentials if credentials is not None else {"token": "t0k"},
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def test_rx_frame():
    message = parse_frame(source(), (FIXTURES / "rx.json").read_text())
    assert message is not None and message.event_type == "uplink"
    assert (
        message.external_id == "70B3D57ED0001234"
        and message.ingestion_method == IngestionMethod.WEBSOCKET
    )
    assert message.network_received_at == datetime(2026, 9, 3, 8, 12, 3, 421000, tzinfo=UTC)
    meta = message.provider_metadata
    assert (
        meta["f_port"] == 2
        and meta["f_cnt"] == 1834
        and meta["spreading_factor"] == 9
        and meta["best_rssi"] == -97
    )
    frame, port = lorawan_frame(message.payload, meta)
    assert port == 2 and frame is not None and frame[0] == 0xF2
    assert message.identity_attributes == {"app_id": "BE7A0001"}


def test_gw_frame_carries_receptions():
    message = parse_frame(source(), (FIXTURES / "gw.json").read_text())
    assert message is not None and message.event_type == "gateway_receptions"
    assert [r.gateway_id for r in message.gateway_receptions] == [
        "7276ff0039030123",
        "7276ff0039030456",
    ]
    assert message.gateway_receptions[0].attributes["lat"] == 52.09


def test_txd_frame_and_housekeeping():
    message = parse_frame(source(), (FIXTURES / "txd.json").read_text())
    assert message is not None and message.event_type == "downlink_transmitted"
    assert message.provider_metadata["queue_ref"] == 13
    assert parse_frame(source(), json.dumps({"cmd": "cq", "cache": []})) is None
    with pytest.raises(ApplicationError) as excinfo:
        parse_frame(source(), "not json")
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED


def test_ws_url_and_missing_credentials():
    assert ws_url(source()) == "wss://eu1.loriot.io/app?token=t0k"
    with pytest.raises(ApplicationError) as excinfo:
        ws_url(source(config={}, credentials={}))
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
    assert isinstance(LoriotAdapter().event_connector(source()), LoriotConnector)


def test_webhook_variant():
    body = json.loads((FIXTURES / "rx.json").read_text())
    messages = LoriotAdapter().parse_webhook(source(), [body, {"cmd": "cq"}], {})
    assert len(messages) == 1 and messages[0].ingestion_method == IngestionMethod.WEBHOOK


@pytest.mark.asyncio
async def test_submit_sends_a_tx_frame(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def fake_send_tx(url, frame, wait_seconds=15.0):
        sent.append((url, frame))
        return {"cmd": "tx", "success": True, "seqno": 41}

    monkeypatch.setattr(loriot, "send_tx", fake_send_tx)
    result = await LoriotCommands(source()).submit(
        "70b3d57ed0001234", b"\xa1\x00", {"f_port": 32, "confirmed": True}
    )
    assert result["provider_ref"] == "41" and result["statuses"] == [
        "accepted_by_network",
        "queued",
    ]
    assert sent[0][0].startswith("wss://eu1.loriot.io/app?token=")
    assert sent[0][1] == {
        "cmd": "tx",
        "EUI": "70B3D57ED0001234",
        "port": 32,
        "confirmed": True,
        "data": "A100",
    }


@pytest.mark.asyncio
async def test_submit_failures(monkeypatch):
    async def rejected(url, frame, wait_seconds=15.0):
        return {"cmd": "tx", "success": False, "error": "device not found"}

    monkeypatch.setattr(loriot, "send_tx", rejected)
    with pytest.raises(ApplicationError) as excinfo:
        await LoriotCommands(source()).submit("AA", b"\x00", {"f_port": 1})
    assert excinfo.value.code == ErrorCode.COMMAND_REJECTED

    async def down(url, frame, wait_seconds=15.0):
        raise TimeoutError("no answer")

    monkeypatch.setattr(loriot, "send_tx", down)
    with pytest.raises(ApplicationError) as unavailable:
        await LoriotCommands(source()).submit("AA", b"\x00", {"f_port": 1})
    assert (
        unavailable.value.code == ErrorCode.CONNECTIVITY_UNAVAILABLE and unavailable.value.retryable
    )
