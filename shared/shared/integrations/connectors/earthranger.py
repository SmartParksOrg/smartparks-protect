"""EarthRanger, direct (architecture 18.2, decision D84): the site's own API instead of Gundi.

Built from the EarthRanger API primer (`{site}/api/v1.0/docs/topics/api_primer.html`) and the
public client (github.com/PADAS/er-client), fetched 2026-09-04:

- Every request carries `Authorization: Bearer <token>` (an OAuth2 access token created on
  the site), `Accept` and `Content-Type: application/json`.
- Observations of a tracking source: `POST /api/v1.0/sensors/generic/{provider_key}/status`
  with `manufacturer_id` (the source id the site creates on first sight), `location` (`lat`,
  `lon`), `recorded_at`, `subject_name`, `subject_type`, `subject_subtype`, `model_name`,
  `source_type` and `additional`. The provider key belongs to a source provider configured on
  the site.
- Events: `POST /api/v1.0/activity/events` with `event_type` (a slug that exists on the site),
  `time`, `location` (`latitude`, `longitude`), `priority` (0, 100, 200 or 300), `title`,
  `event_details` (the type's schema) and optional `related_subjects`; the answer wraps the
  event in `data` with its `id`. `PATCH /api/v1.0/activity/event/{id}` updates an event, which
  is how a corrected record reaches the site (architecture 28.10).

Identities: as with Gundi, the Smart Parks entity id is the `manufacturer_id`, so a track stays
continuous when a collar is replaced. Observations cannot be updated; a corrected position is
sent again and the site keeps both. Live verification waits for a site and a token.
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

NAMESPACE = "smartparks_protect"
DEFAULT_EVENT_TYPE = f"{NAMESPACE}_event"
DEFAULT_SUBJECT_TYPE = "wildlife"
DEFAULT_PROVIDER_KEY = "smartparks_protect"
REQUEST_TIMEOUT_SECONDS = 30
PRIORITIES: dict[str, int] = {"info": 100, "warning": 200, "critical": 300}


def _mapping(integration: IntegrationContext, key: str) -> dict[str, str]:
    value = integration.config.get(key) or {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def subject_type_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    mapping = _mapping(integration, "subject_types")
    if item.entity_type_key and mapping.get(item.entity_type_key):
        return mapping[item.entity_type_key]
    return str(integration.config.get("default_subject_type") or DEFAULT_SUBJECT_TYPE)


def event_type_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    mapping = _mapping(integration, "event_types")
    smart_parks_type = str(item.data.get("event_type") or "")
    if mapping.get(smart_parks_type):
        return mapping[smart_parks_type]
    return str(integration.config.get("default_event_type") or DEFAULT_EVENT_TYPE)


def build_observation(integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
    if item.entity_id is None:
        raise Skipped("position without an entity: EarthRanger tracks subjects, not devices")
    if item.location is None:
        raise Skipped(f"position {item.object_id} has no location")
    additional: dict[str, Any] = {
        "device_id": str(item.device_id) if item.device_id else None,
        "device_name": item.device_name,
        "data_source": item.data_source_name,
        "project": item.project_name,
        "entity_type": item.entity_type_key,
        "curation_version": item.object_version if item.object_version > 1 else None,
    }
    for key in ("altitude_m", "speed_mps", "heading_deg", "accuracy_m", "satellites"):
        if item.data.get(key) is not None:
            additional[key] = item.data[key]
    return {
        "manufacturer_id": str(item.entity_id),
        "source_type": "tracking-device",
        "subject_name": item.entity_name or str(item.entity_id),
        "subject_type": subject_type_for(integration, item),
        "subject_subtype": item.entity_type_key or subject_type_for(integration, item),
        "model_name": "smartparks-protect",
        "recorded_at": iso(item.time),
        "location": {"lat": item.location[0], "lon": item.location[1]},
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
    body: dict[str, Any] = {
        "event_type": event_type_for(integration, item),
        "time": iso(item.time),
        "priority": PRIORITIES.get(str(item.data.get("severity") or "info"), 100),
        "title": str(item.data.get("title") or item.data.get("event_type") or "Event"),
        "event_details": {k: v for k, v in details.items() if v not in (None, "")},
    }
    if item.location is not None:
        body["location"] = {"latitude": item.location[0], "longitude": item.location[1]}
    return body


def build_test_event(
    integration: IntegrationContext, location: tuple[float, float]
) -> dict[str, Any]:
    return {
        "event_type": str(integration.config.get("default_event_type") or DEFAULT_EVENT_TYPE),
        "time": iso(datetime.now(UTC)),
        "priority": 100,
        "title": f"Test from Smart Parks Protect ({integration.name})",
        "location": {"latitude": location[0], "longitude": location[1]},
        "event_details": {
            f"{NAMESPACE}_event_type": "TEST",
            f"{NAMESPACE}_severity": "info",
            f"{NAMESPACE}_project": integration.name,
        },
    }


def parse_object_id(body: Any) -> str | None:
    if isinstance(body, dict):
        inner = body.get("data")
        data: dict[str, Any] = inner if isinstance(inner, dict) else body
        if data.get("id"):
            return str(data["id"])
    return None


class EarthRangerClient:
    def __init__(self, base_url: str, token: str) -> None:
        if not token:
            raise PermanentFailure("the EarthRanger integration has no token credential")
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def send(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", json=payload, headers=self.headers
                )
        except httpx.HTTPError as exc:
            raise TransientFailure(f"earthranger: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientFailure(f"earthranger answered {response.status_code}")
        if response.status_code >= 400:
            raise PermanentFailure(
                f"earthranger answered {response.status_code}: {response.text[:300]}"
            )
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:300]}
        return {"status": response.status_code, "body": body}


class EarthRangerConnector:
    key: ClassVar[str] = "earthranger"
    label: ClassVar[str] = "EarthRanger (direct API)"
    description: ClassVar[str] = (
        "Positions become observations of a generic sensor source and events become "
        "EarthRanger events on the site itself; corrected events are updated in place"
    )
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["base_url"],
        "properties": {
            "base_url": {"type": "string", "description": "The site, https://<site>.pamdas.org"},
            "provider_key": {
                "type": "string",
                "default": DEFAULT_PROVIDER_KEY,
                "description": "Source provider key on the site for the generic sensor endpoint",
            },
            "default_subject_type": {"type": "string", "default": DEFAULT_SUBJECT_TYPE},
            "subject_types": {
                "type": "object",
                "description": "Entity type key to EarthRanger subject type",
                "additionalProperties": {"type": "string"},
            },
            "default_event_type": {"type": "string", "default": DEFAULT_EVENT_TYPE},
            "event_types": {
                "type": "object",
                "description": "Smart Parks event type to EarthRanger event type slug",
                "additionalProperties": {"type": "string"},
            },
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "base_url": "https://smartparks.pamdas.org",
        "provider_key": DEFAULT_PROVIDER_KEY,
        "default_subject_type": "wildlife",
        "subject_types": {"rhino": "rhino", "elephant": "elephant"},
        "default_event_type": DEFAULT_EVENT_TYPE,
        "event_types": {"GEOFENCE_EXIT": f"{NAMESPACE}_geofence"},
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "token": "OAuth2 access token created on the site (admin, OAuth2 provider, access tokens)"
    }
    setup_hint: ClassVar[str] = (
        f"On the site create a source provider with key `{DEFAULT_PROVIDER_KEY}` and the event "
        f"type `{DEFAULT_EVENT_TYPE}` whose schema holds the `{NAMESPACE}_*` keys, or map every "
        "Smart Parks event type to an existing slug. Send a test event first."
    )

    def _client(self, integration: IntegrationContext) -> EarthRangerClient:
        require_config(integration, "base_url")
        return EarthRangerClient(
            str(integration.config["base_url"]), str(integration.credentials.get("token") or "")
        )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        if item.object_type == "position":
            provider = str(integration.config.get("provider_key") or DEFAULT_PROVIDER_KEY)
            return {
                "method": "POST",
                "endpoint": f"/api/v1.0/sensors/generic/{provider}/status",
                "body": build_observation(integration, item),
            }
        if item.object_type == "event":
            body = build_event(integration, item)
            if item.previous_external_id:
                return {
                    "method": "PATCH",
                    "endpoint": f"/api/v1.0/activity/event/{item.previous_external_id}",
                    "body": body,
                }
            return {"method": "POST", "endpoint": "/api/v1.0/activity/events", "body": body}
        raise Skipped(f"EarthRanger cannot receive {item.object_type}s")

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        response = await self._client(integration).send(
            str(payload.get("method") or "POST"), str(payload["endpoint"]), dict(payload["body"])
        )
        external_id = parse_object_id(response.get("body")) or item.previous_external_id
        return DeliveryResult(external_id=external_id, response=response)

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        if location is None:
            raise PermanentFailure(
                "a test event needs coordinates: pass latitude and longitude, or give the "
                "project an entity with a position"
            )
        return await self._client(integration).send(
            "POST", "/api/v1.0/activity/events", build_test_event(integration, location)
        )
