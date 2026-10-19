"""Offload stations and the trackers' LP0 credentials (phase 42, decisions D319 to D324)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

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
    """The address and both keys typed in, the address alone to claim the frames a card holds
    for it while the keys follow (decision D338), or `from_device` to take the three values the
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
    is_station: bool = Field(
        description="The device has received files or reports as a station, or was set up as one"
    )
    mobile: bool = Field(default=False, description="The station reports its own position (D336)")
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
    mobile: bool = Field(
        default=False,
        description="The station travels and reports its own position (decision D336); its "
        "location is then its last known position, not a place set by hand",
    )
    has_location: bool = False
    location: dict[str, Any] | None = Field(
        default=None,
        description="Where the Offload page's map draws it: the place set by hand, or a "
        "mobile station's last known position, as a GeoJSON point",
    )
    location_at: datetime | None = Field(
        default=None, description="When a mobile station's last known position was taken"
    )
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
    entity_icon: str | None = Field(default=None, description="The entity type's icon key")
    last_position: dict[str, Any] | None = Field(
        default=None, description="Its last known position as a GeoJSON point, for the map"
    )
    last_position_at: datetime | None = None
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


class OffloadStationSetup(BaseModel):
    """Make a device of the project an offload station from the Offload page, or complete one
    that is missing a piece (Tim, 2026-10-16): the Offload station entity (the entity the device
    tracks today is kept; else an entity of the project by id, or a new Offload station entity
    with this name, the device's name by default), its place when given, and its gateway row on
    the offload station source, which otherwise waits for the first card."""

    device_id: uuid.UUID
    entity_id: uuid.UUID | None = Field(
        default=None, description="An entity of the project, when the device tracks none today"
    )
    entity_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="The name of a new Offload station entity, when the device tracks none today",
    )
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    mobile: bool | None = Field(
        default=None,
        description="A mobile station travels and reports its own position, like a tracker "
        "(decision D336); a static one, the default, stands where a person placed it. "
        "Left out, the station stays as it is",
    )

    @model_validator(mode="after")
    def _consistent(self) -> "OffloadStationSetup":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude go together")
        if self.mobile and self.latitude is not None:
            raise ValueError("a mobile station has no place set by hand; it reports its position")
        if self.entity_id is not None and self.entity_name is not None:
            raise ValueError("give entity_id or entity_name, not both")
        return self


class OffloadStationSetupResult(BaseModel):
    """What the setup did, piece by piece, so the page can say it."""

    device_id: uuid.UUID
    device_name: str
    station_eui: str
    entity_id: uuid.UUID
    entity_name: str
    entity_created: bool = Field(description="A new Offload station entity was made")
    entity_kept: bool = Field(description="The device tracked this entity already")
    placed: bool = Field(description="The place was set in this call")
    mobile: bool = Field(default=False, description="The station reports its own position")
    gateway_id: uuid.UUID
    gateway_created: bool = Field(description="The gateway row did not exist before")
