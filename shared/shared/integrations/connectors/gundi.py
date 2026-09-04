"""EarthRanger through Gundi (architecture 18.2, decisions D15 and D62).

Gundi Sensors API v2 (https://support.earthranger.com/developer_docs/gundi-api):
    POST {base}/observations/   {source, source_name, subject_type, recorded_at,
                                 location: {lat, lon}, additional}
    POST {base}/events/         {source, title, event_type, recorded_at,
                                 location: {lat, lon}, event_details}
Both take the `apikey` header and answer `{"object_id": ..., "created_at": ...}`. Timestamps
carry an offset. Gundi forwards to the EarthRanger site the connection points at; the event
type slug must exist on that site with a schema whose keys match `event_details`.

Identities (D62): the Smart Parks entity id is the Gundi `source` and the entity name the
`source_name`, so an EarthRanger track stays continuous when a collar is replaced. The subject
type comes from the integration's `subject_types` map (entity type key to EarthRanger subject
type) with `default_subject_type` as fallback. Event types use `smartparks_protect_` as the
namespace, like AddaxAI Connect uses `addaxai_connect_`.
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
)

GUNDI_BASE_URL = "https://sensors.api.gundiservice.org/v2"
NAMESPACE = "smartparks_protect"
DEFAULT_EVENT_TYPE = f"{NAMESPACE}_event"
DEFAULT_SUBJECT_TYPE = "wildlife"
REQUEST_TIMEOUT_SECONDS = 30
TEST_SOURCE = "smartparks-protect-test"


def subject_type_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    mapping = integration.config.get("subject_types") or {}
    if item.entity_type_key and isinstance(mapping, dict) and mapping.get(item.entity_type_key):
        return str(mapping[item.entity_type_key])
    return str(integration.config.get("default_subject_type") or DEFAULT_SUBJECT_TYPE)


def event_type_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    mapping = integration.config.get("event_types") or {}
    smart_parks_type = str(item.data.get("event_type") or "")
    if isinstance(mapping, dict) and mapping.get(smart_parks_type):
        return str(mapping[smart_parks_type])
    return str(integration.config.get("default_event_type") or DEFAULT_EVENT_TYPE)


def _location(item: DeliveryItem) -> dict[str, float]:
    if item.location is None:
        raise Skipped(f"{item.object_type} {item.object_id} has no location to place on the map")
    return {"lat": item.location[0], "lon": item.location[1]}


def build_observation(integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
    if item.entity_id is None:
        raise Skipped("position without an entity: EarthRanger tracks subjects, not devices")
    additional: dict[str, Any] = {
        "device_id": str(item.device_id) if item.device_id else None,
        "device_name": item.device_name,
        "data_source": item.data_source_name,
        "project": item.project_name,
        "entity_type": item.entity_type_key,
    }
    for key in ("altitude_m", "speed_mps", "heading_deg", "accuracy_m", "satellites"):
        if item.data.get(key) is not None:
            additional[key] = item.data[key]
    return {
        "source": str(item.entity_id),
        "source_name": item.entity_name or str(item.entity_id),
        "subject_type": subject_type_for(integration, item),
        "recorded_at": iso(item.time),
        "location": _location(item),
        "additional": {k: v for k, v in additional.items() if v is not None},
    }


def build_event(integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
    details: dict[str, Any] = {
        f"{NAMESPACE}_event_type": item.data.get("event_type"),
        f"{NAMESPACE}_severity": item.data.get("severity"),
        f"{NAMESPACE}_entity": item.entity_name,
        f"{NAMESPACE}_device": item.device_name,
        f"{NAMESPACE}_project": item.project_name,
        f"{NAMESPACE}_description": item.data.get("description"),
        f"{NAMESPACE}_event_id": item.object_id,
    }
    if item.link:
        details[f"{NAMESPACE}_link"] = item.link
    if item.location_is_fallback:
        details[f"{NAMESPACE}_location_note"] = "entity's last known position"
    return {
        "source": str(item.entity_id) if item.entity_id else TEST_SOURCE,
        "title": str(item.data.get("title") or item.data.get("event_type") or "Event"),
        "event_type": event_type_for(integration, item),
        "recorded_at": iso(item.time),
        "location": _location(item),
        "event_details": {k: v for k, v in details.items() if v not in (None, "")},
    }


def build_test_event(
    integration: IntegrationContext, location: tuple[float, float]
) -> dict[str, Any]:
    return {
        "source": TEST_SOURCE,
        "title": f"Test from Smart Parks Protect ({integration.name})",
        "event_type": str(integration.config.get("default_event_type") or DEFAULT_EVENT_TYPE),
        "recorded_at": iso(datetime.now(UTC)),
        "location": {"lat": location[0], "lon": location[1]},
        "event_details": {
            f"{NAMESPACE}_event_type": "TEST",
            f"{NAMESPACE}_severity": "info",
            f"{NAMESPACE}_project": integration.name,
        },
    }


def parse_object_id(body: Any) -> str | None:
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict) and body.get("object_id"):
        return str(body["object_id"])
    return None


class GundiClient:
    def __init__(self, api_key: str, base_url: str = GUNDI_BASE_URL) -> None:
        if not api_key:
            raise PermanentFailure("the Gundi integration has no api_key credential")
        self.headers = {"apikey": api_key}
        self.base_url = base_url.rstrip("/")

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.base_url}{path}", json=payload, headers=self.headers
                )
        except httpx.HTTPError as exc:
            raise TransientFailure(f"gundi: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientFailure(f"gundi answered {response.status_code}")
        if response.status_code >= 400:
            raise PermanentFailure(f"gundi answered {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:300]}
        return {"status": response.status_code, "body": body}


class GundiConnector:
    key: ClassVar[str] = "gundi"
    label: ClassVar[str] = "EarthRanger via Gundi"
    description: ClassVar[str] = (
        "Positions become observations and events become EarthRanger events through the Gundi "
        "Sensors API; the Gundi connection selects the EarthRanger site"
    )
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "base_url": {"type": "string", "default": GUNDI_BASE_URL},
            "default_subject_type": {
                "type": "string",
                "default": DEFAULT_SUBJECT_TYPE,
                "description": "EarthRanger subject type for entities without a mapping",
            },
            "subject_types": {
                "type": "object",
                "description": "Entity type key to EarthRanger subject type",
                "additionalProperties": {"type": "string"},
            },
            "default_event_type": {
                "type": "string",
                "default": DEFAULT_EVENT_TYPE,
                "description": "EarthRanger event type slug; must exist on the site",
            },
            "event_types": {
                "type": "object",
                "description": "Smart Parks event type to EarthRanger event type slug",
                "additionalProperties": {"type": "string"},
            },
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "default_subject_type": "wildlife",
        "subject_types": {"rhino": "rhino", "elephant": "elephant", "vehicle": "vehicle"},
        "default_event_type": DEFAULT_EVENT_TYPE,
        "event_types": {"GEOFENCE_EXIT": f"{NAMESPACE}_geofence"},
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "api_key": "API key of the Gundi connection (Gundi portal, Connections)"
    }
    setup_hint: ClassVar[str] = (
        "In the Gundi portal create a connection from a Smart Parks Protect source to the "
        f"EarthRanger site. On the site create the event type `{DEFAULT_EVENT_TYPE}` with the "
        f"`{NAMESPACE}_*` keys as its schema, or map every Smart Parks event type to an "
        "existing slug. Send a test event first."
    )

    def _client(self, integration: IntegrationContext) -> GundiClient:
        return GundiClient(
            str(integration.credentials.get("api_key") or ""),
            str(integration.config.get("base_url") or GUNDI_BASE_URL),
        )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        if item.object_type == "position":
            return {"endpoint": "/observations/", "body": build_observation(integration, item)}
        if item.object_type == "event":
            return {"endpoint": "/events/", "body": build_event(integration, item)}
        raise Skipped(f"Gundi cannot receive {item.object_type}s")

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        response = await self._client(integration).post(
            str(payload["endpoint"]), dict(payload["body"])
        )
        return DeliveryResult(external_id=parse_object_id(response.get("body")), response=response)

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        if location is None:
            raise PermanentFailure(
                "a test event needs coordinates: pass latitude and longitude, or give the "
                "project an entity with a position"
            )
        return await self._client(integration).post(
            "/events/", build_test_event(integration, location)
        )
