"""WildlifeNL (decision D88): the data platform of the WildlifeNL research programme, of which
Smart Parks is a consortium member.

Built from the API's source and design documents (github.com/UtrechtUniversity/wildlifenl,
MPL-2.0, read 2026-09-04; the OpenAPI document is generated from the same code and served at
the API's root):

- Every call carries `Authorization: Bearer <token>`. A token is a credential created through
  the email code flow (`POST /auth/`, then `PUT /auth/` with the code) and stays valid; the
  scopes of the account's roles decide what it may do. Automated systems need the
  `data-system` role.
- `POST /borne-sensor-reading/` (scope `data-system`): `sensorID`, `timestamp`, optional
  `location` (`latitude`, `longitude`), `altitude`, `temperature` (degrees Celsius) and
  `accelero` (`x`, `y`, `z`). The answer has no body. WildlifeNL links a reading to an animal
  through a borne sensor deployment with the same `sensorID`, registered by a herd manager;
  readings without one are accepted and kept for later.
- `POST /detection/` (scope `data-system`): `speciesID`, `deploymentID` (the sensor's
  identification), `sensorType` (`visual`, `acoustic`, `motion`, `radio`, `chemical`, `other`),
  `location`, `start`, `end`, optional `uri`, and `animals`, one per animal with `confidence`
  as a percentage and optional `behaviour`, `description`, `sex`, `lifeStage`, `condition`.
  All animals of one detection share a species; an image with several species becomes
  several detections. The answer is the detection with its `ID`.
- `GET /species/` lists species with `ID`, `name` (the Latin binomen), `commonName` and
  `category`; `GET /profile/me/` returns the account with its `roles`.

Mapping: positions and temperature measurements are borne sensor readings under the device's
identity (configurable); `SPECIES_DETECTION` events (camera traps) are detections, with the
species resolved by name against the platform's list. Other events are skipped: WildlifeNL
has no free-form events, its interactions are people's reports.

Read again on 2026-11-21 (phase 49, decisions D407 to D411), the source at its push of
2026-11-16 and the OpenAPI documents of the TEST server (version 20261116) and the LIVE
server (20260826):

- A detection takes `speciesName` (the Latin name, matched exactly) on TEST and `speciesID`
  on LIVE. The connector reads the server's own `/openapi.json` and sends what it asks for.
- Requests are limited per token with a growing cooldown; a 429 carries `Retry-After`.
- A reading reaches an animal only through a deployment with the same `sensorID`:
  `POST /animal/` (`name`, `speciesID`) and `POST /borne-sensor-deployment/` (`animalID`,
  `sensorID`, `contactHardwareAddress` or null, `start`), both under the `herd-manager` role;
  `GET /borne-sensor-deployment/active/` lists the deployments without an end. A new
  deployment of a sensor ends the one before it.
- A reading with a location for an animal with a deployment sets the animal's location
  whatever the reading's age and, as the code reads, raises zone alarms when the reading is
  older than an hour. A reading without a deployment is stored and does neither. So old data
  goes first and the deployment after it (decision D409).
- Readings are kept per sensor and timestamp, so a reading sent twice overwrites itself.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    LoginResult,
    PartlyRegistered,
    PermanentFailure,
    Skipped,
    Subject,
    SubjectChoice,
    SubjectOptions,
    SubjectStatus,
    TransientFailure,
    iso,
    require_config,
)

DETECTION_EVENT_TYPE = "SPECIES_DETECTION"
DEFAULT_SENSOR_ID_SOURCE = "device_identity"
SENSOR_ID_SOURCES = ("device_identity", "device_name", "entity_id")
DEFAULT_TEMPERATURE_METRICS = ["temperature"]
DEFAULT_SENSOR_TYPE = "visual"
SENSOR_TYPES = ("visual", "acoustic", "motion", "radio", "chemical", "other")
REQUEST_TIMEOUT_SECONDS = 30
SPECIES_CACHE_SECONDS = 600
API_DOCUMENT_CACHE_SECONDS = 3600
DATA_SYSTEM_ROLE = "data-system"
HERD_MANAGER_ROLE = "herd-manager"
# The name in the platform's login email ("displayNameApp").
LOGIN_APP_NAME = "Smart Parks Protect"
SPECIES_FIELDS = ("speciesName", "speciesID")
# The keys of an entity's own document that name its species, as the Movebank export reads
# them (decision D411).
SPECIES_ATTRIBUTES = ("taxon", "species", "scientific_name")


def sensor_id(integration: IntegrationContext, source: DeliveryItem | Subject) -> str | None:
    """What WildlifeNL sees as `sensorID`, the same for a reading and for the deployment that
    links it to an animal; at least two characters, as the platform asks."""
    kind = str(integration.config.get("sensor_id_source") or DEFAULT_SENSOR_ID_SOURCE)
    if kind == "device_name":
        value = source.device_name
    elif kind == "entity_id":
        value = str(source.entity_id) if source.entity_id else None
    else:
        value = source.device_identity or source.device_serial or source.device_name
    return value if value and len(value) >= 2 else None


def sensor_id_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    value = sensor_id(integration, item)
    if value is None:
        kind = str(integration.config.get("sensor_id_source") or DEFAULT_SENSOR_ID_SOURCE)
        raise Skipped(f"no sensor id for {item.object_type} {item.object_id} ({kind})")
    return value


def _reading(sensor_id: str, item: DeliveryItem) -> dict[str, Any]:
    return {"sensorID": sensor_id, "timestamp": iso(item.time)}


def build_position_reading(integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
    if item.location is None:
        raise Skipped(f"position {item.object_id} has no location")
    body = _reading(sensor_id_for(integration, item), item)
    body["location"] = {"latitude": item.location[0], "longitude": item.location[1]}
    altitude = item.data.get("altitude_m")
    if isinstance(altitude, int | float):
        body["altitude"] = float(altitude)
    return body


def build_measurement_reading(
    integration: IntegrationContext, item: DeliveryItem
) -> dict[str, Any]:
    metrics = [str(m) for m in integration.config.get("temperature_metrics") or []]
    metric = str(item.data.get("metric_key") or "")
    value = item.data.get("value")
    if metric not in (metrics or DEFAULT_TEMPERATURE_METRICS):
        raise Skipped(f"WildlifeNL readings carry temperature only, not {metric}")
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise Skipped(f"measurement {item.object_id} has no numeric value")
    body = _reading(sensor_id_for(integration, item), item)
    body["temperature"] = float(value)
    return body


def _percent(confidence: Any) -> int:
    try:
        number = float(confidence)
    except (TypeError, ValueError):
        return 0
    if number <= 1.0:
        number *= 100
    return max(0, min(100, round(number)))


def _context(item: DeliveryItem) -> dict[str, Any]:
    context = item.data.get("context")
    return dict(context) if isinstance(context, dict) else {}


def species_in_event(item: DeliveryItem) -> dict[str, int]:
    """Species named by the event with the best confidence per species, in order of mention."""
    context = _context(item)
    found: dict[str, int] = {}
    for classification in context.get("classifications") or []:
        if not isinstance(classification, dict) or not classification.get("species"):
            continue
        name = str(classification["species"])
        found[name] = max(found.get(name, 0), _percent(classification.get("confidence")))
    for name in context.get("species") or []:
        if name and str(name) not in found:
            found[str(name)] = _percent(context.get("max_confidence"))
    return found


def build_detections(integration: IntegrationContext, item: DeliveryItem) -> list[dict[str, Any]]:
    """One detection per species of a `SPECIES_DETECTION` event; `speciesID` is filled in at
    delivery, `species` holds the name until then."""
    species = species_in_event(item)
    if str(item.data.get("event_type") or "") != DETECTION_EVENT_TYPE or not species:
        raise Skipped("WildlifeNL takes species detections; other events have no counterpart")
    if item.location is None:
        raise Skipped(f"detection {item.object_id} has no location")
    context = _context(item)
    sensor_type = str(integration.config.get("sensor_type") or DEFAULT_SENSOR_TYPE)
    if sensor_type not in SENSOR_TYPES:
        raise PermanentFailure(f"sensor_type must be one of {', '.join(SENSOR_TYPES)}")
    deployment = sensor_id_for(integration, item)
    uri = context.get("link") or item.link
    detections = []
    for name, confidence in species.items():
        detection: dict[str, Any] = {
            "species": name,
            "deploymentID": deployment,
            "sensorType": sensor_type,
            "location": {"latitude": item.location[0], "longitude": item.location[1]},
            "start": iso(item.time),
            "end": iso(item.time),
            "animals": [
                {
                    "confidence": confidence,
                    "description": str(item.data.get("title") or "")[:200] or None,
                }
            ],
        }
        if uri:
            detection["uri"] = str(uri)
        detection["animals"] = [
            {k: v for k, v in animal.items() if v is not None} for animal in detection["animals"]
        ]
        detections.append(detection)
    return detections


def _is_uuid(value: str) -> bool:
    parts = value.split("-")
    return len(value) == 36 and [len(p) for p in parts] == [8, 4, 4, 4, 12]


def find_species(
    name: str, catalogue: list[dict[str, Any]], mapping: dict[str, str]
) -> dict[str, Any] | None:
    """The platform's species for a Smart Parks name: the integration's own mapping first (to
    a name or an id), then the Latin or common name, case-insensitive. An id the mapping names
    that the list does not hold is believed, with the id alone."""
    wanted = mapping.get(name) or mapping.get(name.lower()) or name
    lowered = wanted.strip().lower().replace("_", " ")
    for species in catalogue:
        if not species.get("ID"):
            continue
        candidates = {
            str(species["ID"]).lower(),
            str(species.get("name") or "").lower(),
            str(species.get("commonName") or "").lower(),
        }
        if lowered in candidates:
            return species
    return {"ID": wanted} if _is_uuid(wanted) else None


def resolve_species(
    name: str, catalogue: list[dict[str, Any]], mapping: dict[str, str]
) -> str | None:
    """The WildlifeNL species id for a Smart Parks species name."""
    species = find_species(name, catalogue, mapping)
    return str(species["ID"]) if species else None


def species_of(
    subject: Subject, catalogue: list[dict[str, Any]], mapping: dict[str, str]
) -> dict[str, Any] | None:
    """The platform's species of an entity (decision D411): what the entity says of itself,
    else the integration's mapping by the type's key, else the type's label. None when the
    platform knows none of them; an animal is never registered under a guess."""
    candidates = [
        str(subject.attributes[key]) for key in SPECIES_ATTRIBUTES if subject.attributes.get(key)
    ]
    candidates += [c for c in (subject.entity_type_key, subject.entity_type_label) if c]
    for candidate in candidates:
        species = find_species(candidate, catalogue, mapping)
        if species is not None and species.get("name"):
            return species
    return None


def detection_species_field(document: dict[str, Any]) -> str:
    """Which field names the species in `POST /detection/` on this server (decision D407),
    from its OpenAPI document: `speciesName` since the source of 2026-11, `speciesID` before."""
    try:
        schema = document["paths"]["/detection/"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        if "$ref" in schema:
            schema = document["components"]["schemas"][str(schema["$ref"]).rsplit("/", 1)[-1]]
        properties = schema["properties"]
    except (KeyError, TypeError):
        raise PermanentFailure(
            "the WildlifeNL server's API document does not describe POST /detection/"
        ) from None
    for field in SPECIES_FIELDS:
        if field in properties:
            return field
    raise PermanentFailure(
        "the WildlifeNL server's API document names no species field for a detection "
        f"(looked for {', '.join(SPECIES_FIELDS)})"
    )


def _retry_after(response: httpx.Response) -> float | None:
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return seconds if seconds > 0 else None


class WildlifeNlClient:
    def __init__(self, base_url: str, token: str | None) -> None:
        """`token` is None only for the login itself, the two calls that need none."""
        if token == "":
            raise PermanentFailure(
                "the WildlifeNL integration is not signed in: sign in on the integration"
            )
        self.base_url = base_url.rstrip("/")
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token is not None:
            self.headers["Authorization"] = f"Bearer {token}"

    async def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", json=payload, headers=self.headers
                )
        except httpx.HTTPError as exc:
            raise TransientFailure(f"wildlifenl: {type(exc).__name__}: {exc}") from exc
        if response.status_code == 429:
            # the platform limits per token with a growing cooldown and says how long to wait
            wait = _retry_after(response)
            raise TransientFailure(
                "wildlifenl answered 429" + (f", asking for {wait:g} s" if wait else ""),
                retry_after=wait,
            )
        if response.status_code >= 500:
            raise TransientFailure(f"wildlifenl answered {response.status_code}")
        if response.status_code in (401, 403):
            what = "the token" if "Authorization" in self.headers else "the request"
            raise PermanentFailure(
                f"wildlifenl refused {what} ({response.status_code}): {response.text[:300]}"
            )
        if response.status_code >= 400:
            raise PermanentFailure(
                f"wildlifenl answered {response.status_code}: {response.text[:300]}"
            )
        body: Any
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = {"text": response.text[:300]}
        return {"status": response.status_code, "body": body}


class WildlifeNlConnector:
    key: ClassVar[str] = "wildlifenl"
    label: ClassVar[str] = "WildlifeNL"
    description: ClassVar[str] = (
        "Positions and temperature readings become borne sensor readings under the device's "
        "identity; camera trap species detections become detections with the species resolved "
        "by name; other events are skipped"
    )
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event", "measurement"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["base_url"],
        "properties": {
            "base_url": {"type": "string", "description": "The WildlifeNL API root"},
            "sensor_id_source": {
                "type": "string",
                "enum": list(SENSOR_ID_SOURCES),
                "default": DEFAULT_SENSOR_ID_SOURCE,
                "description": "What WildlifeNL sees as sensorID: the device's primary identity "
                "(DevEUI, IMEI or serial), the device name, or the entity id",
            },
            "temperature_metrics": {
                "type": "array",
                "items": {"type": "string"},
                "default": DEFAULT_TEMPERATURE_METRICS,
                "description": "Metric keys delivered as the reading's temperature",
            },
            "sensor_type": {
                "type": "string",
                "enum": list(SENSOR_TYPES),
                "default": DEFAULT_SENSOR_TYPE,
                "description": "The sensor type of species detections",
            },
            "species": {
                "type": "object",
                "description": "Smart Parks species name to a WildlifeNL species name or id, "
                "for names the platform spells differently",
                "additionalProperties": {"type": "string"},
            },
        },
    }
    # the TEST server, where a first integration belongs; the rest has defaults
    config_example: ClassVar[dict[str, Any]] = {"base_url": "https://test-api-wildlifenl.uu.nl"}
    credentials_schema: ClassVar[dict[str, str]] = {
        "token": "Filled by signing in on the integration: the account's email address, then "
        "the code WildlifeNL mails to it. The account needs the data-system role, and the "
        "herd-manager role so Protect can register the animals"
    }
    setup_hint: ClassVar[str] = (
        "Ask the WildlifeNL administrator for an account with the data-system role, and the "
        "herd-manager role so Protect can register the animals. Save the integration with the "
        "server's address, then sign in with the account's email address and the code "
        "WildlifeNL mails to it. Integrate each entity from its own page."
    )

    def __init__(self) -> None:
        self._species: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
        self._documents: dict[str, tuple[datetime, dict[str, Any]]] = {}

    def _client(self, integration: IntegrationContext) -> WildlifeNlClient:
        require_config(integration, "base_url")
        return WildlifeNlClient(
            str(integration.config["base_url"]), str(integration.credentials.get("token") or "")
        )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        if item.object_type == "position":
            return {
                "method": "POST",
                "endpoint": "/borne-sensor-reading/",
                "body": build_position_reading(integration, item),
            }
        if item.object_type == "measurement":
            return {
                "method": "POST",
                "endpoint": "/borne-sensor-reading/",
                "body": build_measurement_reading(integration, item),
            }
        if item.object_type == "event":
            return {
                "method": "POST",
                "endpoint": "/detection/",
                "detections": build_detections(integration, item),
            }
        raise Skipped(f"WildlifeNL cannot receive {item.object_type}s")

    async def species_catalogue(
        self, integration: IntegrationContext, client: WildlifeNlClient
    ) -> list[dict[str, Any]]:
        cached = self._species.get(client.base_url)
        now = datetime.now(UTC)
        if cached and (now - cached[0]).total_seconds() < SPECIES_CACHE_SECONDS:
            return cached[1]
        answer = await client.request("GET", "/species/")
        body = answer.get("body")
        catalogue = [s for s in body if isinstance(s, dict)] if isinstance(body, list) else []
        self._species[client.base_url] = (now, catalogue)
        return catalogue

    async def request_code(self, integration: IntegrationContext, email: str) -> None:
        """`POST /auth/`: the platform mails a code to the address (decision D414)."""
        require_config(integration, "base_url")
        client = WildlifeNlClient(str(integration.config["base_url"]), None)
        await client.request("POST", "/auth/", {"displayNameApp": LOGIN_APP_NAME, "email": email})

    async def exchange_code(
        self, integration: IntegrationContext, email: str, code: str
    ) -> LoginResult:
        """`PUT /auth/` with the code from the email: the answer carries the bearer token and
        the scopes of the account. A wrong or expired code is the platform's 403."""
        require_config(integration, "base_url")
        client = WildlifeNlClient(str(integration.config["base_url"]), None)
        try:
            answer = await client.request("PUT", "/auth/", {"email": email, "code": code.strip()})
        except PermanentFailure as exc:
            if "(403)" in str(exc):
                raise PermanentFailure(
                    "WildlifeNL did not accept the code. It may be mistyped or expired; ask "
                    "for a new one."
                ) from exc
            raise
        body = answer.get("body")
        if not isinstance(body, dict) or not body.get("token"):
            raise PermanentFailure("wildlifenl answered the login without a token")
        return LoginResult(
            credentials={"token": str(body["token"])},
            account=str(body.get("email") or email),
            scopes=[str(scope) for scope in body.get("scopes") or []],
        )

    async def api_document(self, client: WildlifeNlClient) -> dict[str, Any]:
        """The server's own OpenAPI document, kept an hour: it says what this server takes."""
        cached = self._documents.get(client.base_url)
        now = datetime.now(UTC)
        if cached and (now - cached[0]).total_seconds() < API_DOCUMENT_CACHE_SECONDS:
            return cached[1]
        answer = await client.request("GET", "/openapi.json")
        body = answer.get("body")
        if not isinstance(body, dict) or "paths" not in body:
            raise TransientFailure("wildlifenl served no API document at /openapi.json")
        self._documents[client.base_url] = (now, body)
        return body

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        client = self._client(integration)
        endpoint = str(payload["endpoint"])
        if "detections" not in payload:
            response = await client.request("POST", endpoint, dict(payload["body"]))
            return DeliveryResult(external_id=None, response=response)
        mapping = {str(k): str(v) for k, v in (integration.config.get("species") or {}).items()}
        catalogue = await self.species_catalogue(integration, client)
        field = detection_species_field(await self.api_document(client))
        ids: list[str] = []
        responses: list[dict[str, Any]] = []
        for detection in payload["detections"]:
            body = dict(detection)
            name = str(body.pop("species"))
            species = find_species(name, catalogue, mapping)
            if species is None or (field == "speciesName" and not species.get("name")):
                raise PermanentFailure(
                    f"WildlifeNL has no species named {name!r}: add it on the platform or map "
                    "it in the integration's species setting"
                )
            # the Latin name on a server that asks for it, the id on one that does not (D407)
            body[field] = str(species["name"] if field == "speciesName" else species["ID"])
            response = await client.request("POST", endpoint, body)
            answer = response.get("body")
            if isinstance(answer, dict) and answer.get("ID"):
                ids.append(str(answer["ID"]))
            responses.append(response)
        return DeliveryResult(
            external_id=ids[0] if ids else None,
            response={"status": responses[-1]["status"], "detection_ids": ids},
        )

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        client = self._client(integration)
        profile = await client.request("GET", "/profile/me/")
        answer = profile.get("body")
        body: dict[str, Any] = dict(answer) if isinstance(answer, dict) else {}
        roles = [str(r.get("name")) for r in body.get("roles") or [] if isinstance(r, dict)]
        if DATA_SYSTEM_ROLE not in roles:
            raise PermanentFailure(
                f"the WildlifeNL account {body.get('email') or ''} lacks the {DATA_SYSTEM_ROLE} "
                f"role (roles: {', '.join(roles) or 'none'}); readings would be refused"
            )
        catalogue = await self.species_catalogue(integration, client)
        document = await self.api_document(client)
        return {
            "status": profile["status"],
            "account": body.get("email"),
            "roles": roles,
            "can_register_animals": HERD_MANAGER_ROLE in roles,
            "species_count": len(catalogue),
            "api_version": (document.get("info") or {}).get("version"),
            "detection_species_field": detection_species_field(document),
        }

    async def _active_deployments(self, client: WildlifeNlClient) -> dict[str, dict[str, Any]]:
        """The platform's deployments without an end, by sensor id."""
        try:
            answer = await client.request("GET", "/borne-sensor-deployment/active/")
        except PermanentFailure as exc:
            raise PermanentFailure(
                f"WildlifeNL does not show its deployments to this account; it needs the "
                f"{HERD_MANAGER_ROLE} role ({exc})"
            ) from exc
        body = answer.get("body")
        rows = [d for d in body if isinstance(d, dict)] if isinstance(body, list) else []
        return {str(d["sensorID"]): d for d in rows if d.get("sensorID")}

    @staticmethod
    def _deployed(deployment: dict[str, Any] | None, sensor: str | None) -> SubjectStatus:
        if deployment is None:
            return SubjectStatus(registered=False, sensor_id=sensor)
        found = deployment.get("animal")
        animal: dict[str, Any] = found if isinstance(found, dict) else {}
        return SubjectStatus(
            registered=True,
            sensor_id=sensor,
            external_id=str(animal.get("ID") or deployment.get("animalID") or "") or None,
            external_name=str(animal.get("name") or "") or None,
            since=_moment(deployment.get("start")),
        )

    async def statuses(
        self, integration: IntegrationContext, subjects: list[Subject]
    ) -> dict[uuid.UUID, SubjectStatus]:
        client = self._client(integration)
        active = await self._active_deployments(client)
        out: dict[uuid.UUID, SubjectStatus] = {}
        for subject in subjects:
            sensor = sensor_id(integration, subject)
            out[subject.entity_id] = self._deployed(active.get(sensor or ""), sensor)
        return out

    async def options(self, integration: IntegrationContext, subject: Subject) -> SubjectOptions:
        """The platform's species to choose from with Protect's proposal (decisions D411 and
        D413), the sensor id the entity will be known by, and what the platform has for it."""
        client = self._client(integration)
        active = await self._active_deployments(client)
        catalogue = await self.species_catalogue(integration, client)
        sensor = sensor_id(integration, subject)
        mapping = {str(k): str(v) for k, v in (integration.config.get("species") or {}).items()}
        proposal = species_of(subject, catalogue, mapping)
        options = SubjectOptions(
            sensor_id=sensor,
            status=self._deployed(active.get(sensor or ""), sensor),
            species=sorted(
                (
                    SubjectChoice(
                        id=str(s["ID"]),
                        name=str(s.get("name") or ""),
                        common_name=str(s.get("commonName") or "") or None,
                    )
                    for s in catalogue
                    if s.get("ID") and s.get("name")
                ),
                key=lambda choice: (choice.common_name or choice.name).lower(),
            ),
            proposed_species_id=str(proposal["ID"]) if proposal else None,
        )
        if sensor is None:
            options.blocked = "No device is on this entity, so there is no sensor to register"
        elif len(subject.entity_name) < 2:
            options.blocked = "WildlifeNL asks for a name of at least two characters"
        return options

    async def register(
        self,
        integration: IntegrationContext,
        subject: Subject,
        settings: dict[str, Any],
        external_id: str | None,
    ) -> SubjectStatus:
        """An animal and a deployment of its sensor (decision D408), unless the platform has
        a deployment of the sensor already. The animal's id travels in `PartlyRegistered`
        when the deployment is refused after the animal was made, so no second one follows."""
        client = self._client(integration)
        sensor = sensor_id(integration, subject)
        if sensor is None:
            raise PermanentFailure("No device is on this entity, so there is no sensor to register")
        active = await self._active_deployments(client)
        status = self._deployed(active.get(sensor), sensor)
        if status.registered:
            return status
        species = str(settings.get("species_id") or "")
        if not _is_uuid(species):
            raise PermanentFailure("Choose the entity's species on WildlifeNL first")
        animal = external_id
        if animal is None:
            made = await client.request(
                "POST", "/animal/", {"name": subject.entity_name, "speciesID": species}
            )
            body = made.get("body")
            if not isinstance(body, dict) or not body.get("ID"):
                raise PermanentFailure("wildlifenl made an animal without an ID")
            animal = str(body["ID"])
        start = subject.assigned_from or datetime.now(UTC)
        try:
            await client.request(
                "POST",
                "/borne-sensor-deployment/",
                {
                    "animalID": animal,
                    "sensorID": sensor,
                    "contactHardwareAddress": None,
                    "start": iso(start),
                },
            )
        except (PermanentFailure, TransientFailure) as exc:
            raise PartlyRegistered(
                f"WildlifeNL made the animal and refused its sensor: {exc}", external_id=animal
            ) from exc
        return SubjectStatus(
            registered=True,
            sensor_id=sensor,
            external_id=animal,
            external_name=subject.entity_name,
            since=start,
        )


def _moment(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
