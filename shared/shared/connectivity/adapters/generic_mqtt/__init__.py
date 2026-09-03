"""Generic MQTT source: subscribe to topics on any broker, JSON payloads.

Config keys: `host`, `port` (1883), `tls` (false), `topics` (list of filters), and how to find the
device identifier: `external_id_from` is `topic` (default) with `topic_template` such as
`devices/{external_id}/up`, or `payload` with `external_id_field`. Credentials: `username`,
`password`.
"""

import json
import re
from typing import Any, ClassVar

from shared.connectivity.adapters.generic_http import dotted_get, parse_time
from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    Emit,
    EventConnector,
    InboundMessage,
)
from shared.connectivity.transports.mqtt import MqttSettings, subscribe_forever
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.generic_mqtt")


def topic_pattern(template: str) -> re.Pattern[str]:
    escaped = re.escape(template).replace(r"\{external_id\}", r"(?P<external_id>[^/]+)")
    escaped = escaped.replace(r"\+", r"[^/]+").replace(r"\#", r".*")
    return re.compile("^" + escaped + "$")


def parse_message(source: DataSourceContext, topic: str, payload: bytes) -> InboundMessage:
    config = source.config
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=f"payload is not JSON: {exc}",
            component="adapter.generic_mqtt",
            context={"topic": topic},
        ) from exc
    if not isinstance(data, dict):
        data = {"value": data}
    external_id: str | None
    if config.get("external_id_from", "topic") == "topic":
        match = topic_pattern(config.get("topic_template", "devices/{external_id}/+")).match(topic)
        external_id = match.group("external_id") if match else None
    else:
        value = dotted_get(data, config.get("external_id_field", "device_id"))
        external_id = str(value) if value is not None else None
    return InboundMessage(
        external_id=external_id,
        event_type=str(
            dotted_get(data, config.get("event_type_field", "type"))
            or config.get("default_event_type", "uplink")
        ),
        payload=data,
        acquisition_channel=AcquisitionChannel(config.get("acquisition_channel", "other")),
        ingestion_method=IngestionMethod.MQTT,
        provider_metadata={"topic": topic},
        network_received_at=parse_time(
            dotted_get(data, config.get("time_field", "received_at")), "generic_mqtt"
        ),
        identity_type=config.get("identity_type", "dev_eui"),
    )


class GenericMqttConnector:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def run(self, emit: Emit) -> None:
        config, credentials = self.source.config, self.source.credentials
        settings = MqttSettings(
            host=config["host"],
            port=int(config.get("port", 1883)),
            username=credentials.get("username"),
            password=credentials.get("password"),
            tls=bool(config.get("tls", False)),
            client_id=f"protect-ingest-{self.source.id.hex[:8]}",
        )

        async def callback(topic: str, payload: bytes) -> None:
            try:
                message = parse_message(self.source, topic, payload)
            except ApplicationError as error:
                log.warning(
                    "mqtt message dropped", source=self.source.name, topic=topic, error=str(error)
                )
                return
            await emit(message)

        await subscribe_forever(settings, list(config.get("topics", ["devices/#"])), callback)


class GenericMqttAdapter:
    key: ClassVar[str] = "generic_mqtt"
    label: ClassVar[str] = "Generic MQTT broker"
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(uplink=True)
    default_link_templates: ClassVar[dict[str, str]] = {}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer", "default": 1883},
            "tls": {"type": "boolean", "default": False},
            "topics": {"type": "array", "items": {"type": "string"}, "default": ["devices/#"]},
            "external_id_from": {
                "type": "string",
                "enum": ["topic", "payload"],
                "default": "topic",
            },
            "topic_template": {"type": "string", "default": "devices/{external_id}/+"},
            "external_id_field": {"type": "string", "default": "device_id"},
            "event_type_field": {"type": "string", "default": "type"},
            "default_event_type": {"type": "string", "default": "uplink"},
            "time_field": {"type": "string", "default": "received_at"},
            "identity_type": {"type": "string", "default": "dev_eui"},
            "acquisition_channel": {"type": "string", "default": "other"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return GenericMqttConnector(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="generic_mqtt has no webhook endpoint",
            component="adapter.generic_mqtt",
        )
