"""The connectors: Gundi payloads and client, signed webhooks, MQTT topics."""

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.integrations.base import (
    DeliveryItem,
    IntegrationContext,
    PermanentFailure,
    Skipped,
    TransientFailure,
)
from shared.integrations.connectors import gundi, mqtt, webhook
from shared.integrations.registry import CONNECTORS, describe_connector, get_connector

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 5, 1, 12, tzinfo=UTC)
ENTITY = uuid.uuid4()
DEVICE = uuid.uuid4()
PROJECT = uuid.uuid4()


def _context(key, config=None, credentials=None):
    return IntegrationContext(
        id=uuid.uuid4(),
        project_id=PROJECT,
        name="Ops",
        connector_key=key,
        config=config or {},
        credentials=credentials or {},
    )


def _position():
    return DeliveryItem(
        object_type="position",
        object_id="42",
        object_version=1,
        time=T0,
        project_id=PROJECT,
        project_name="Demo park",
        project_slug="demo-park",
        entity_id=ENTITY,
        entity_name="Rhino 14",
        entity_type_key="rhino",
        device_id=DEVICE,
        device_name="SP05",
        data_source_name="Local ChirpStack",
        location=(-24.9, 31.5),
        data={"speed_mps": 1.5, "altitude_m": None, "attributes": {}},
        link="http://localhost:3000/projects/x/devices/y",
    )


def _event(location=(-24.9, 31.5)):
    return DeliveryItem(
        object_type="event",
        object_id=str(uuid.uuid4()),
        object_version=1,
        time=T0,
        project_id=PROJECT,
        project_name="Demo park",
        project_slug="demo-park",
        entity_id=ENTITY,
        entity_name="Rhino 14",
        entity_type_key="rhino",
        device_name="SP05",
        location=location,
        location_is_fallback=True,
        data={
            "event_type": "GEOFENCE_EXIT",
            "severity": "warning",
            "title": "Rhino 14 left Core zone",
            "description": None,
        },
        link="http://localhost:3000/projects/x/rules/events?event=y",
    )


def _mock(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handler))
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_registry_describes_connectors():
    assert set(CONNECTORS) >= {"gundi", "webhook", "mqtt"}
    described = describe_connector(get_connector("gundi"))
    assert described["supports"] == ["event", "position"]
    assert "api_key" in described["credentials_schema"]
    with pytest.raises(KeyError):
        get_connector("nope")


def test_gundi_observation_uses_the_entity_as_source():
    context = _context("gundi", {"subject_types": {"rhino": "black_rhino"}})
    body = gundi.build_observation(context, _position())
    assert body["source"] == str(ENTITY) and body["source_name"] == "Rhino 14"
    assert body["subject_type"] == "black_rhino"
    assert body["recorded_at"] == "2026-05-01T12:00:00+00:00"
    assert body["location"] == {"lat": -24.9, "lon": 31.5}
    assert body["additional"]["device_name"] == "SP05" and body["additional"]["speed_mps"] == 1.5
    assert "altitude_m" not in body["additional"]
    unmapped = gundi.build_observation(_context("gundi"), _position())
    assert unmapped["subject_type"] == gundi.DEFAULT_SUBJECT_TYPE
    device_only = _position()
    device_only.entity_id = None
    with pytest.raises(Skipped):
        gundi.build_observation(context, device_only)
    nowhere = _position()
    nowhere.location = None
    with pytest.raises(Skipped):
        gundi.build_observation(context, nowhere)


def test_gundi_event_namespace_and_mapping():
    context = _context("gundi", {"event_types": {"GEOFENCE_EXIT": "smartparks_protect_geofence"}})
    body = gundi.build_event(context, _event())
    assert body["event_type"] == "smartparks_protect_geofence"
    assert body["title"] == "Rhino 14 left Core zone"
    details = body["event_details"]
    assert details["smartparks_protect_severity"] == "warning"
    assert details["smartparks_protect_entity"] == "Rhino 14"
    assert details["smartparks_protect_location_note"] == "entity's last known position"
    assert "smartparks_protect_description" not in details
    assert gundi.build_event(_context("gundi"), _event())["event_type"] == gundi.DEFAULT_EVENT_TYPE
    with pytest.raises(Skipped):
        gundi.build_event(context, _event(location=None))
    test_event = gundi.build_test_event(context, (1.0, 2.0))
    assert test_event["source"] == gundi.TEST_SOURCE and test_event["location"] == {
        "lat": 1.0,
        "lon": 2.0,
    }


