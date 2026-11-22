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
    CodeLogin,
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
    rights,
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


def test_a_status_message_is_one_reading_without_a_location():
    """Decision D421: the device's temperature is forwarded, and the accelerometer of the same
    moment rides along in m/s², so one status message is one request. The other numbers of
    the moment have no field on the platform and are left out."""
    connector = WildlifeNlConnector()
    moment = {
        "device_temperature": 2.75,
        "acceleration_x": 1.96,
        "acceleration_y": 10.59,
        "acceleration_z": 1.18,
        "battery_voltage": 3.9,
        "activity": 12.0,
    }
    reading = connector.render(
        integration(),
        item(
            "measurement",
            location=None,
            data={"metric_key": "device_temperature", "value": 2.75, "moment": moment},
        ),
    )
    assert reading["body"] == {
        "sensorID": "70B3D57ED0001234",
        "timestamp": "2026-09-04T10:00:00+00:00",
        "temperature": 2.75,
        "accelero": {"x": 1.96, "y": 10.59, "z": 1.18},
    }
    # an axis missing: the temperature alone
    partial = {k: v for k, v in moment.items() if k != "acceleration_z"}
    alone = connector.render(
        integration(),
        item(
            "measurement",
            data={"metric_key": "device_temperature", "value": 2.75, "moment": partial},
        ),
    )
    assert "accelero" not in alone["body"] and "location" not in alone["body"]
    # the axes themselves are not forwarded: they ride along with the temperature
    with pytest.raises(Skipped):
        connector.render(
            integration(),
            item("measurement", data={"metric_key": "acceleration_x", "value": 1.96}),
        )
    assert WildlifeNlConnector.forwards == {
        "object_types": ["position", "measurement"],
        "metric_keys": ["device_temperature", "temperature"],
    }


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


def test_the_rights_come_from_the_servers_own_document():
    """Decision D420: the scopes each call takes are read from the server's document, so a
    role given more rights there, or an administrator listed on an operation, is seen."""
    document = {
        "paths": {
            "/borne-sensor-reading/": {"post": {"security": [{"auth": ["data-system", "admin"]}]}},
            "/animal/": {"post": {"security": [{"auth": ["herd-manager", "admin"]}]}},
            "/borne-sensor-deployment/": {"post": {"security": [{"auth": []}]}},
        }
    }
    admin = rights(document, ["admin"])
    assert admin["readings"] and admin["animals"] and admin["deployments"]
    # not in the document: the scopes the source gave it
    assert not admin["active_deployments"] and not admin["detections"]
    system = rights(document, ["data-system"])
    assert system["readings"] and system["detections"] and not system["animals"]
    assert rights({}, ["herd-manager"])["active_deployments"]


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


