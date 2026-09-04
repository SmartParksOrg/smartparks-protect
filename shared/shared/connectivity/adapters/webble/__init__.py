"""The browser as a data source (architecture 25.4, decision D77).

Not an external platform: a person connects a nearby OpenCollar over Web Bluetooth in the
Smart Parks Protect frontend, and the browser hands every notification frame to the API as a
delivery on this built-in source (channel `webble`, ingestion `browser_sync`). Commands over
this route are written by the browser too (decision D79): the command connector only queues
the command; the browser fetches it, writes the frame and the confirmation comes back through
the synced frames. The route is never selected automatically.
"""

import uuid
from typing import Any, ClassVar

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    InboundMessage,
)
from shared.enums import AcquisitionChannel, ErrorCode
from shared.trace import ApplicationError

SOURCE_ID = uuid.UUID("a0000000-0000-0000-0000-0000000000b1")
SOURCE_NAME = "Browser (WebBLE)"
IDENTITY_TYPE = "device_id"


class BrowserCommands:
    """The browser executes the command; the platform stage is 'queued for the browser'."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "provider_ref": options.get("reference"),
            "statuses": ["queued"],
            "executor": "browser",
            "frame_hex": bytes([int(options["f_port"])]).hex() + payload.hex(),
        }


class WebBleAdapter:
    key: ClassVar[str] = "webble"
    label: ClassVar[str] = SOURCE_NAME
    push: ClassVar[bool] = False
    builtin: ClassVar[bool] = True
    requires_client: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.WEBBLE
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True, downlink=True
    )
    default_link_templates: ClassVar[dict[str, str]] = {}
    config_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    config_example: ClassVar[dict[str, Any]] = {}
    credentials_schema: ClassVar[dict[str, str]] = {}
    setup_hint: ClassVar[str] = (
        "Built in. Frames read from a device over Web Bluetooth in this application arrive "
        "here; nothing to configure."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def command_connector(self, source: DataSourceContext) -> BrowserCommands:
        return BrowserCommands(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="the WebBLE source takes frames through the device sync endpoint, not a "
            "webhook",
            component="adapter.webble",
            user_actionable=True,
        )