async def test_gundi_client_and_connector(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("apikey"), json.loads(request.content)))
        if request.headers.get("apikey") == "bad":
            return httpx.Response(403, json={"detail": "nope"})
        if request.url.path.endswith("/observations/"):
            return httpx.Response(200, json={"object_id": "obs-1", "created_at": "x"})
        return httpx.Response(200, json=[{"object_id": "evt-1", "created_at": "x"}])

    _mock(monkeypatch, handler)
    connector = get_connector("gundi")
    context = _context("gundi", credentials={"api_key": "k"})
    payload = connector.render(context, _position())
    assert payload["endpoint"] == "/observations/"
    result = await connector.deliver(context, _position(), payload)
    assert result.external_id == "obs-1" and result.response["status"] == 200
    assert calls[0][0] == "/v2/observations/" and calls[0][1] == "k"
    result = await connector.deliver(context, _event(), connector.render(context, _event()))
    assert result.external_id == "evt-1"
    with pytest.raises(Skipped):
        connector.render(
            context,
            DeliveryItem(
                object_type="measurement",
                object_id="1",
                object_version=1,
                time=T0,
                project_id=PROJECT,
                project_name="p",
                project_slug="p",
            ),
        )
    with pytest.raises(PermanentFailure):
        await connector.deliver(
            _context("gundi", credentials={"api_key": "bad"}), _position(), payload
        )
    with pytest.raises(PermanentFailure):
        await connector.test(context, None)
    assert (await connector.test(context, (1.0, 2.0)))["status"] == 200
    with pytest.raises(PermanentFailure):
        gundi.GundiClient("")


async def test_gundi_transient_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events/"):
            raise httpx.ConnectError("down")
        return httpx.Response(503, text="maintenance")

    _mock(monkeypatch, handler)
    client = gundi.GundiClient("k")
    with pytest.raises(TransientFailure):
        await client.post("/observations/", {})
    with pytest.raises(TransientFailure):
        await client.post("/events/", {})


async def test_webhook_signs_and_classifies(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/down":
            return httpx.Response(502, text="bad gateway")
        if request.url.path == "/refuse":
            return httpx.Response(400, text="no")
        return httpx.Response(200, json={"received": True})

    _mock(monkeypatch, handler)
    connector = get_connector("webhook")
    context = _context(
        "webhook",
        {"url": "https://example.org/ok", "headers": {"X-Api-Key": "abc"}},
        {"secret": "s3cret"},
    )
    payload = connector.render(context, _position())
    assert payload["type"] == "position" and payload["object"]["latitude"] == -24.9
    assert payload["entity"]["name"] == "Rhino 14" and payload["device"]["name"] == "SP05"
    result = await connector.deliver(context, _position(), {**payload, "delivery_id": "d-1"})
    assert result.response["status"] == 200
    request = seen[-1]
    body = request.content
    assert request.headers["X-Protect-Signature"] == webhook.sign("s3cret", body)
    assert request.headers["X-Protect-Delivery"] == "d-1" and request.headers["X-Api-Key"] == "abc"
    assert json.loads(body)["delivery_id"] == "d-1"
    with pytest.raises(TransientFailure):
        await connector.deliver(
            _context("webhook", {"url": "https://example.org/down"}), _position(), payload
        )
    with pytest.raises(PermanentFailure):
        await connector.deliver(
            _context("webhook", {"url": "https://example.org/refuse"}), _position(), payload
        )
    with pytest.raises(PermanentFailure):
        await connector.deliver(_context("webhook", {"url": "ftp://x"}), _position(), payload)
    assert (await connector.test(context, (1.0, 2.0)))["status"] == 200


def test_mqtt_topics():
    context = _context("mqtt", {"topic_prefix": "/parks/"})
    assert mqtt.topic_for(context, _position()) == f"parks/demo-park/position/{ENTITY}"
    custom = _context("mqtt", {"topic_template": "x/{project_id}/{device_id}"})
    assert mqtt.topic_for(custom, _position()) == f"x/{PROJECT}/{DEVICE}"
    with pytest.raises(PermanentFailure):
        mqtt.topic_for(_context("mqtt", {"topic_template": "{nope}"}), _position())
    payload = get_connector("mqtt").render(context, _event())
    assert payload["topic"].endswith(f"/event/{ENTITY}") and payload["message"]["type"] == "event"


async def test_mqtt_without_host_is_permanent():
    with pytest.raises(PermanentFailure):
        await mqtt.publish(_context("mqtt"), "t", b"{}")
