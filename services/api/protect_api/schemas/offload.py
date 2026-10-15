"""Offload stations and the trackers' LP0 credentials (phase 42, decisions D319 to D324)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.log_files import DeviceLogFileRead


class Lp0Readback(BaseModel):
    """What the device itself reported of its LP0 settings (the settings table, D228): the
    address in the clear, and whether the two keys are known, never their values."""

    dev_addr: str | None = None
    app_key_known: bool = False
    network_key_known: bool = False
    observed_at: datetime | None = None


class Lp0CredentialsRead(BaseModel):
    dev_addr: str | None = Field(default=None, description="Eight uppercase hex digits")
    keys_set: bool = False
    app_s_key: str | None = Field(
        default=None,
        description="The application session key as 32 hex digits, for a caller who may set "
        "the keys (device control in the project, or a server admin); null for a viewer",
    )
    nwk_s_key: str | None = Field(default=None, description="The network session key, the same")
    set_at: datetime | None = None
    source: str | None = Field(default=None, description="person or device")
    readback: Lp0Readback = Field(default_factory=Lp0Readback)
    frames_waiting: int = Field(
        default=0,
        description="Frames stored for this address before the device had it, waiting for "
        "the decoder's walk",
    )


class Lp0CredentialsUpdate(BaseModel):
    """The address and both keys typed in, or `from_device` to take the three values the
    device reported in its settings readback."""

    dev_addr: str | None = Field(default=None, max_length=16)
    app_s_key: str | None = Field(default=None, max_length=48)
    nwk_s_key: str | None = Field(default=None, max_length=48)
    from_device: bool = False


class Lp0CredentialsResult(Lp0CredentialsRead):
    queued: int = Field(default=0, description="Retained frames handed to the decoder's walk")


class SkippedMember(BaseModel):
    name: str
    reason: str


class OffloadUpload(BaseModel):
    files: list[DeviceLogFileRead]
    skipped: list[SkippedMember] = Field(default_factory=list)
    other_station: list[str] = Field(
        default_factory=list,
        description="Files named after another station's EUI, accepted as they are",
    )


class OffloadTracker(BaseModel):
    dev_addr: str | None = None
    device_id: uuid.UUID | None = None
    device_name: str | None = None
    frames: int = 0
    last_reception_at: datetime | None = None
    mean_rssi: float | None = None


class OffloadStationRead(BaseModel):
    """What a station's card brought to Protect: the files, their frames and records, the
    trackers it served in the last 30 days, and the station's own report when it sent one."""

    device_id: uuid.UUID
    station_eui: str | None = None
    is_station: bool = Field(description="The device has received files or reports as a station")
    files: int = 0
    frames: int = 0
    frames_retained: int = 0
    frames_repeated: int = 0
    records_new: int = 0
    records_known: int = 0
    last_upload_at: datetime | None = None
    last_reception_at: datetime | None = None
    trackers: list[OffloadTracker] = Field(default_factory=list)
    state: dict[str, Any] | None = Field(
        default=None, description="The station's last port 23 report (decision D323)"
    )
    state_time: datetime | None = None
