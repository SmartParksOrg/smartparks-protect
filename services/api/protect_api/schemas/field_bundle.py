"""The field bundle for Smart Parks Protect Go (phase 43, decision D331): what a project's
member takes along to read an offload station's card where there is no connection."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FieldProject(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str


class FieldArea(BaseModel):
    """A box in degrees: one of the project's regions, from its features, its entities' and
    devices' places and their current positions (decision D365), or the envelope of them all;
    what the offline map is cut for."""

    west: float
    south: float
    east: float
    north: float


class FieldLp0(BaseModel):
    """A tracker's LP0 credentials: the address always, the keys for a caller who may set them
    in Protect (device control in the project, or a server admin), as 32 hex digits."""

    dev_addr: str
    keys_set: bool
    app_s_key: str | None = None
    nwk_s_key: str | None = None
    set_at: datetime | None = None
    source: str | None = Field(default=None, description="person or device")


class FieldDevice(BaseModel):
    id: uuid.UUID
    name: str
    serial_number: str | None
    dev_eui: str | None = Field(default=None, description="Sixteen hex digits when known")
    device_type_key: str
    device_type_label: str
    driver_key: str
    status: str
    firmware_version: str | None
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    is_station: bool = Field(default=False, description="An offload station of the project")
    lp0: FieldLp0 | None = None


class FieldEntity(BaseModel):
    id: uuid.UUID
    name: str
    entity_type_key: str
    entity_type_label: str
    icon_key: str | None
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON, a place set by hand"
    )


class FieldStation(BaseModel):
    device_id: uuid.UUID
    device_name: str
    station_eui: str
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON point, where it stands"
    )


class FieldMetric(BaseModel):
    """A metric's definition from Protect's registry, so Protect Go names and units the values
    it decodes as Protect does (decision D334)."""

    key: str
    label: str
    unit: str | None = None
    value_type: str
    category: str
    description: str | None = None


class FieldMapRead(BaseModel):
    """The project's offline map (phase 43 P3): one PMTiles extract of the project's regions,
    each with a margin, cut from a Protomaps planet build; `ready` means
    `GET /projects/{id}/field-bundle/map` streams it."""

    status: str = Field(description="queued, running, ready or failed")
    west: float
    south: float
    east: float
    north: float
    regions: list[FieldArea] = Field(
        default_factory=list,
        description="The boxes the map was or is being cut for, with their margin (D365)",
    )
    covers_areas: bool = Field(
        default=True,
        description="Whether those boxes cover every region the project has now; when not, "
        "a new map should be asked for",
    )
    max_zoom: int
    build: str | None = Field(default=None, description="The planet build's date, YYYYMMDD")
    size_bytes: int | None = None
    sha256: str | None = None
    requested_at: datetime
    ready_at: datetime | None = None
    error: str | None = None


class FieldMapRequest(BaseModel):
    force: bool = Field(default=False, description="Cut again although a fresh map covers the area")


class FieldOtherTracker(BaseModel):
    """A tracker of another project the project's stations served (decision D348): the address
    and the names, never a key, so Protect Go names a card's frames of it instead of offering
    to add a device Protect already has."""

    dev_addr: str
    device_id: uuid.UUID
    device_name: str
    project_name: str | None = None


class FieldBundleRead(BaseModel):
    """One project for the field: its devices with the entity each tracks now, the entities,
    the stations with their EUI and place, the trackers' LP0 credentials the caller may see, the
    area, and the versions that made it. Protect Go decodes a card with these and uploads the card's
    files untouched to `POST /devices/{id}/offload-files`; nothing decoded comes back."""

    format_version: int = Field(default=1, description="The shape of this document")
    revision: str = Field(
        default="",
        description="A fingerprint of the content (devices, entities, stations, keys, map), "
        "the same until the project changes; Protect Go compares it to refresh itself "
        "(decision D344)",
    )
    generated_at: datetime
    protect_version: str
    protect_commit: str
    server_url: str = Field(description="Where the bundle came from, for the upload")
    project: FieldProject
    area: FieldArea | None = Field(default=None, description="The envelope of `areas`")
    areas: list[FieldArea] = Field(
        default_factory=list,
        description="The project's regions, the largest first (decision D365): places farther "
        "apart than the server's region gap are regions of their own",
    )
    map: FieldMapRead | None = Field(
        default=None, description="The offline map's state, once one was asked for"
    )
    credentials_included: bool = Field(
        description="The caller may see keys, so every tracker with keys carries them"
    )
    devices: list[FieldDevice] = Field(default_factory=list)
    metrics: list[FieldMetric] = Field(
        default_factory=list, description="The metric registry: key, label, unit, type"
    )
    entities: list[FieldEntity] = Field(default_factory=list)
    stations: list[FieldStation] = Field(default_factory=list)
    other_trackers: list[FieldOtherTracker] = Field(
        default_factory=list,
        description="Trackers of other projects the stations served in the last 30 days (D348)",
    )


class FieldBundleRevision(BaseModel):
    """The bundle's fingerprint alone, cheap to ask for often (decision D344)."""

    revision: str
    checked_at: datetime
