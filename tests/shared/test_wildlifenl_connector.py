"""The WildlifeNL connector (decision D88): readings and detections from the API's own model,
species resolved by name, the bearer token and the role check."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.integrations.base import DeliveryItem, IntegrationContext, PermanentFailure, Skipped
from shared.integrations.connectors.wildlifenl import (
    WildlifeNlConnector,
    resolve_species,
    species_in_event,
)
from shared.integrations.registry import CONNECTORS

pytestmark = pytest.mark.asyncio

SPECIES = [
    {"ID": "11111111-1111-1111-1111-111111111111", "name": "Canis lupus", "commonName": "Wolf"},
    {"ID": "22222222-2222-2222-2222-222222222222", "name": "Sus scrofa", "commonName": "Wild boar"},
]


def integration(**config):
    return IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="WildlifeNL",
        connector_key="wildlifenl",
        config={"base_url": "https://wildlifenl.example/api", **config},
        credentials={"token": "tok"},
    )


def item(object_type="position", **overrides):
    base = DeliveryItem(
        object_type=object_type,
        object_id="123",
        object_version=1,
        time=datetime(2026, 9, 4, 10, 0, tzinfo=UTC),
        project_id=uuid.uuid4(),
        project_name="Kempen-Broek",
        project_slug="kempen",
        entity_id=uuid.UUID(int=7),
        entity_name="Konik 3",
        entity_type_key="horse",
        device_name="SP05-003",
        device_serial="SN-003",
        device_identity="70B3D57ED0001234",
        location=(51.2, 5.7),
        link="https://protect.example/projects/x/devices/y",
        data={"altitude_m": 34.5, "metric_key": "temperature", "value": 21.5},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def detection_item(**overrides):
    return item(
        "event",
        data={
            "event_type": "SPECIES_DETECTION",
            "severity": "info",
            "title": "Wolf at Waterhole north",
            "context": {
                "species": ["wolf", "wild_boar"],
                "max_confidence": 0.94,
                "classifications": [
                    {"species": "wolf", "confidence": 0.94},
                    {"species": "wolf", "confidence": 0.61},
                    {"species": "wild_boar", "confidence": 0.7},
                ],
                "link": "https://addaxai.example/images/abc",
            },
        },
        **overrides,
    )


def test_registered():
    assert "wildlifenl" in CONNECTORS and CONNECTORS["wildlifenl"].supports == {
        "position",
        "event",
        "measurement",
    }


def test_render_readings_by_identity_name_or_entity():
    connector = WildlifeNlConnector()
    reading = connector.render(integration(), item())
    assert reading["endpoint"] == "/borne-sensor-reading/" and reading["body"] == {
        "sensorID": "70B3D57ED0001234",
        "timestamp": "2026-09-04T10:00:00+00:00",
        "location": {"latitude": 51.2, "longitude": 5.7},
        "altitude": 34.5,
    }
    by_name = connector.render(integration(sensor_id_source="device_name"), item())
    assert by_name["body"]["sensorID"] == "SP05-003"
    by_entity = connector.render(integration(sensor_id_source="entity_id"), item())
    assert by_entity["body"]["sensorID"] == str(uuid.UUID(int=7))
    fallback = connector.render(integration(), item(device_identity=None))
    assert fallback["body"]["sensorID"] == "SN-003"
    with pytest.raises(Skipped):
        connector.render(
            integration(), item(device_identity=None, device_serial=None, device_name=None)
        )
    temperature = connector.render(integration(), item("measurement"))
    assert temperature["body"] == {
        "sensorID": "70B3D57ED0001234",
        "timestamp": "2026-09-04T10:00:00+00:00",
        "temperature": 21.5,
    }
    with pytest.raises(Skipped):
        connector.render(
            integration(), item("measurement", data={"metric_key": "battery", "value": 3.9})
        )
    with pytest.raises(Skipped):
        connector.render(integration(), item(location=None))


def test_render_detections_one_per_species():
    connector = WildlifeNlConnector()
    assert species_in_event(detection_item()) == {"wolf": 94, "wild_boar": 70}
    rendered = connector.render(integration(), detection_item())
    assert rendered["endpoint"] == "/detection/" and len(rendered["detections"]) == 2
    wolf = rendered["detections"][0]
    assert wolf["species"] == "wolf" and wolf["deploymentID"] == "70B3D57ED0001234"
    assert wolf["sensorType"] == "visual" and wolf["uri"] == "https://addaxai.example/images/abc"
    assert wolf["start"] == wolf["end"] == "2026-09-04T10:00:00+00:00"
    assert wolf["animals"] == [{"confidence": 94, "description": "Wolf at Waterhole north"}]
    assert wolf["location"] == {"latitude": 51.2, "longitude": 5.7}
    with pytest.raises(Skipped):
        connector.render(
            integration(),
            item("event", data={"event_type": "GEOFENCE_EXIT", "severity": "warning"}),
        )
    with pytest.raises(PermanentFailure):
        connector.render(integration(sensor_type="thermal"), detection_item())


def test_resolve_species_by_mapping_latin_or_common_name():
    assert resolve_species("wolf", SPECIES, {}) == SPECIES[0]["ID"]
    assert resolve_species("Canis lupus", SPECIES, {}) == SPECIES[0]["ID"]
    assert resolve_species("wild_boar", SPECIES, {}) == SPECIES[1]["ID"]
    assert resolve_species("everzwijn", SPECIES, {"everzwijn": "Sus scrofa"}) == SPECIES[1]["ID"]
    assert resolve_species("x", SPECIES, {"x": SPECIES[0]["ID"]}) == SPECIES[0]["ID"]
    assert resolve_species("unicorn", SPECIES, {}) is None


async def test_deliver_and_test_against_a_mock_platform(monkeypatch):
    calls: list[tuple[str, str, str | None, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, content=request.content).json() if request.content else None
        calls.append((request.method, request.url.path, request.headers.get("authorization"), body))
        if request.url.path == "/api/species/":
            return httpx.Response(200, json=SPECIES)
        if request.url.path == "/api/profile/me/":
            return httpx.Response(
                200,
                json={
                    "email": "collars@smartparks.org",
                    "roles": [{"ID": 2, "name": "data-system"}],
                },
            )
        if request.url.path == "/api/borne-sensor-reading/":
            return httpx.Response(204)
        if request.url.path == "/api/detection/":
            return httpx.Response(200, json={"ID": f"det-{len(calls)}", **body})
        return httpx.Response(404, json={"title": "Not Found"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )
    connector = WildlifeNlConnector()
    reading = await connector.deliver(
        integration(), item(), connector.render(integration(), item())
    )
    assert reading.external_id is None and reading.response["status"] == 204
    assert calls[0][:3] == ("POST", "/api/borne-sensor-reading/", "Bearer tok")
    assert calls[0][3]["sensorID"] == "70B3D57ED0001234"

    rendered = connector.render(integration(), detection_item())
    result = await connector.deliver(integration(), detection_item(), rendered)
    posted = [c for c in calls if c[1] == "/api/detection/"]
    assert (
        len(posted) == 2 and result.external_id == posted[0][3].get("ID") is None
    ) or result.external_id
    assert posted[0][3]["speciesID"] == SPECIES[0]["ID"] and "species" not in posted[0][3]
    assert posted[1][3]["speciesID"] == SPECIES[1]["ID"]
    assert len(result.response["detection_ids"]) == 2
    assert sum(1 for c in calls if c[1] == "/api/species/") == 1  # cached

    unknown = detection_item()
    unknown.data["context"]["species"] = ["unicorn"]
    unknown.data["context"]["classifications"] = []
    with pytest.raises(PermanentFailure, match="unicorn"):
        await connector.deliver(integration(), unknown, connector.render(integration(), unknown))

    answer = await connector.test(integration(), None)
    assert answer["roles"] == ["data-system"] and answer["species_count"] == 2


async def test_test_reports_a_missing_role_and_refused_tokens(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != "Bearer tok":
            return httpx.Response(
                401, json={"title": "Unauthorized", "detail": "Invalid bearer token."}
            )
        return httpx.Response(
            200, json={"email": "someone@example.org", "roles": [{"ID": 3, "name": "researcher"}]}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )
    connector = WildlifeNlConnector()
    with pytest.raises(PermanentFailure, match="data-system"):
        await connector.test(integration(), None)
    bad = IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="x",
        connector_key="wildlifenl",
        config={"base_url": "https://wildlifenl.example/api"},
        credentials={"token": "wrong"},
    )
    with pytest.raises(PermanentFailure, match="refused the token"):
        await connector.test(bad, None)
    with pytest.raises(PermanentFailure, match="no token"):
        await connector.deliver(
            IntegrationContext(
                id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                name="x",
                connector_key="wildlifenl",
                config={"base_url": "https://wildlifenl.example/api"},
                credentials={},
            ),
            item(),
            connector.render(integration(), item()),
        )
