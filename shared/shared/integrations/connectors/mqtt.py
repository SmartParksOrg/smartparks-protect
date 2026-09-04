"""MQTT publisher: one message per object on a topic built from a template.

Default topic: `{prefix}/{project_slug}/{object_type}/{subject}` where subject is the entity id
or, without an entity, the device id. The payload is the webhook shape. A broker that cannot be
reached is a transient failure.
"""

import json
from typing import Any, ClassVar

import aiomqtt

from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    PermanentFailure,
    TransientFailure,
)
from shared.integrations.connectors.webhook import object_payload

DEFAULT_TOPIC = "{prefix}/{project_slug}/{object_type}/{subject}"
CONNECT_TIMEOUT = 10


def topic_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    template = str(integration.config.get("topic_template") or DEFAULT_TOPIC)
    values = {
        "prefix": str(integration.config.get("topic_prefix") or "smartparks-protect").strip("/"),
        "project_slug": item.project_slug,
        "project_id": str(item.project_id),
        "object_type": item.object_type,
        "subject": str(item.entity_id or item.device_id or "unknown"),
        "entity_id": str(item.entity_id or ""),
        "device_id": str(item.device_id or ""),
    }
    try:
        topic = template.format(**values)
    except (KeyError, IndexError) as exc:
        raise PermanentFailure(f"topic template uses an unknown placeholder: {exc}") from exc
    return topic.strip("/")


async def publish(
    integration: IntegrationContext, topic: str, body: bytes, *, retain: bool = False
) -> None:
    host = str(integration.config.get("host") or "")
    if not host:
        raise PermanentFailure("mqtt integration without a host")
    try:
        async with aiomqtt.Client(
            host,
            port=int(integration.config.get("port") or 1883),
            username=integration.credentials.get("username"),
            password=integration.credentials.get("password"),
            tls_params=aiomqtt.TLSParameters() if integration.config.get("tls") else None,
            timeout=CONNECT_TIMEOUT,
        ) as client:
            await client.publish(
                topic, body, qos=int(integration.config.get("qos") or 1), retain=retain
            )
    except aiomqtt.MqttError as exc:
        raise TransientFailure(f"mqtt: {exc}") from exc


class MqttConnector:
    key: ClassVar[str] = "mqtt"
    label: ClassVar[str] = "MQTT"
    description: ClassVar[str] = "Publish every forwarded object as JSON to an MQTT broker"
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event", "measurement"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 1883},
            "tls": {"type": "boolean", "default": False},
            "qos": {"type": "integer", "default": 1, "minimum": 0, "maximum": 2},
            "topic_prefix": {"type": "string", "default": "smartparks-protect"},
            "topic_template": {
                "type": "string",
                "default": DEFAULT_TOPIC,
                "description": (
                    "Placeholders: prefix, project_slug, project_id, object_type, subject, "
                    "entity_id, device_id"
                ),
            },
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "host": "broker.example.org",
        "port": 8883,
        "tls": True,
        "topic_prefix": "smartparks-protect",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "username": "Broker username (optional)",
        "password": "Broker password (optional)",
    }
    setup_hint: ClassVar[str] = (
        "Messages are published with QoS 1 and no retain flag; subscribe with a wildcard under "
        "the prefix."
    )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        return {"topic": topic_for(integration, item), "message": object_payload(item)}

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        body = json.dumps(payload["message"], default=str).encode()
        await publish(integration, str(payload["topic"]), body)
        return DeliveryResult(response={"topic": payload["topic"], "bytes": len(body)})

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        prefix = str(integration.config.get("topic_prefix") or "smartparks-protect").strip("/")
        topic = f"{prefix}/test"
        message = {
            "type": "test",
            "message": f"Test from Smart Parks Protect ({integration.name})",
            "latitude": location[0] if location else None,
            "longitude": location[1] if location else None,
        }
        await publish(integration, topic, json.dumps(message).encode())
        return {"topic": topic}
