"""Rock7 RockBLOCK adapter (decision D156) against the documented delivery fields and the MT
endpoint's answers (https://docs.groundcontrol.com/iot/rockblock/web-services, 2026-09-09)."""

from datetime import UTC, datetime

import httpx
import pytest

from shared.connectivity.adapters.rock7 import (
    Rock7Adapter,
    Rock7Commands,
    Rock7Management,
    parse_message,
    parse_mt_response,
    transmit_time,
)
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.trace import ApplicationError
from tests.shared.test_adapters_and_drivers import context as base_context

pytestmark = pytest.mark.asyncio

# The example of the "Receiving MO messages via HTTP Webhook" page: "Hello World RockBLOCK".
DELIVERY = {
    "imei": "300234010753370",
    "serial": "12345",
    "momsn": "12345",
    "transmit_time": "21-10-31 10:41:50",
    "iridium_latitude": "52.3867",
    "iridium_longitude": "0.2938",
    "iridium_cep": "8",
    "data": "48656c6c6f20576f726c6420526f636b424c4f434b",
}


def context(**overrides):
    base = base_context("rock7")
    return DataSourceContext(
        id=base.id,
        name=base.name,
        adapter_key="rock7",
        config=overrides.get("config", {}),
        credentials=overrides.get("credentials", {"username": "mrsmith", "password": "abc1234"}),
        capabilities=AdapterCapabilities(uplink=True, downlink=True),
    )


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_transmit_time_is_the_documented_form_or_iso():
    assert transmit_time("21-10-31 10:41:50") == datetime(2021, 10, 31, 10, 41, 50, tzinfo=UTC)
    assert transmit_time("2023-10-18T15:22:09Z") == datetime(2023, 10, 18, 15, 22, 9, tzinfo=UTC)
    assert transmit_time("") is None and transmit_time("yesterday") is None


async def test_delivery_becomes_an_iridium_uplink_with_the_payload_untouched():
    message = parse_message(DELIVERY)
    assert message.external_id == "300234010753370"
    assert message.identity_type == "imei"
    assert message.event_type == "uplink"
    assert message.acquisition_channel is AcquisitionChannel.IRIDIUM
    assert message.ingestion_method is IngestionMethod.WEBHOOK
    assert bytes.fromhex(message.payload["data_hex"]) == b"Hello World RockBLOCK"
    assert message.satellite_delivered_at == datetime(2021, 10, 31, 10, 41, 50, tzinfo=UTC)
    assert message.provider_metadata["momsn"] == "12345"
    assert message.provider_metadata["iridium_location"] == {
        "latitude": 52.3867,
        "longitude": 0.2938,
        "cep_km": 8.0,
    }
    assert message.identity_attributes == {"serial": "12345"}
    session = parse_message({"imei": "300234010753370", "momsn": "1", "data": ""})
    assert session.event_type == "sbd_session" and "data_hex" not in session.payload
    with pytest.raises(ApplicationError):
        parse_message({"momsn": "1"})
    with pytest.raises(ApplicationError):
        parse_message({"imei": "300234010753370", "data": "zz"})
    assert Rock7Adapter().parse_webhook(context(), DELIVERY, {})[0].external_id == (
        "300234010753370"
    )


def test_mt_answers_are_read_by_code():
    assert parse_mt_response("OK,1234567\n") == "1234567"
    with pytest.raises(ApplicationError) as auth:
        parse_mt_response("FAILED,10,Invalid login credentials")
    assert auth.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
    with pytest.raises(ApplicationError) as credit:
        parse_mt_response("FAILED,13,Insufficient credit")
    assert credit.value.code == ErrorCode.COMMAND_REJECTED and "credit" in credit.value.message
    with pytest.raises(ApplicationError) as outage:
        parse_mt_response("FAILED,99,System error")
    assert outage.value.code == ErrorCode.CONNECTIVITY_UNAVAILABLE and outage.value.retryable
    with pytest.raises(ApplicationError):
        parse_mt_response("<html>nope</html>")


async def test_command_posts_the_satellite_frame_with_the_login(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), dict(httpx.QueryParams(request.content.decode()))))
        return httpx.Response(200, text="OK,987654")

    _mock_client(monkeypatch, handler)
    result = await Rock7Commands(context()).submit(
        "300234010753370", bytes.fromhex("0301aa"), {"f_port": 2, "flush": True}
    )
    assert result["provider_ref"] == "987654"
    assert result["statuses"] == ["accepted_by_network", "queued"]
    assert calls == [
        (
            "https://rockblock.rock7.com/rockblock/MT",
            {
                "imei": "300234010753370",
                "username": "mrsmith",
                "password": "abc1234",
                "data": "020301aa",
                "flush": "yes",
            },
        )
    ]
    with pytest.raises(ApplicationError) as too_long:
        await Rock7Commands(context()).submit("300234010753370", bytes(270), {"f_port": 2})
    assert too_long.value.code == ErrorCode.COMMAND_REJECTED
    with pytest.raises(ApplicationError) as no_login:
        await Rock7Commands(context(credentials={})).submit("3", b"\x01", {"f_port": 2})
    assert no_login.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED


async def test_connection_probe_reads_the_login_from_the_failure_code(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        fields = dict(httpx.QueryParams(request.content.decode()))
        seen.append(fields)
        if fields["password"] == "wrong":
            return httpx.Response(200, text="FAILED,10,Invalid login credentials")
        return httpx.Response(200, text="FAILED,16,No data")

    _mock_client(monkeypatch, handler)
    assert (await Rock7Management(context()).test_connection())["ok"] is True
    assert seen[0]["imei"] == "000000000000000" and seen[0]["data"] == ""
    with pytest.raises(ApplicationError) as excinfo:
        await Rock7Management(
            context(credentials={"username": "mrsmith", "password": "wrong"})
        ).test_connection()
    assert excinfo.value.code == ErrorCode.CONNECTIVITY_AUTH_FAILED
