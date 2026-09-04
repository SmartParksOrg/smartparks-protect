"""The direct EarthRanger connector (decision D84): payloads from the documented API, the
bearer token, updates of corrected events through the previous external id."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.integrations.base import DeliveryItem, IntegrationContext, PermanentFailure, Skipped
from shared.integrations.connectors.earthranger import EarthRangerConnector, parse_object_id

pytestmark = pytest.mark.asyncio


def integration(**config):
    return IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="ER site",
        connector_key="earthranger",
        config={
            "base_url": "https://site.pamdas.org",
            "subject_types": {"rhino": "rhino"},
            **config,
        },
        credentials={"token": "tok"},
    )


def item(object_type="position", **overrides):
    base = DeliveryItem(
        object_type=object_type,
        object_id="123",
        object_version=1,
        time=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        project_id=uuid.uuid4(),
        project_name="Demo park",
        project_slug="demo",
        entity_id=uuid.UUID(int=7),
        entity_name="Rhino 14",
        entity_type_key="rhino",
        device_name="SP05-demo",
        location=(-24.9, 31.5),
        data={
            "altitude_m": 300,
            "accuracy_m": 12,
            "event_type": "GEOFENCE_EXIT",
            "severity": "warning",
            "title": "Rhino 14 left the reserve",
        },
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


async def test_render_observation_and_event():
    connector = EarthRangerConnector()
    observation = connector.render(integration(), item())
    assert (
        observation["method"] == "POST"
        and observation["endpoint"] == "/api/v1.0/sensors/generic/smartparks_protect/status"
    )
    body = observation["body"]
    assert body["manufacturer_id"] == str(uuid.UUID(int=7)) and body["subject_name"] == "Rhino 14"
    assert body["subject_type"] == "rhino" and body["location"] == {"lat": -24.9, "lon": 31.5}
    assert (
        body["recorded_at"] == "2026-09-04T10:00:00+00:00"
        and body["additional"]["altitude_m"] == 300
    )
    event = connector.render(integration(), item("event"))
    assert event["endpoint"] == "/api/v1.0/activity/events"
    assert event["body"]["priority"] == 200 and event["body"]["location"] == {
        "latitude": -24.9,
        "longitude": 31.5,
    }
    assert event["body"]["event_details"]["smartparks_protect_event_type"] == "GEOFENCE_EXIT"
    update = connector.render(
        integration(), item("event", object_version=2, previous_external_id="er-42")
    )
    assert update["method"] == "PATCH" and update["endpoint"] == "/api/v1.0/activity/event/er-42"
    with pytest.raises(Skipped):
        connector.render(integration(), item(entity_id=None))
    with pytest.raises(Skipped):
        connector.render(integration(), item("measurement"))
    assert parse_object_id({"data": {"id": "abc"}}) == "abc" and parse_object_id({"id": "x"}) == "x"


async def test_deliver_and_test_use_the_bearer_token(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/status"):
            return httpx.Response(201, json={"data": {"id": "obs-1"}})
        return httpx.Response(201, json={"data": {"id": "ev-1"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )
    connector = EarthRangerConnector()
    payload = connector.render(integration(), item())
    result = await connector.deliver(integration(), item(), payload)
    assert result.external_id == "obs-1" and calls[0] == (
        "POST",
        "/api/v1.0/sensors/generic/smartparks_protect/status",
        "Bearer tok",
    )
    answer = await connector.test(integration(), (-24.9, 31.5))
    assert answer["status"] == 201 and calls[-1][1] == "/api/v1.0/activity/events"
    with pytest.raises(PermanentFailure):
        await connector.test(integration(), None)
    bad = IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="x",
        connector_key="earthranger",
        config={},
        credentials={},
    )
    with pytest.raises(PermanentFailure):
        await connector.deliver(bad, item(), payload)
