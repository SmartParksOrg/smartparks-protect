"""The WildlifeNL connector (decisions D88 and D407 to D411): readings and detections from the
API's own model, the species field each server asks for, the bearer token and the role check,
the rate limit's waiting time, and the animals and deployments Protect registers."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from shared.integrations.base import (
    DeliveryItem,
    IntegrationContext,
    PermanentFailure,
    Skipped,
    Subject,
    SubjectRegistrar,
    TransientFailure,
)
from shared.integrations.connectors.wildlifenl import (
    WildlifeNlConnector,
    detection_species_field,
    resolve_species,
    species_in_event,
    species_of,
)
from shared.integrations.registry import CONNECTORS

pytestmark = pytest.mark.asyncio

SPECIES = [
    {"ID": "11111111-1111-1111-1111-111111111111", "name": "Canis lupus", "commonName": "Wolf"},
    {"ID": "22222222-2222-2222-2222-222222222222", "name": "Sus scrofa", "commonName": "Wild boar"},
]
HORSE = {
    "ID": "33333333-3333-3333-3333-333333333333",
    "name": "Equus ferus caballus",
    "commonName": "Konik",
}
FIXTURES = Path(__file__).parents[1] / "fixtures" / "payloads" / "wildlifenl"
# the two servers' own description of POST /detection/, read on 2026-11-21
API_TEST = json.loads((FIXTURES / "openapi_test_detection.json").read_text())
API_LIVE = json.loads((FIXTURES / "openapi_live_detection.json").read_text())
ACTIVE = json.loads((FIXTURES / "active_deployments.json").read_text())


def mock_platform(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **k)
    )


def subject(**overrides):
    values = {
        "entity_id": uuid.UUID(int=7),
        "entity_name": "Konik 3",
        "entity_type_key": "horse",
        "entity_type_label": "Horse",
        "entity_type_parent_key": "wildlife",
        "device_name": "SP05-003",
        "device_serial": "SN-003",
        "device_identity": "70B3D57ED0001234",
        "assigned_from": datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
    }
    return Subject(**{**values, **overrides})


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
        if request.url.path == "/api/openapi.json":
            return httpx.Response(200, json=API_LIVE)
        if request.url.path == "/api/profile/me/":
            return httpx.Response(
                200,
                json={
                    "email": "devices@smartparks.org",
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
    # what this server takes and whether the account may register animals (D407, D408)
    assert answer["api_version"] == "20260826" and answer["detection_species_field"] == "speciesID"
    assert answer["can_register_animals"] is False
    assert sum(1 for c in calls if c[1] == "/api/openapi.json") == 1  # read once, then kept


def test_the_species_field_of_a_detection_follows_the_server():
    """Decision D407: the TEST server of 2026-11 takes the Latin name, the LIVE server the id,
    and both refuse a field their schema does not name."""
    assert detection_species_field(API_TEST) == "speciesName"
    assert detection_species_field(API_LIVE) == "speciesID"
    for document in (API_TEST, API_LIVE):
        record = document["components"]["schemas"]["DetectionRecord"]
        assert record["additionalProperties"] is False
    with pytest.raises(PermanentFailure, match="does not describe"):
        detection_species_field({"paths": {}})
    with pytest.raises(PermanentFailure, match="no species field"):
        detection_species_field(
            {
                "paths": {
                    "/detection/": {
                        "post": {
                            "requestBody": {
                                "content": {
                                    "application/json": {"schema": {"properties": {"start": {}}}}
                                }
                            }
                        }
                    }
                }
            }
        )


async def test_a_detection_names_the_species_as_the_server_asks(monkeypatch):
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/species/":
            return httpx.Response(200, json=SPECIES)
        if request.url.path == "/api/openapi.json":
            return httpx.Response(200, json=API_TEST)
        posted.append(httpx.Response(200, content=request.content).json())
        return httpx.Response(200, json={"ID": f"det-{len(posted)}"})

    mock_platform(monkeypatch, handler)
    connector = WildlifeNlConnector()
    rendered = connector.render(integration(), detection_item())
    await connector.deliver(integration(), detection_item(), rendered)
    allowed = set(API_TEST["components"]["schemas"]["DetectionRecord"]["properties"])
    assert [d["speciesName"] for d in posted] == ["Canis lupus", "Sus scrofa"]
    assert all("speciesID" not in d and set(d) <= allowed for d in posted)


async def test_a_429_carries_the_time_the_platform_asks_for(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"title": "Too Many"})

    mock_platform(monkeypatch, handler)
    connector = WildlifeNlConnector()
    with pytest.raises(TransientFailure, match="429") as raised:
        await connector.deliver(integration(), item(), connector.render(integration(), item()))
    assert raised.value.retry_after == 120


def test_the_species_of_an_entity():
    """Decision D411: the entity's own value, the mapping by its type, the type's label; never
    a guess."""
    catalogue = [*SPECIES, HORSE]
    assert species_of(subject(), catalogue, {"horse": "Equus ferus caballus"}) == HORSE
    assert species_of(subject(attributes={"species": "Sus scrofa"}), catalogue, {}) == SPECIES[1]
    assert species_of(subject(entity_type_label="Konik"), catalogue, {}) == HORSE
    assert species_of(subject(), catalogue, {}) is None


async def test_subjects_and_their_registration(monkeypatch):
    """Decision D408: what the platform has is read from its active deployments; an animal and
    a deployment are made for the entity it lacks, and a second run makes neither again."""
    assert isinstance(WildlifeNlConnector(), SubjectRegistrar)
    calls: list[tuple[str, str, dict | None]] = []
    active = list(ACTIVE)
    refuse_deployment = {"on": True}

    def handler(request: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, content=request.content).json() if request.content else None
        path = request.url.path.removeprefix("/api")
        calls.append((request.method, path, body))
        if path == "/species/":
            return httpx.Response(200, json=[*SPECIES, HORSE])
        if path == "/borne-sensor-deployment/active/":
            return httpx.Response(200, json=active)
        if path == "/animal/":
            return httpx.Response(200, json={"ID": "bbbbbbbb-0000-4000-8000-000000000002", **body})
        if path == "/borne-sensor-deployment/":
            if refuse_deployment["on"]:
                return httpx.Response(500, json={"title": "Internal Server Error"})
            active.append({**body, "animal": {"ID": body["animalID"], "name": "Konik 9"}})
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    mock_platform(monkeypatch, handler)
    connector = WildlifeNlConnector()
    config = {"species": {"horse": "Equus ferus caballus"}}
    known = subject()
    new = subject(
        entity_id=uuid.UUID(int=9), entity_name="Konik 9", device_identity="70B3D57ED0009999"
    )
    no_device = subject(
        entity_id=uuid.UUID(int=10), device_identity=None, device_serial=None, device_name=None
    )
    no_species = subject(
        entity_id=uuid.UUID(int=11),
        entity_type_key="okapi",
        entity_type_label="Okapi",
        device_identity="70B3D57ED0001111",
    )
    everyone = [known, new, no_device, no_species]

    statuses = await connector.subjects(integration(**config), everyone, {})
    assert [s.state for s in statuses] == ["registered", "not_registered", "blocked", "blocked"]
    assert statuses[0].external_name == "Konik 3" and statuses[0].since == datetime(
        2026, 5, 1, 8, 0, tzinfo=UTC
    )
    assert statuses[1].sensor_id == "70B3D57ED0009999"
    assert statuses[1].species == "Equus ferus caballus"
    assert "No device" in statuses[2].detail and "no species" in statuses[3].detail
    assert not [c for c in calls if c[0] == "POST"]  # reading changes nothing

    # the platform fails between the animal and the deployment: the animal is remembered
    statuses, state = await connector.register(integration(**config), everyone, {})
    assert statuses[1].state == "blocked" and "500" in statuses[1].detail
    assert state["animals"] == {str(new.entity_id): "bbbbbbbb-0000-4000-8000-000000000002"}

    refuse_deployment["on"] = False
    statuses, state = await connector.register(integration(**config), everyone, state)
    assert [s.state for s in statuses] == ["registered", "registered", "blocked", "blocked"]
    animals = [c for c in calls if c[:2] == ("POST", "/animal/")]
    assert len(animals) == 1  # not a second animal for the second attempt
    assert animals[0][2] == {"name": "Konik 9", "speciesID": HORSE["ID"]}
    deployment = [c for c in calls if c[:2] == ("POST", "/borne-sensor-deployment/")][-1][2]
    assert deployment == {
        "animalID": "bbbbbbbb-0000-4000-8000-000000000002",
        "sensorID": "70B3D57ED0009999",
        "contactHardwareAddress": None,
        # from the start of the device's time on the entity, so its history belongs to it
        "start": "2026-05-01T08:00:00+00:00",
    }

    posts = len([c for c in calls if c[0] == "POST"])
    statuses, _ = await connector.register(integration(**config), everyone, state)
    assert statuses[1].state == "registered"
    assert len([c for c in calls if c[0] == "POST"]) == posts  # nothing left to make


async def test_an_account_without_the_herd_manager_role_is_told(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"title": "Forbidden"})

    mock_platform(monkeypatch, handler)
    with pytest.raises(PermanentFailure, match="herd-manager"):
        await WildlifeNlConnector().subjects(integration(), [subject()], {})


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