async def test_an_entity_is_offered_its_species_and_registered_as_chosen(monkeypatch):
    """Decisions D408, D413 and D416: the platform's species to pick from with a proposal,
    what the platform has read from its active deployments and on which animal, an animal
    made as chosen, and a deployment that is not sent twice."""
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
                return httpx.Response(422, json={"title": "Unprocessable Entity"})
            # the platform's own rule: the sensor's deployment before it ends at this start
            active[:] = [d for d in active if d["sensorID"] != body["sensorID"]]
            # the platform's answer since 2026-11-22 names the animal by its identifier
            active.append(
                {**body, "animal": {"ID": body["animalID"], "identifier": "NL123456789012"}}
            )
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    mock_platform(monkeypatch, handler)
    connector = WildlifeNlConnector()
    konik_3 = "aaaaaaaa-0000-4000-8000-000000000001"
    known = subject(external_id=konik_3)
    new = subject(
        entity_id=uuid.UUID(int=9),
        entity_name="Konik 9",
        entity_type_label="Konik",
        device_identity="70B3D57ED0009999",
        attributes={"ear_tag": "NL123456789012"},
    )
    no_device = subject(
        entity_id=uuid.UUID(int=10),
        device_identity=None,
        device_serial=None,
        device_name=None,
        attributes={"ear_tag": "NL123456789099"},
    )
    # Konik 3's device moved to Konik 10 in Protect: the platform still has it on Konik 3
    moved = subject(entity_id=uuid.UUID(int=11), entity_name="Konik 10")

    options = await connector.options(integration(), new)
    # every species of the platform, by the name a person reads, and the one Protect proposes
    assert [c.common_name for c in options.species] == ["Konik", "Wild boar", "Wolf"]
    assert options.proposed_species_id == HORSE["ID"] and options.blocked is None
    # the platform calls the animal by its ear tag number, asked when integrating (D422)
    assert WildlifeNlConnector.subject_fields == ("ear_tag",)
    assert options.sensor_id == "70B3D57ED0009999" and not options.status.registered
    unknown = await connector.options(integration(), subject(entity_type_label="Horse"))
    assert unknown.proposed_species_id is None  # never a guess (D411); the user picks
    # an entity without a device may be integrated; its first device waits (D418)
    assert (await connector.options(integration(), no_device)).blocked is None
    elsewhere = await connector.options(integration(), moved)
    assert not elsewhere.status.registered and elsewhere.status.elsewhere == "Konik 3"

    statuses = await connector.statuses(integration(), [known, new, no_device, moved])
    assert [statuses[s.entity_id].registered for s in (known, new, no_device, moved)] == [
        True,
        False,
        False,
        False,  # the sensor is on another animal: not this entity's (the bug of D408)
    ]
    assert statuses[known.entity_id].since == datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    # the species the platform has for the animal, to show beside Protect's choice (D423)
    assert statuses[known.entity_id].external_species == "Konik (Equus ferus caballus)"
    assert statuses[moved.entity_id].elsewhere == "Konik 3"
    assert not [c for c in calls if c[0] == "POST"]  # reading changes nothing

    chosen = {"species_id": HORSE["ID"], "species_name": HORSE["name"]}
    with pytest.raises(PermanentFailure, match="Choose the entity's species"):
        await connector.register_animal(integration(), new, {})
    animal_id = await connector.register_animal(integration(), new, chosen)
    assert animal_id == "bbbbbbbb-0000-4000-8000-000000000002"
    animals = [c for c in calls if c[:2] == ("POST", "/animal/")]
    assert animals == [
        ("POST", "/animal/", {"identifier": "NL123456789012", "speciesID": HORSE["ID"]})
    ]
    with pytest.raises(PermanentFailure, match="ear tag number"):
        await connector.register_animal(integration(), subject(entity_id=uuid.UUID(int=12)), chosen)

    start = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    with pytest.raises(PermanentFailure):
        await connector.deploy(integration(), animal_id, "70B3D57ED0009999", start)
    refuse_deployment["on"] = False
    await connector.deploy(integration(), animal_id, "70B3D57ED0009999", start)
    deployment = [c for c in calls if c[:2] == ("POST", "/borne-sensor-deployment/")][-1][2]
    assert deployment == {
        "animalID": animal_id,
        "sensorID": "70B3D57ED0009999",
        "contactHardwareAddress": None,
        # from the start of the device's time on the entity, so its history belongs to it
        "start": "2026-05-01T08:00:00+00:00",
    }

    # a second try sends nothing: the sensor is on that animal
    posts = len([c for c in calls if c[0] == "POST"])
    await connector.deploy(integration(), animal_id, "70B3D57ED0009999", start)
    await connector.deploy(integration(), konik_3, "70B3D57ED0001234", start)
    assert len([c for c in calls if c[0] == "POST"]) == posts
    # the device moved: its sensor goes to the other animal, which ends it on Konik 3
    await connector.deploy(integration(), animal_id, "70B3D57ED0001234", start)
    assert len([c for c in calls if c[0] == "POST"]) == posts + 1
    moved_status = await connector.statuses(integration(), [moved, known])
    assert moved_status[known.entity_id].elsewhere == "NL123456789012"


async def test_an_account_without_the_rights_is_told(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"title": "Forbidden"})

    mock_platform(monkeypatch, handler)
    with pytest.raises(PermanentFailure, match=r"does not show its deployments.*403"):
        await WildlifeNlConnector().statuses(integration(), [subject()])


async def test_test_reports_a_missing_role_and_refused_tokens(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/openapi.json":
            return httpx.Response(200, json=API_TEST)
        if request.url.path == "/api/species/":
            return httpx.Response(200, json=SPECIES)
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
    # an account without the rights is reported, not refused: its roles may change (D420)
    answer = await connector.test(integration(), None)
    assert answer["roles"] == ["researcher"]
    assert answer["can_send_readings"] is False and answer["can_register_animals"] is False
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
    with pytest.raises(PermanentFailure, match="not signed in"):
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


async def test_signing_in_with_the_code_from_the_email(monkeypatch):
    """Decision D414: Protect asks for the code and trades it for the token; the user never
    handles a token. Neither call carries one."""
    calls: list[tuple[str, str, str | None, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = httpx.Response(200, content=request.content).json()
        calls.append((request.method, request.url.path, request.headers.get("authorization"), body))
        if request.method == "POST":
            return httpx.Response(200, json="The authentication code has been sent")
        if body["code"] != "123456":
            return httpx.Response(403, json={"title": "Forbidden", "detail": "does not match"})
        return httpx.Response(
            200,
            json={
                "email": "tim@example.org",
                "token": "tok-from-the-platform",
                "userID": "u1",
                "scopes": ["data-system", "herd-manager"],
            },
        )

    mock_platform(monkeypatch, handler)
    connector = WildlifeNlConnector()
    assert isinstance(connector, CodeLogin)
    signed_out = IntegrationContext(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name="x",
        connector_key="wildlifenl",
        config={"base_url": "https://wildlifenl.example/api"},
        credentials={},
    )
    await connector.request_code(signed_out, "tim@example.org")
    assert calls[0] == (
        "POST",
        "/api/auth/",
        None,
        {"displayNameApp": "Smart Parks Protect", "email": "tim@example.org"},
    )
    with pytest.raises(PermanentFailure, match="did not accept the code"):
        await connector.exchange_code(signed_out, "tim@example.org", "000000")
    result = await connector.exchange_code(signed_out, "tim@example.org", " 123456 ")
    assert calls[-1] == ("PUT", "/api/auth/", None, {"email": "tim@example.org", "code": "123456"})
    assert result.credentials == {"token": "tok-from-the-platform"}
    assert result.account == "tim@example.org"
    assert result.scopes == ["data-system", "herd-manager"]
