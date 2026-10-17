"""One decode path for a frame an offload station stored (phase 43 P6, decision D331).

The decoder's pipeline and Protect Field both turn a card's line into records: the frame is
verified and decrypted with the tracker's own keys, the station's word on who the tracker is
is checked against the registry, and the driver reads the records. The checks and the shape
of what the driver sees live here, with no database in sight, so Field decodes a card on a
laptop exactly as the server does; the pipeline looks the keys and the counter up and writes
the metadata, Field reads them from its bundle. A frame that cannot be decoded is refused
with the same code and words in both.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.connectivity.adapters.lp0_station import FrameError, Lp0StationAdapter
from shared.connectivity.adapters.lp0_station.lorawan import (
    Credentials,
    Unwrapped,
    parse_uplink,
)
from shared.device_drivers.base import DecodedRecords, DeviceDriver, SourceEventData
from shared.enums import AcquisitionChannel, ErrorCode


class FrameRefused(Exception):
    """A frame that is not decoded, with the error code the trace carries and the words a
    person reads; `user_actionable` when a setting of theirs (keys, a serial) is the way out."""

    def __init__(self, code: ErrorCode, message: str, *, user_actionable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.user_actionable = user_actionable


@dataclass(frozen=True, slots=True)
class UnwrappedFrame:
    """The frame opened: the application payload, port and verified 32-bit counter, and the
    16-bit counter the header carries (the pipeline keeps both in the metadata)."""

    payload: bytes
    f_port: int | None
    f_cnt: int
    f_cnt16: int
    dev_addr: str

    @property
    def unwrapped(self) -> Unwrapped:
        return Unwrapped(payload=self.payload, f_port=self.f_port, f_cnt=self.f_cnt)


def unwrap_station_frame(
    phy: bytes,
    credentials: Credentials | None,
    *,
    device_name: str,
    device_eui: str | None,
    source_eui: str | None,
    lp0_version: int | None,
    last_f_cnt: int | None,
) -> UnwrappedFrame:
    """Open a stored frame with the tracker's keys (decisions D320, D321 and D327): refused
    without keys, when the station's `source_eui` contradicts the device the address belongs
    to, when the LP0 metadata version is one this code does not read, and when the frame does
    not verify under the keys."""
    uplink = parse_uplink(phy)
    if credentials is None:
        raise FrameRefused(
            ErrorCode.CREDENTIALS_MISSING,
            f"{device_name} has no LP0 keys; set the address and keys on the device, "
            "then decode again",
        )
    if source_eui and device_eui is not None and source_eui.upper() != device_eui.upper():
        raise FrameRefused(
            ErrorCode.DEVICE_IDENTITY_AMBIGUOUS,
            f"the station says the frame is from tracker {source_eui}, but address "
            f"{uplink.dev_addr} belongs to {device_name} ({device_eui}); check the device's "
            "LP0 address and keys, or its serial, then decode again",
        )
    try:
        unwrapped = Lp0StationAdapter.unwrap_frame(
            phy, credentials, last_f_cnt=last_f_cnt, lp0_version=lp0_version
        )
    except FrameError as exc:
        raise FrameRefused(ErrorCode.PAYLOAD_DECODE_FAILED, str(exc)) from None
    return UnwrappedFrame(
        payload=unwrapped.payload,
        f_port=unwrapped.f_port,
        f_cnt=unwrapped.f_cnt,
        f_cnt16=uplink.f_cnt,
        dev_addr=uplink.dev_addr,
    )


def frame_metadata(frame: UnwrappedFrame) -> dict[str, Any]:
    """What the pipeline writes to the event's provider metadata once a frame is open, and
    what Field passes the driver: the payload in hex, the port and both counters."""
    return {
        "frame_hex": frame.payload.hex(),
        "f_port": frame.f_port,
        "f_cnt": frame.f_cnt16,
        "f_cnt32": frame.f_cnt,
        "mic_ok": True,
    }


def station_event_data(
    frame: UnwrappedFrame,
    *,
    document: dict[str, Any],
    received_at: datetime | None,
    fallback_time: datetime,
    firmware_version: str | None,
    device_attributes: dict[str, Any] | None = None,
    device_type_settings: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceEventData:
    """The delivery as the driver sees it on the `lp0` channel: the station's line as the
    payload, the opened frame and its port, the station's reception time when plausible
    (`received_at`, else `fallback_time`, which only a live message such as the station's own
    statistics takes as its time; a stored stream keeps the times its records carry)."""
    return SourceEventData(
        id=0,
        event_type="uplink",
        payload=document,
        provider_metadata={**(metadata or {}), **frame_metadata(frame)},
        network_received_at=received_at,
        ingested_at=fallback_time,
        device_attributes=dict(device_attributes or {}),
        device_type_settings=dict(device_type_settings or {}),
        frame=frame.payload,
        f_port=frame.f_port,
        acquisition_channel=AcquisitionChannel.LP0,
        firmware_version=firmware_version,
    )


def decode_station_frame(
    driver: DeviceDriver,
    frame: UnwrappedFrame,
    *,
    document: dict[str, Any],
    received_at: datetime | None,
    fallback_time: datetime,
    firmware_version: str | None,
    device_attributes: dict[str, Any] | None = None,
    device_type_settings: dict[str, Any] | None = None,
) -> DecodedRecords:
    """The records of an opened frame, read by the device's driver as the pipeline has it
    read them."""
    return driver.decode(
        station_event_data(
            frame,
            document=document,
            received_at=received_at,
            fallback_time=fallback_time,
            firmware_version=firmware_version,
            device_attributes=device_attributes,
            device_type_settings=device_type_settings,
        )
    )
