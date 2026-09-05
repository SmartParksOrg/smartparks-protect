"""Adapters and drivers are pure: they run without a database."""

import uuid
from datetime import UTC, datetime

import pytest

from shared.connectivity.adapters.generic_http import GenericHttpAdapter
from shared.connectivity.adapters.generic_mqtt import parse_message, topic_pattern
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.registry import ADAPTERS, get_adapter
from shared.device_drivers.base import SourceEventData, canonical_key
from shared.device_drivers.generic_json import GenericJsonDriver
from shared.device_drivers.registry import DRIVERS, get_driver
from shared.enums import ErrorCode, IngestionMethod
from shared.trace import ApplicationError


def context(adapter_key: str, config: dict | None = None) -> DataSourceContext:
    return DataSourceContext(
        id=uuid.uuid4(),
        name="test",
        adapter_key=adapter_key,
        config=config or {},
        credentials={},
        capabilities=AdapterCapabilities(),
    )


def test_registries():
    assert set(ADAPTERS) == {
        "generic_http",
        "generic_mqtt",
        "chirpstack",
        "kpn_thingpark",
        "loriot",
        "netmore",
        "akenza",
        "traccar",
        "addaxai_connect",
        "cloudloop",
        "webble",
        "log_file",
        "tts",
        "actility_thingpark",
        "cra_iot",
    }
    assert set(DRIVERS) == {"generic_json", "opencollar"}
    assert (
        get_adapter("generic_http").key == "generic_http"
        and get_driver("generic_json").key == "generic_json"
    )
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_generic_http_single_and_batch():
    adapter = GenericHttpAdapter()
    single = adapter.parse_webhook(
        context("generic_http"),
        {"device_id": "AA", "type": "status", "received_at": "2026-03-01T00:00:00+00:00", "v": 1},
        {},
    )
    assert len(single) == 1 and single[0].external_id == "AA" and single[0].event_type == "status"
    assert single[0].network_received_at == datetime(2026, 3, 1, tzinfo=UTC)
    assert single[0].ingestion_method == IngestionMethod.WEBHOOK
    batch = adapter.parse_webhook(
        context("generic_http", {"batch_field": "items", "external_id_field": "meta.eui"}),
        {"items": [{"meta": {"eui": "1"}, "v": 1}, {"meta": {"eui": "2"}, "v": 2}]},
        {},
    )
    assert [m.external_id for m in batch] == ["1", "2"]
    with pytest.raises(ApplicationError):
        adapter.parse_webhook(context("generic_http"), [1, 2], {})


def test_generic_mqtt_topic_and_payload_identity():
    assert (
        topic_pattern("devices/{external_id}/up").match("devices/ABC/up").group("external_id")
        == "ABC"
    )
    source = context("generic_mqtt", {"topic_template": "sp/{external_id}/+"})
    message = parse_message(source, "sp/DEV1/data", b'{"lat": 1, "lon": 2}')
    assert message.external_id == "DEV1" and message.ingestion_method == IngestionMethod.MQTT
    source = context("generic_mqtt", {"external_id_from": "payload", "external_id_field": "id"})
    assert parse_message(source, "any/topic", b'{"id": "X9"}').external_id == "X9"
    with pytest.raises(ApplicationError) as excinfo:
        parse_message(source, "t", b"not json")
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED


def _event(payload: dict, network_received_at: datetime | None = None) -> SourceEventData:
    return SourceEventData(
        id=1,
        event_type="uplink",
        payload=payload,
        provider_metadata={},
        network_received_at=network_received_at,
        ingested_at=datetime(2026, 3, 1, 12, tzinfo=UTC),
        device_attributes={},
        device_type_settings={},
    )


def test_generic_json_driver_decodes():
    records = GenericJsonDriver().decode(
        _event(
            {
                "time": 1772366400,
                "latitude": -24.9,
                "longitude": 31.5,
                "measurements": {"battery_voltage": 3.9},
                "state": {"a": 1},
                "events": [{"type": "x"}],
            }
        )
    )
    assert records.positions[0].time == datetime.fromtimestamp(1772366400, tz=UTC)
    assert (
        records.measurements[0].metric_key == "battery_voltage"
        and records.states
        and records.events
    )
    empty = GenericJsonDriver().decode(
        _event({"note": "nothing"}, network_received_at=datetime(2026, 3, 1, tzinfo=UTC))
    )
    assert empty.empty


