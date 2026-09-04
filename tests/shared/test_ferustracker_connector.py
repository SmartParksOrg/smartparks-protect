"""The FerusTracker connector (decision D89): the flow's document, decoder field names per
payload family, and the unauthenticated post."""

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.integrations.base import DeliveryItem, IntegrationContext, PermanentFailure, Skipped
from shared.integrations.connectors.ferustracker import FerusTrackerConnector
from shared.integrations.registry import CONNECTORS

pytestmark = pytest.mark.asyncio


def integration(**config):
    return IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="FerusTracker",
        connector_key="ferustracker",
        config={
            "site": "Kempen-Broek",
            "payload_types": {"opencollar": "opencollar_edge_6"},
            **config,
        },
        credentials={},
    )


def item(object_type="position", **overrides):
    base = DeliveryItem(
        object_type=object_type,
        object_id="9",
        object_version=1,
        time=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        project_id=uuid.uuid4(),
        project_name="Kempen-Broek",
        project_slug="kempen",
        entity_id=uuid.UUID(int=7),
        entity_name="Konik 3",
        device_name="SP05-003",
        device_serial="SN-003",
        device_type_key="opencollar",
        device_identity="70B3D57ED0001234",
        location=(51.2, 5.7),
        data={"altitude_m": 34.5, "satellites": 9, "accuracy_m": 4.2},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_registered():
    assert CONNECTORS["ferustracker"].supports == {"position", "measurement"}


def test_render_edge_documents_like_the_flow():
    connector = FerusTrackerConnector()
    rendered = connector.render(integration(), item())
    assert rendered["url"] == "https://ferustracker.nl/api/smartparks"
    body = rendered["body"]
    assert body["devEUI"] == body["deviceName"] == "70B3D57ED0001234"
    assert body["fPort"] == 2 and body["tags"] == {
        "payloadType": "opencollar_edge_6",
        "subType": "",
    }
    assert body["provider"] == "kpn" and body["site"] == "Kempen-Broek"
    assert body["time"] == "2026-09-04T10:00:00+00:00"
    fields = json.loads(body["objectJSON"])
    assert fields == {
        "latitude": 51.2,
        "longitude": 5.7,
        "fix_timestamp": int(datetime(2026, 9, 4, 10, 0, tzinfo=UTC).timestamp()),
        "altitude": 34.5,
        "SIV": 9,
        "h_acc_est": 4.2,
    }
    battery = connector.render(
        integration(), item("measurement", data={"metric_key": "battery_voltage", "value": 3.71})
    )
    assert battery["body"]["fPort"] == 4 and json.loads(battery["body"]["objectJSON"]) == {
        "bat": 3710
    }
    temperature = connector.render(
        integration(), item("measurement", data={"metric_key": "device_temperature", "value": 21.5})
    )
    assert json.loads(temperature["body"]["objectJSON"]) == {"temp": 21.5}
    with pytest.raises(Skipped):
        connector.render(
            integration(), item("measurement", data={"metric_key": "rssi", "value": -90})
        )
    with pytest.raises(Skipped):
        connector.render(integration(), item("event", data={"event_type": "GEOFENCE_EXIT"}))
    with pytest.raises(Skipped):
        connector.render(integration(), item(device_identity=None, device_serial=None))


def test_render_v2_documents_and_default_payload_type():
    connector = FerusTrackerConnector()
    v2 = integration(payload_types={"opencollar": "opencollar_v2"}, site="")
    body = connector.render(v2, item())["body"]
    assert body["fPort"] == 1 and "site" not in body
    assert json.loads(body["objectJSON"]) == {
        "latitude": 51.2,
        "longitude": 5.7,
        "gps_time": int(datetime(2026, 9, 4, 10, 0, tzinfo=UTC).timestamp()),
        "alt": 34.5,
        "satellites": 9,
    }
    status = connector.render(
        v2, item("measurement", data={"metric_key": "battery_voltage", "value": 3.5})
    )["body"]
    assert status["fPort"] == 12 and json.loads(status["objectJSON"]) == {"battery": 3500}
    unmapped = connector.render(
        integration(default_payload_type="opencollar_edge_4"), item(device_type_key="other")
    )
    assert unmapped["body"]["tags"]["payloadType"] == "opencollar_edge_4"


async def test_deliver_posts_without_authentication(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.headers.get("authorization")))
        if request.method == "GET":
            return httpx.Response(405, text="Method Not Allowed")
        return httpx.Response(200, text="OK")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )
    connector = FerusTrackerConnector()
    result = await connector.deliver(integration(), item(), connector.render(integration(), item()))
    assert result.response["status"] == 200 and calls[0] == (
        "POST",
        "https://ferustracker.nl/api/smartparks",
        None,
    )
    answer = await connector.test(integration(), None)
    assert answer["reachable"] is True and answer["status"] == 405

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="unknown device")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(failing), **k)
    )
    with pytest.raises(PermanentFailure, match="unknown device"):
        await connector.deliver(integration(), item(), connector.render(integration(), item()))
