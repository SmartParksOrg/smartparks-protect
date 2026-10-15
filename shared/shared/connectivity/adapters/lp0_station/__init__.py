"""Offload stations' SD cards as a data source (phase 42, decisions D319 to D324).

Built in, one for every installation: a tracker offloads its flash log over LP0, a raw LoRa path,
to a nearby offload station (a RangerEdge with an SD card), which stores every frame it received
as a line of a JSONL file. A person carries the card to Protect and uploads its files on the
station's device page. Every line is a delivery on this source (channel `lp0`, ingestion
`file_upload`), addressed by the tracker's LP0 DevAddr, which is the tracker's identity here; the
station is a gateway of this source, so every frame is a reception with its signal. The keys that
verify and decrypt a frame are the tracker's own and live on the device (D320); `unwrap_frame`
is the one place they are applied.
"""

import uuid
from typing import Any, ClassVar

from shared.connectivity.adapters.lp0_station.lorawan import (
    Credentials,
    FrameError,
    Unwrapped,
    unwrap,
)
from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    InboundMessage,
)
from shared.enums import AcquisitionChannel, ErrorCode
from shared.trace import ApplicationError

SOURCE_ID = uuid.UUID("a0000000-0000-0000-0000-0000000000c1")
#: The stored frame formats this version reads: the ordinary LoRaWAN 1.0 uplink the station
#: writes today (named `lorawan` when a line says so, unnamed otherwise).
FRAME_FORMATS = frozenset({"lorawan"})
SOURCE_NAME = "Offload station files"
IDENTITY_TYPE = "dev_addr"


class Lp0StationAdapter:
    key: ClassVar[str] = "lp0_station"
    label: ClassVar[str] = SOURCE_NAME
    push: ClassVar[bool] = False
    builtin: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LP0
    identity_type: ClassVar[str] = IDENTITY_TYPE
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(uplink=True)
    default_link_templates: ClassVar[dict[str, str]] = {}
    config_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    config_example: ClassVar[dict[str, Any]] = {}
    credentials_schema: ClassVar[dict[str, str]] = {}
    setup_hint: ClassVar[str] = (
        "Built in. The files of an offload station's SD card are uploaded on the station's "
        "device page; each tracker's LP0 address and keys are set on the tracker's page. "
        "Nothing to configure here."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="offload station files are uploaded on the station's device page, not "
            "posted to a webhook",
            component="adapter.lp0_station",
            user_actionable=True,
        )

    @staticmethod
    def unwrap_frame(
        phy: bytes,
        credentials: Credentials,
        *,
        last_f_cnt: int | None = None,
        frame_format: str | None = None,
    ) -> Unwrapped:
        """The application payload, port and verified counter of a stored frame, decrypted
        with the tracker's keys; `FrameError` when it is not this device's, does not verify,
        or is of a frame format this version does not read. The firmware (issue 772) may
        version the stored frame or wrap it in an envelope; a line that names a format other
        than the ordinary LoRaWAN frame is refused here by name, never guessed at."""
        if frame_format is not None and frame_format not in FRAME_FORMATS:
            raise FrameError(f"frame format {frame_format!r} is not one this version reads")
        return unwrap(phy, credentials, last_f_cnt=last_f_cnt)


__all__ = [
    "FRAME_FORMATS",
    "IDENTITY_TYPE",
    "SOURCE_ID",
    "SOURCE_NAME",
    "Credentials",
    "FrameError",
    "Lp0StationAdapter",
    "Unwrapped",
]
