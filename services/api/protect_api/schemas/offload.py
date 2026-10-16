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


class OffloadOverviewStation(BaseModel):
    """One offload station of the project on the Offload page: its device, its entity when it
    has one, what its cards brought, and the gist of its own last report."""

    device_id: uuid.UUID
    device_name: str
    station_eui: str | None = None
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    gateway_id: uuid.UUID | None = Field(default=None, description="Its row on the Gateways page")
    has_location: bool = False
    files: int = 0
    frames: int = 0
    frames_retained: int = Field(default=0, description="Frames of addresses no device has")
    last_upload_at: datetime | None = None
    trackers: int = Field(default=0, description="Trackers served in the window")
    receptions: int = Field(default=0, description="Frames received in the window")
    last_reception_at: datetime | None = None
    card_ok: bool | None = Field(default=None, description="From the station's own report")
    listening: bool | None = None
    storage_pending: int | None = None
    visits_complete: int | None = None
    state_time: datetime | None = None


class OffloadOverviewTracker(BaseModel):
    """One tracker of the project on the Offload page: its address and whether its keys are
    set, never the keys, and what the stations received of it in the window."""

    device_id: uuid.UUID
    device_name: str
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    dev_addr: str | None = None
    keys_set: bool = False
    source: str | None = Field(default=None, description="person or device")
    set_at: datetime | None = None
    reported_dev_addr: str | None = Field(
        default=None, description="The address the device itself last reported in its settings"
    )
    last_f_cnt: int | None = None
    last_frame_at: datetime | None = Field(
        default=None, description="The last frame verified under the device's keys"
    )
    receptions: int = 0
    stations: int = Field(default=0, description="Stations that received it in the window")
    last_reception_at: datetime | None = None
    last_station_device_id: uuid.UUID | None = None
    last_station_name: str | None = None


class OffloadUnknownAddress(BaseModel):
    """An address the project's stations received that no device has: Needs attention links it."""

    dev_addr: str
    dev_eui: str | None = Field(default=None, description="The tracker's EUI when a line named it")
    receptions: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class OffloadOverviewRead(BaseModel):
    """The project's LP0 network on one page (phase 42): every offload station, every tracker
    with an address or frames, the addresses nobody has, and how many of the project's devices
    have no address yet."""

    window_days: int
    stations: list[OffloadOverviewStation] = Field(default_factory=list)
    trackers: list[OffloadOverviewTracker] = Field(default_factory=list)
    unknown: list[OffloadUnknownAddress] = Field(default_factory=list)
    devices_without_address: int = Field(
        default=0, description="Devices of the project with no LP0 address, stations apart"
    )
