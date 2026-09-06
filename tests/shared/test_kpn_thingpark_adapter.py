"""KPN/ThingPark: uplink and downlink status parsing, the push Token (D95), the downlink token
and CorrelationID, the connector."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.connectivity.adapters.kpn_thingpark import (
    KPN_DOWNLINK_URL,
    KpnThingParkAdapter,
    ThingParkCommands,
    correlation_id,
    downlink_token,
    parse_event,
    push_token,
    verify_push,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.registry import ADAPTERS, describe_adapter
from shared.connectivity.transports.http import raw_query_params
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


def example(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_uplink_event():
    body = example("uplink.json")
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


def test_best_gateway_gets_the_coordinates_thingpark_gives():
    """LrrLAT and LrrLON belong to the top-level Lrrid; the registry reads `location`."""
    message = parse_event(source(), example("kpn_uplink_hookbin_2016.json")["body"])
    by_id = {r.gateway_id: r for r in message.gateway_receptions}
    assert by_id["080603db"].attributes["location"] == {
        "latitude": 52.069241,
        "longitude": 4.349416,
    }
    assert "location" not in by_id["080e00c8"].attributes
    assert message.provider_metadata["frame_hex"] == "00277c0878fd9b2e000000000000ffff"
    assert "name" not in message.identity_attributes  # that capture carries no CustomerData.name
    live = parse_event(source(), example("kpn_live_uplink_port13.json"))
    assert live.identity_attributes["name"] == "SP051195"


def test_numeric_fields_of_newer_thingpark_versions_parse():
    """ThingPark Wireless sends strings, newer versions numbers; both must read the same."""
    message = parse_event(source(), example("actility_uplink_with_token.json")["body"])
    meta = message.provider_metadata
    assert meta["f_port"] == 17 and meta["f_cnt"] == 18 and meta["best_rssi"] == -67.0
    assert message.gateway_receptions[0].attributes["location"]["latitude"] == 47.438381


def test_downlink_sent_event():
    message = parse_event(source(), example("downlink_sent.json"))
    assert message.event_type == "downlink_transmitted"
    assert message.provider_metadata["queue_ref"] == "5F3E4D2C-0000-1111-2222-333344445555"
    assert message.provider_metadata["delivery_status"] == 1


def test_live_downlink_sent_report_moves_the_command_and_explains_the_slot():
    """The report KPN posted for the first downlink through the dev server (2026-09-06): sent
    (DeliveryStatus 1) on RX2, with C0 on RX1 explaining why."""
    message = parse_event(source(), example("kpn_live_downlink_sent.json"))
    meta = message.provider_metadata
    assert message.event_type == "downlink_transmitted"
    assert meta["queue_ref"] == "6CF1BF9A3DBD4821" and meta["delivery_status"] == 1
    assert meta["delivery_causes"] == ["RX1 C0: LRC selected RX2"]
    assert meta["frequency_hz"] == 869_525_000 and meta["f_cnt_down"] == 5
    assert message.network_received_at == datetime(2026, 9, 6, 8, 18, 55, 268000, tzinfo=UTC)


def test_failed_downlink_report_fails_the_command():
    report = example("kpn_live_downlink_sent.json")
    sent = report["DevEUI_downlink_Sent"]
    sent["DeliveryStatus"] = 0
    sent["DeliveryFailedCause1"], sent["DeliveryFailedCause2"] = "E3", "DA"
    message = parse_event(source(), report)
    meta = message.provider_metadata
    # `log` with an ERROR level is what the command path turns into a failed command
    assert message.event_type == "log" and meta["level"] == "ERROR"
    assert meta["queue_ref"] == "6CF1BF9A3DBD4821" and meta["delivery_status"] == 0
    assert meta["description"] == (
        "downlink not sent: RX1 E3: validity time expired; RX2 DA: duty cycle constraint "
        "detected by LRC"
    )


def test_unknown_document_is_rejected():
    with pytest.raises(ApplicationError) as excinfo:
        parse_event(source(), {"Something": {}})
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED


def test_webhook_accepts_a_list():
    body = example("uplink.json")
    messages = KpnThingParkAdapter().parse_webhook(source(), [body, body], {})
    assert len(messages) == 2


@pytest.mark.parametrize(
    "name", ["actility_uplink_with_token.json", "kpn_uplink_hookbin_2016.json"]
)
def test_push_token_matches_the_published_examples(name):
    """Golden tests: Actility's and IoT Academy's published pushes with their keys."""
    fixture = example(name)
    assert (
        push_token(fixture["body"], fixture["query"], fixture["as_key"])
        == fixture["query"]["Token"]
    )
    assert verify_push([fixture["body"]], fixture["query"], fixture["as_key"])
    adapter = KpnThingParkAdapter()
    assert adapter.verify_webhook(
        source(credentials={"as_key": fixture["as_key"]}), fixture["body"], {}, fixture["query"]
    )


def test_push_token_refuses_tampering_and_missing_key():
    fixture = example("actility_uplink_with_token.json")
    body, query, key = fixture["body"], fixture["query"], fixture["as_key"]
    changed = json.loads(json.dumps(body))
    changed["DevEUI_uplink"]["payload_hex"] = "00"
    assert not verify_push([changed], query, key)
    assert not verify_push([body], {**query, "Token": "0" * 64}, key)
    assert not verify_push([body], {**query, "Time": "2021-04-07T08:49:51.551+02:00"}, key)
    assert not verify_push([body], query, "")
    assert not verify_push([body], {k: v for k, v in query.items() if k != "Token"}, key)
    assert not verify_push([body, {"Something": {}}], query, key)
    assert not verify_push([], query, key)
    assert push_token({"Something": {}}, query, key) is None


def test_push_token_per_report_type():
    """Body elements per report from the tunnel interface documentation; a downlink sent report
    hashes CustomerID, DevEUI, FPort and FCntDn, a notification only CustomerID and DevEUI."""
    query = {"LrnDevEui": "FADE55B9F72E2243", "AS_ID": "as", "Time": "2026-09-06T10:00:00.000Z"}
    key = "k"
    sent = {
        "DevEUI_downlink_Sent": {
            "CustomerID": "199906997",
            "DevEUI": "FADE55B9F72E2243",
            "FPort": "8",
            "FCntDn": "1",
        }
    }
    expected = hashlib.sha256(
        (
            "199906997FADE55B9F72E224381"
            + "LrnDevEui=FADE55B9F72E2243&AS_ID=as&Time=2026-09-06T10:00:00.000Z"
            + key
        ).encode()
    ).hexdigest()
    assert push_token(sent, query, key) == expected
    note = {"DevEUI_notification": {"CustomerID": "1", "DevEUI": "AA"}}
    assert push_token(note, {}, key) == hashlib.sha256(b"1AAk").hexdigest()
    # a missing FPort counts as 0, a missing payload as empty
    uplink = {"DevEUI_uplink": {"CustomerID": "1", "DevEUI": "AA", "FCntUp": "5"}}
    assert push_token(uplink, {}, key) == hashlib.sha256(b"1AA05k").hexdigest()


def test_raw_query_keeps_the_plus_of_the_time_offset():
    raw = (
        "LrnDevEui=0059AC000010020D&LrnFPort=2&LrnInfos=TWA_1.1.AS-1-2&AS_ID=hookbin"
        "&Time=2016-07-05T08:58:26.911+02:00&Token=ab"
    )
    params = raw_query_params(raw)
    assert params["Time"] == "2016-07-05T08:58:26.911+02:00" and params["Token"] == "ab"
    encoded = raw.replace(":", "%3A").replace("+", "%2B")
    assert raw_query_params(encoded)["Time"] == "2016-07-05T08:58:26.911+02:00"
    assert raw_query_params("") == {} and raw_query_params("a&b=")["b"] == ""


def test_downlink_token_is_sha256_of_query_and_key():
    query = {"DevEUI": "AA", "FPort": "1", "Payload": "00", "AS_ID": "x", "Time": "t"}
    expected = hashlib.sha256(b"DevEUI=AA&FPort=1&Payload=00&AS_ID=x&Time=tsecret").hexdigest()
    assert downlink_token(query, "secret") == expected


def test_correlation_id_is_64_bits_of_hex():
    command = uuid.UUID("5f3e4d2c-8a9b-4c1d-9e2f-333344445555")
    assert correlation_id(str(command)) == "5F3E4D2C8A9B4C1D"
    other = correlation_id("not-a-uuid")
    assert len(other) == 16 and int(other, 16) >= 0 and other == other.upper()


@pytest.mark.asyncio
async def test_submit_token_mode(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    command = uuid.uuid4()
    result = await ThingParkCommands(source()).submit(
        "70b3d57ed0001234", b"\xa4\x00", {"f_port": 32, "reference": str(command)}
    )
    expected_ref = command.hex[:16].upper()
    assert result["provider_ref"] == expected_ref
    assert result["statuses"] == ["accepted_by_network"]
    params = dict(calls[0].url.params)
    assert (
        params["DevEUI"] == "70B3D57ED0001234"
        and params["FPort"] == "32"
        and params["Payload"] == "A400"
    )
    assert params["AS_ID"] == "TWA_1.1" and len(params["Token"]) == 64
    assert params["CorrelationID"] == expected_ref
    # the token covers the query in ThingPark's order, CorrelationID included
    assert list(params) == ["DevEUI", "FPort", "Payload", "AS_ID", "Time", "CorrelationID", "Token"]
    query = {k: params[k] for k in ("DevEUI", "FPort", "Payload", "AS_ID", "Time", "CorrelationID")}
    assert params["Token"] == downlink_token(query, "secret")
    # the `+` and `:` of Time travel percent-encoded, as Actility's example does
    assert "%2B00%3A00" in str(calls[0].url) and "+" not in str(calls[0].url.query)

    # the sent report ThingPark posts later carries the same id, upper case, as queue_ref
    report = example("downlink_sent.json")
    report["DevEUI_downlink_Sent"]["CorrelationID"] = expected_ref.lower()
    assert parse_event(source(), report).provider_metadata["queue_ref"] == expected_ref


@pytest.mark.asyncio
async def test_submit_uses_kpn_url_by_default_and_reports_refusals(monkeypatch):
    real = httpx.AsyncClient
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(403, text="Security Check. bad AS_ID")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    kpn = ADAPTERS["kpn_thingpark"].command_connector(source({"as_id": "ASIDx"}, {"as_key": "k"}))
    with pytest.raises(ApplicationError) as refused:
        await kpn.submit("AA", b"\x00", {"f_port": 1, "reference": str(uuid.uuid4())})
    assert refused.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
    assert seen["url"] == KPN_DOWNLINK_URL and seen["auth"] == ""


@pytest.mark.asyncio
async def test_submit_needs_as_id_key_and_for_actility_the_url():
    with pytest.raises(ApplicationError) as missing:
        await ThingParkCommands(source({"as_id": ""}, {"as_key": ""}), KPN_DOWNLINK_URL).submit(
            "AA", b"\x00", {"f_port": 1}
        )
    assert missing.value.code == ErrorCode.COMMAND_REJECTED
    assert str(missing.value).endswith("the data source has no as_id and no as_key credential")
    actility = ADAPTERS["actility_thingpark"].command_connector(
        source({"as_id": "x"}, {"as_key": "k"})
    )
    with pytest.raises(ApplicationError) as no_url:
        await actility.submit("AA", b"\x00", {"f_port": 1})
    assert "no downlink_url" in str(no_url.value)


def test_registered_and_described():
    described = describe_adapter(ADAPTERS["kpn_thingpark"])
    assert described["push"] is True and described["can_send_commands"] is True
    assert (
        described["acquisition_channel"] == "lorawan"
        and "downlink_url" in described["config_schema"]["properties"]
    )
    assert list(described["credentials_schema"]) == ["as_key"]
    http = next(c for c in described["channels"] if c["key"] == "http")
    api = next(c for c in described["channels"] if c["key"] == "api")
    assert http["credential_keys"] == ["as_key"] and api["credential_keys"] == []
    assert api["config_keys"] == ["as_id"] and "downlink_url" in api["optional_keys"]
    assert described["config_schema"]["properties"]["downlink_url"]["default"] == KPN_DOWNLINK_URL
    assert "auth_mode" not in described["config_schema"]["properties"]
    actility = describe_adapter(ADAPTERS["actility_thingpark"])
    api = next(c for c in actility["channels"] if c["key"] == "api")
    assert api["config_keys"] == ["as_id", "downlink_url"]
    assert "default" not in actility["config_schema"]["properties"]["downlink_url"]


@pytest.mark.parametrize(
    ("name", "port", "kind"),
    [
        ("kpn_live_uplink_port13.json", 13, "positions"),
        ("kpn_live_uplink_port4.json", 4, "measurements"),
    ],
)
def test_live_kpn_pushes_decode_with_the_opencollar_driver(name, port, kind):
    """The first recorded pushes from Smart Parks' KPN application (2026-09-06): the frame
    reaches the OpenCollar driver and yields a position (port 13) or a status (port 4)."""
    from shared.device_drivers.base import SourceEventData
    from shared.device_drivers.registry import DRIVERS

    message = parse_event(source(), example(name))
    assert message.event_type == "uplink" and message.provider_metadata["f_port"] == port
    assert message.gateway_receptions and all(
        r.rssi is not None and r.snr is not None for r in message.gateway_receptions
    )
    assert any("location" in r.attributes for r in message.gateway_receptions)
    frame, f_port = lorawan_frame(message.payload, message.provider_metadata)
    assert frame and f_port == port
    records = DRIVERS["opencollar"].decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload=message.payload,
            provider_metadata=message.provider_metadata,
            network_received_at=message.network_received_at,
            ingested_at=message.network_received_at,
            device_attributes={},
            device_type_settings={},
            frame=frame,
            f_port=f_port,
            acquisition_channel="lorawan",
        )
    )
    assert getattr(records, kind), records


def test_live_join_notification_is_a_join_event():
    message = parse_event(source(), example("kpn_live_join_notification.json"))
    assert message.event_type == "join"
    assert message.external_id == "0016C001F016D281"
    assert message.provider_metadata["notification_type"] == "join"
    assert message.provider_metadata["dev_addr"] == "14718A79"
    assert message.network_received_at is not None
    assert message.gateway_receptions == []