def test_generic_json_driver_errors():
    with pytest.raises(ApplicationError) as excinfo:
        GenericJsonDriver().decode(
            _event({"time": "2026-03-01T00:00:00", "lat": 1, "lon": 2})
        )  # naive
    assert excinfo.value.code == ErrorCode.TIMESTAMP_INVALID
    with pytest.raises(ApplicationError) as excinfo:
        GenericJsonDriver().decode(_event({"lat": "north", "lon": 2}))
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED


def test_canonical_key_is_stable_across_offsets():
    device = uuid.uuid4()
    a = canonical_key(device, datetime(2026, 3, 1, 12, tzinfo=UTC), "gnss")
    from datetime import timedelta, timezone

    b = canonical_key(device, datetime(2026, 3, 1, 14, tzinfo=timezone(timedelta(hours=2))), "gnss")
    assert a == b
    assert (
        canonical_key(
            device, datetime(2026, 3, 1, 12, tzinfo=UTC), "measurement", "battery_voltage"
        )
        != a
    )


def test_generic_json_driver_prefers_the_lorawan_frame():
    import base64
    import json

    frame = json.dumps({"time": "2026-03-01T00:00:00+00:00", "lat": -24.9, "lon": 31.5}).encode()
    event = SourceEventData(
        id=1,
        event_type="uplink",
        payload={"data": base64.b64encode(frame).decode(), "fPort": 1},
        provider_metadata={"f_port": 1},
        network_received_at=None,
        ingested_at=datetime(2026, 3, 1, 12, tzinfo=UTC),
        device_attributes={},
        device_type_settings={},
        frame=frame,
        f_port=1,
    )
    records = GenericJsonDriver().decode(event)
    assert records.positions[0].latitude == -24.9


def test_lorawan_frame_extraction():
    import base64

    from shared.device_drivers.base import lorawan_frame

    payload = {"data": base64.b64encode(b"\x01\x02").decode(), "fPort": 13}
    assert lorawan_frame(payload, {}) == (b"\x01\x02", 13)
    assert lorawan_frame(payload, {"f_port": 7}) == (b"\x01\x02", 7)
    assert lorawan_frame({}, {"frame_hex": "0a0b", "f_port": 2}) == (b"\x0a\x0b", 2)
    assert lorawan_frame({"data": "not base64!!"}, {}) == (None, None)


def test_chirpstack_without_a_broker_runs_no_connector():
    """An existing ChirpStack can deliver through its HTTP integration alone."""
    import uuid

    from shared.connectivity.base import AdapterCapabilities, DataSourceContext

    def source(config: dict) -> DataSourceContext:
        return DataSourceContext(
            id=uuid.uuid4(),
            name="cs",
            adapter_key="chirpstack",
            config=config,
            credentials={},
            capabilities=AdapterCapabilities(uplink=True),
        )

    adapter = ADAPTERS["chirpstack"]
    assert adapter.event_connector(source({"web_url": "https://cs.example"})) is None
    assert adapter.event_connector(source({"mqtt_host": "mq.example"})) is not None


def test_channel_keys_per_adapter():
    from shared.connectivity.channels import (
        api_channel_key,
        channel_enabled,
        stream_channel_key,
        webhook_channel_key,
    )

    assert (
        stream_channel_key("chirpstack") == "mqtt" and webhook_channel_key("chirpstack") == "http"
    )
    assert api_channel_key("chirpstack") == "api" and stream_channel_key("generic_http") is None
    assert (
        stream_channel_key("loriot") == "stream" and stream_channel_key("addaxai_connect") == "poll"
    )
    assert channel_enabled({}, "http") and channel_enabled(None, None)
    assert not channel_enabled({"http": False}, "http") and channel_enabled({"http": False}, "api")
