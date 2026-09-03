import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.connectivity.adapters.chirpstack import (
    ChirpStackAdapter,
    parse_chirpstack_time,
    parse_event,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.trace import ApplicationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "chirpstack"
APP = "17c82e96-be03-4f38-aef3-f83d48582d97"


def source(config: dict | None = None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="cs",
        adapter_key="chirpstack",
        config=config or {"mqtt_host": "x"},
        credentials={},
        capabilities=AdapterCapabilities(),
    )


def topic(event: str, eui: str = "0101010101010101") -> str:
    return f"application/{APP}/device/{eui}/event/{event}"


def test_nanosecond_time_is_parsed():
    assert parse_chirpstack_time("2022-07-18T09:34:15.775023242+00:00") == datetime(
        2022, 7, 18, 9, 34, 15, 775023, tzinfo=UTC
    )
    assert parse_chirpstack_time("2022-07-18T09:34:15Z") == datetime(
        2022, 7, 18, 9, 34, 15, tzinfo=UTC
    )
    assert parse_chirpstack_time(None) is None


def test_uplink_event():
    message = parse_event(source(), topic("up"), (FIXTURES / "up.json").read_bytes())
    assert message.external_id == "0101010101010101"
    assert message.event_type == "uplink"
    assert message.acquisition_channel == AcquisitionChannel.LORAWAN
    assert message.ingestion_method == IngestionMethod.MQTT
    assert message.network_received_at == datetime(2022, 7, 18, 9, 34, 15, 775023, tzinfo=UTC)
    assert message.provider_metadata["f_port"] == 1 and message.provider_metadata["f_cnt"] == 10
    assert (
        message.provider_metadata["gateway_count"] == 2
        and message.provider_metadata["best_rssi"] == -36
    )
    assert message.provider_metadata["spreading_factor"] == 11
    assert [r.gateway_id for r in message.gateway_receptions] == [
        "0016c001f153a14c",
        "0016c001f153a14d",
    ]
    assert message.gateway_receptions[0].frequency_hz == 867100000
    assert message.identity_attributes["application_id"] == APP
    assert message.identity_attributes["device_name"] == "Test device"
    assert message.payload["data"] == "qg=="


@pytest.mark.parametrize(
    ("fixture", "event_type"),
    [
        ("status", "status"),
        ("join", "join"),
        ("ack", "downlink_ack"),
        ("txack", "downlink_transmitted"),
        ("log", "log"),
    ],
)
def test_other_events_are_normalized(fixture, event_type):
    message = parse_event(source(), topic(fixture), (FIXTURES / f"{fixture}.json").read_bytes())
    assert message.event_type == event_type
    assert message.external_id == "0101010101010101"
    assert message.gateway_receptions == []


def test_bad_payloads():
    with pytest.raises(ApplicationError):
        parse_event(source(), topic("up"), b"nope")
    with pytest.raises(ApplicationError):
        parse_event(source(), topic("up"), b"[1]")


def test_webhook_uses_event_header():
    adapter = ChirpStackAdapter()
    body = json.loads((FIXTURES / "join.json").read_text())
    messages = adapter.parse_webhook(source(), body, {"x-event": "join"})
    assert messages[0].event_type == "join"
    assert adapter.default_capabilities.downlink is True
    assert "OPEN_DEVICE" in adapter.default_link_templates
