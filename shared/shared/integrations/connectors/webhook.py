"""Signed webhook: one JSON POST per object, `X-Protect-Signature` when a secret is set.

The body is the same shape for every object type: `type`, `version`, `object` (the canonical
row as JSON), `project`, `entity`, `device`, `link`. Answers of 5xx and network errors are
transient, 4xx permanent.
"""

import hashlib
import hmac
import json
from typing import Any, ClassVar

import httpx

from shared.config import get_settings
from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    PermanentFailure,
    TransientFailure,
    iso,
)

USER_AGENT = "smartparks-protect"


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def object_payload(item: DeliveryItem) -> dict[str, Any]:
    return {
        "type": item.object_type,
        "version": item.object_version,
        "object": {
            "id": item.object_id,
            "time": iso(item.time),
            "latitude": item.location[0] if item.location else None,
            "longitude": item.location[1] if item.location else None,
            **item.data,
        },
        "project": {
            "id": str(item.project_id),
            "name": item.project_name,
            "slug": item.project_slug,
        },
        "entity": (
            {
                "id": str(item.entity_id),
                "name": item.entity_name,
                "type": item.entity_type_key,
            }
            if item.entity_id
            else None
        ),
        "device": (
            {
                "id": str(item.device_id),
                "name": item.device_name,
                "serial_number": item.device_serial,
            }
            if item.device_id
            else None
        ),
        "data_source": item.data_source_name,
        "link": item.link,
    }


async def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    secret: str | None,
    headers: dict[str, str] | None = None,
    delivery_id: str | None = None,
) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise PermanentFailure("webhook url must start with http:// or https://")
    body = json.dumps(payload, default=str).encode()
    sent_headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        **(headers or {}),
    }
    if secret:
        sent_headers["X-Protect-Signature"] = sign(secret, body)
    if delivery_id:
        sent_headers["X-Protect-Delivery"] = delivery_id
    try:
        async with httpx.AsyncClient(timeout=get_settings().webhook_timeout_seconds) as client:
            response = await client.post(url, content=body, headers=sent_headers)
    except httpx.HTTPError as exc:
        raise TransientFailure(f"webhook: {type(exc).__name__}: {exc}") from exc
    summary = {"status": response.status_code, "body": response.text[:500]}
    if response.status_code >= 500:
        raise TransientFailure(f"webhook answered {response.status_code}")
    if response.status_code >= 400:
        raise PermanentFailure(f"webhook answered {response.status_code}: {response.text[:200]}")
    return summary


class WebhookConnector:
    key: ClassVar[str] = "webhook"
    label: ClassVar[str] = "Webhook"
    description: ClassVar[str] = (
        "POST every forwarded object as JSON to a URL; signed with HMAC-SHA256 when a secret is "
        "stored"
    )
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event", "measurement"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "http(s) URL that receives the POSTs"},
            "headers": {
                "type": "object",
                "description": "Extra request headers, for example an Authorization header",
                "additionalProperties": {"type": "string"},
            },
        },
    }
    config_example: ClassVar[dict[str, Any]] = {"url": "https://example.org/hooks/protect"}
    credentials_schema: ClassVar[dict[str, str]] = {
        "secret": "Signing secret (optional); the receiver verifies X-Protect-Signature"
    }
    setup_hint: ClassVar[str] = (
        "The receiver gets one request per position, event or measurement with "
        "X-Protect-Delivery set to the delivery id, so it can deduplicate on retries."
    )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        return object_payload(item)

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        url = str(integration.config.get("url") or "")
        headers = {str(k): str(v) for k, v in (integration.config.get("headers") or {}).items()}
        response = await post_json(
            url,
            payload,
            secret=integration.credentials.get("secret"),
            headers=headers,
            delivery_id=str(payload.get("delivery_id") or "") or None,
        )
        return DeliveryResult(response=response)

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        payload = {
            "type": "test",
            "version": 1,
            "object": {
                "message": f"Test from Smart Parks Protect ({integration.name})",
                "latitude": location[0] if location else None,
                "longitude": location[1] if location else None,
            },
            "project": {"id": str(integration.project_id)},
        }
        return await post_json(
            str(integration.config.get("url") or ""),
            payload,
            secret=integration.credentials.get("secret"),
            headers={str(k): str(v) for k, v in (integration.config.get("headers") or {}).items()},
        )
