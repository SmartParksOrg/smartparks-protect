"""Raw log file uploads as a data source (architecture 25.6, decision D77).

Built in: a person uploads a raw log file retrieved from a device (the `.txt` the public BLE
app exports, one base64 frame per line) and associates it with the device. Every frame becomes
a delivery on this source (channel `log_file`, ingestion `file_upload`); the file itself is a
managed asset (`device_log_files`).
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

SOURCE_ID = uuid.UUID("a0000000-0000-0000-0000-0000000000f1")
SOURCE_NAME = "Log file upload"
IDENTITY_TYPE = "device_id"


class LogFileAdapter:
    key: ClassVar[str] = "log_file"
    label: ClassVar[str] = SOURCE_NAME
    push: ClassVar[bool] = False
    builtin: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LOG_FILE
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(uplink=True)
    default_link_templates: ClassVar[dict[str, str]] = {}
    config_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    config_example: ClassVar[dict[str, Any]] = {}
    credentials_schema: ClassVar[dict[str, str]] = {}
    setup_hint: ClassVar[str] = (
        "Built in. Raw log files uploaded on a device page are decoded through this source; "
        "nothing to configure."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="log files are uploaded on the device page, not posted to a webhook",
            component="adapter.log_file",
            user_actionable=True,
        )
