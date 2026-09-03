"""Skeleton of a connectivity adapter. Copy to `shared/connectivity/adapters/<provider>/`,
fill in the platform specifics, register it in `shared/connectivity/registry.py`, add recorded
payloads under `tests/fixtures/payloads/<provider>/` and a runbook under
`docs/integrations/<provider>/`.
"""

from typing import Any, ClassVar

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    Emit,
    EventConnector,
    InboundMessage,
)
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, IngestionMethod


class ExamplePlatformConnector:
    """Only for platforms that need a long-running connection (MQTT, polling, websocket).
    Delete this class for push platforms."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def run(self, emit: Emit) -> None:
        # Use a transport from shared/connectivity/transports/ and call emit(InboundMessage)
        # for every message. Return only when cancelled; the ingest service restarts a
        # connector that ends.
        raise NotImplementedError


class ExamplePlatformAdapter:
    key: ClassVar[str] = "example_platform"
    label: ClassVar[str] = "Example platform"
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(uplink=True)
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "https://console.example.org/devices/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return ExamplePlatformConnector(source)  # or None for push platforms

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        data = require_object(body, self.key)
        return [
            InboundMessage(
                external_id=str(data["deviceEUI"]),  # the platform's device identifier
                event_type="uplink",
                payload=data,
                acquisition_channel=AcquisitionChannel.LORAWAN,
                ingestion_method=IngestionMethod.WEBHOOK,
                provider_metadata={"rssi": data.get("rssi")},
                network_received_at=None,  # parse the platform's receive time here
            )
        ]
