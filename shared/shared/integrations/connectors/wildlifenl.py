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
has no free-form events, its interactions are people's reports. Live verification waits for
the platform's URL and a data-system account.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    PermanentFailure,
    Skipped,
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
DATA_SYSTEM_ROLE = "data-system"


def sensor_id_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    source = str(integration.config.get("sensor_id_source") or DEFAULT_SENSOR_ID_SOURCE)
    if source == "device_name":
        value = item.device_name
    elif source == "entity_id":
        value = str(item.entity_id) if item.entity_id else None
    else:
        value = item.device_identity or item.device_serial or item.device_name
    if not value or len(value) < 2:
        raise Skipped(f"no sensor id for {item.object_type} {item.object_id} ({source})")
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


def resolve_species(
    name: str, catalogue: list[dict[str, Any]], mapping: dict[str, str]
) -> str | None:
    """The WildlifeNL species id for a Smart Parks species name: the integration's own
    mapping first (to a name or an id), then the Latin or common name, case-insensitive."""
    wanted = mapping.get(name) or mapping.get(name.lower()) or name
    if _is_uuid(wanted):
        return wanted
    lowered = wanted.strip().lower().replace("_", " ")
    for species in catalogue:
        candidates = {
            str(species.get("name") or "").lower(),
            str(species.get("commonName") or "").lower(),
        }
        if lowered in candidates and species.get("ID"):
            return str(species["ID"])
    return None


class WildlifeNlClient:
    def __init__(self, base_url: str, token: str) -> None:
        if not token:
            raise PermanentFailure("the WildlifeNL integration has no token credential")
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

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
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientFailure(f"wildlifenl answered {response.status_code}")
        if response.status_code in (401, 403):
            raise PermanentFailure(
                f"wildlifenl refused the token ({response.status_code}): {response.text[:300]}"
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
    config_example: ClassVar[dict[str, Any]] = {
        "base_url": "https://api.wildlifenl.example",
        "sensor_id_source": DEFAULT_SENSOR_ID_SOURCE,
        "temperature_metrics": DEFAULT_TEMPERATURE_METRICS,
        "sensor_type": DEFAULT_SENSOR_TYPE,
        "species": {"wild_boar": "Sus scrofa", "red_deer": "Cervus elaphus"},
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "token": "Bearer token of a WildlifeNL account with the data-system role, from the "
        "email code login (POST /auth/, then PUT /auth/ with the code)"
    }
    setup_hint: ClassVar[str] = (
        "Ask the WildlifeNL administrator for an account with the data-system role, log in "
        "once through the API's own page to receive the token, and let a herd manager register "
        "each collar's identity as a borne sensor deployment on its animal. Species names must "
        "exist on the platform or be mapped. Test the connection first."
    )

    def __init__(self) -> None:
        self._species: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}

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
        ids: list[str] = []
        responses: list[dict[str, Any]] = []
        for detection in payload["detections"]:
            body = dict(detection)
            name = str(body.pop("species"))
            species_id = resolve_species(name, catalogue, mapping)
            if species_id is None:
                raise PermanentFailure(
                    f"WildlifeNL has no species named {name!r}: add it on the platform or map "
                    "it in the integration's species setting"
                )
            body["speciesID"] = species_id
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
        return {
            "status": profile["status"],
            "account": body.get("email"),
            "roles": roles,
            "species_count": len(catalogue),
        }
