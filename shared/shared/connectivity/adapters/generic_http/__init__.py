"""Generic HTTP push source.

Any platform or device that can POST JSON with a bearer token. Config keys:

- `external_id_field` (default `device_id`): JSON pointer-like dotted path to the device identifier
- `event_type_field` (default `type`), `default_event_type` (default `uplink`)
- `time_field` (default `received_at`): when the platform received the message, ISO 8601 with
  offset or unix seconds, optional. The device's own time stays in the payload for the driver.
- `identity_type` (default `dev_eui`)
- `batch_field`: when set, the body holds a list of messages under this key
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    InboundMessage,
)
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.timeutil import require_aware
from shared.trace import ApplicationError


def dotted_get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def parse_time(value: Any, adapter: str = "generic_http") -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=UTC)
        return require_aware(datetime.fromisoformat(str(value)))
    except (ValueError, OverflowError, OSError) as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"received time {value!r} is not a timestamp with offset: {exc}",
            component=f"adapter.{adapter}",
            user_actionable=True,
        ) from exc


class GenericHttpAdapter:
    key: ClassVar[str] = "generic_http"
    label: ClassVar[str] = "Generic HTTP webhook"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.API
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(uplink=True)
    default_link_templates: ClassVar[dict[str, str]] = {}
    config_example: ClassVar[dict[str, Any]] = {
        "external_id_field": "device_id",
        "event_type_field": "type",
        "time_field": "received_at",
    }
    credentials_schema: ClassVar[dict[str, str]] = {}
    setup_hint: ClassVar[str] = (
        "POST JSON to the webhook URL of this data source with the bearer token."
    )
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "external_id_field": {"type": "string", "default": "device_id"},
            "event_type_field": {"type": "string", "default": "type"},
            "default_event_type": {"type": "string", "default": "uplink"},
            "time_field": {"type": "string", "default": "received_at"},
            "identity_type": {"type": "string", "default": "dev_eui"},
            "batch_field": {"type": "string"},
            "acquisition_channel": {"type": "string", "default": "api"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        config = source.config
        batch_field = config.get("batch_field")
        if batch_field:
            container = require_object(body, self.key)
            items = container.get(batch_field)
            if not isinstance(items, list):
                items = []
        else:
            items = [body]
        messages = []
        for item in items:
            data = require_object(item, self.key)
            external_id = dotted_get(data, config.get("external_id_field", "device_id"))
            event_type = dotted_get(data, config.get("event_type_field", "type")) or config.get(
                "default_event_type", "uplink"
            )
            messages.append(
                InboundMessage(
                    external_id=str(external_id) if external_id is not None else None,
                    event_type=str(event_type),
                    payload=data,
                    acquisition_channel=AcquisitionChannel(
                        config.get("acquisition_channel", "api")
                    ),
                    ingestion_method=IngestionMethod.WEBHOOK,
                    provider_metadata={"user_agent": headers.get("user-agent", "")},
                    network_received_at=parse_time(
                        dotted_get(data, config.get("time_field", "received_at"))
                    ),
                    identity_type=config.get("identity_type", "dev_eui"),
                )
            )
        return messages
