"""Integrations, deliveries and gateways (phase 8)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, EmailStr, Field

from protect_api.schemas.common import ORMModel
from shared.enums import IntegrationObjectType, Severity


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    connector_key: str = Field(pattern="^[a-z][a-z0-9_]{1,62}$")
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(default=None, description="Write only")
    object_types: list[IntegrationObjectType] = Field(
        default_factory=lambda: [IntegrationObjectType.POSITION, IntegrationObjectType.EVENT]
    )
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    metric_keys: list[str] = Field(default_factory=list)
    min_severity: Severity = Severity.INFO
    max_object_age_seconds: int = Field(default=86_400, ge=60, le=365 * 86_400)


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = Field(default=None, description="Write only")
    object_types: list[IntegrationObjectType] | None = None
    entity_ids: list[uuid.UUID] | None = None
    device_ids: list[uuid.UUID] | None = None
    event_types: list[str] | None = None
    metric_keys: list[str] | None = None
    min_severity: Severity | None = None
    max_object_age_seconds: int | None = Field(default=None, ge=60, le=365 * 86_400)


class IntegrationRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    connector_key: str
    enabled: bool
    config: dict[str, Any]
    has_credentials: bool = False
    object_types: list[str]
    entity_ids: list[str]
    device_ids: list[str]
    event_types: list[str]
    metric_keys: list[str]
    min_severity: str
    max_object_age_seconds: int
    last_delivery_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    backfill: dict[str, Any]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class IntegrationDetail(IntegrationRead):
    counts: dict[str, int] = Field(default_factory=dict, description="Deliveries per status")
    counts_24h: dict[str, int] = Field(default_factory=dict)


class IntegrationDeliveryRead(ORMModel):
    id: uuid.UUID
    integration_id: uuid.UUID
    project_id: uuid.UUID
    object_type: str
    object_id: str
    object_version: int
    object_time: datetime
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    origin: str
    status: str
    attempts: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    external_id: str | None
    error_code: str | None
    error_message: str | None
    trace_id: uuid.UUID | None
    created_at: datetime
    stale_at: datetime | None = None
    stale_reason: str | None = None


class IntegrationDeliveryDetail(IntegrationDeliveryRead):
    request: dict[str, Any] | None
    response: dict[str, Any]


class IntegrationTestRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class IntegrationTestResult(BaseModel):
    ok: bool
    detail: str
    response: dict[str, Any] = Field(default_factory=dict)


class BackfillRequest(BaseModel):
    time_from: datetime
    time_to: datetime


class LoginCodeRequest(BaseModel):
    email: EmailStr = Field(description="The address of the account on the target")


class LoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1, max_length=64, description="The code from the email")


class LoginRead(BaseModel):
    """A sign-in that worked (D414). The credentials are stored and never returned."""

    account: str
    scopes: list[str] = Field(description="What the account may do on the target")


SubjectStateName = Literal["history_requested", "sending_history", "registered", "held", "failed"]
DeploymentStateName = Literal["pending", "sent", "refused", "declined"]


class TargetStatus(BaseModel):
    """What the target has for an entity, read from the target."""

    registered: bool
    sensor_id: str | None = Field(default=None, description="What the target knows the device by")
    external_id: str | None = None
    external_name: str | None = None
    since: datetime | None = None
    elsewhere: str | None = Field(
        default=None, description="The other animal the target has the sensor on"
    )


class DeploymentRead(BaseModel):
    """A device on an integrated entity as a deployment of its sensor on the target's animal
    (decisions D416 to D419): Protect's own account, the target is not asked."""

    id: uuid.UUID
    integration_id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str
    device_id: uuid.UUID
    device_name: str
    sensor_id: str | None = None
    starts_at: datetime = Field(description="The start of the device's assignment")
    ends_at: datetime | None = Field(
        default=None, description="The end of the assignment in Protect; none while on"
    )
    state: DeploymentStateName
    detail: str | None = None
    animal_id: str | None = None
    sent_at: datetime | None = None
    open_on_target: bool = Field(
        default=False,
        description="The device's latest sent deployment: the target keeps the sensor on this "
        "animal until it is deployed again, since it cannot end a deployment",
    )
    rewrites: int = Field(
        default=0,
        description="Finished deployments of the sensor the target would give a wrong end "
        "when this one is sent (decision D419)",
    )


class IntegrationSubjectRead(BaseModel):
    """An entity integrated with a target that registers its entities (D412): what was chosen
    for it, how far its history is, and what Protect registered."""

    integration_id: uuid.UUID
    entity_id: uuid.UUID
    entity_name: str
    state: SubjectStateName
    detail: str | None = Field(default=None, description="Why it is held or failed")
    species_id: str | None = None
    species_name: str | None = None
    history_from: datetime | None = None
    history_queued: int = 0
    history_waiting: int = Field(default=0, description="Objects of its history not yet sent")
    external_id: str | None = Field(default=None, description="The target's id of the animal")
    registered_at: datetime | None = None
    created_at: datetime
    target: TargetStatus | None = Field(
        default=None, description="Only where the target was asked: the integration's overview"
    )


class IntegrationSubjects(BaseModel):
    items: list[IntegrationSubjectRead]
    waiting: list[DeploymentRead] = Field(
        default_factory=list,
        description="Deployments that wait for a person or were refused, at most 200",
    )
    target_error: str | None = Field(
        default=None, description="Why the target could not be asked; the rows are Protect's own"
    )


class SubjectChoiceRead(BaseModel):
    id: str
    name: str
    common_name: str | None = None


class IntegrationSubjectOptions(BaseModel):
    """What a user sees before integrating one entity (D413)."""

    entity_id: uuid.UUID
    entity_name: str
    device_name: str | None = None
    assigned_from: datetime | None = Field(
        default=None, description="Since when the device is on the entity: the earliest history"
    )
    sensor_id: str | None = None
    target: TargetStatus
    species: list[SubjectChoiceRead]
    proposed_species_id: str | None = None
    blocked: str | None = Field(default=None, description="Why it cannot be integrated as it is")
    subject: IntegrationSubjectRead | None = Field(
        default=None, description="What was chosen before, when the entity is integrated"
    )


class IntegrationSubjectWrite(BaseModel):
    species_id: uuid.UUID
    species_name: str | None = Field(default=None, max_length=200)
    history_from: AwareDatetime | None = Field(
        default=None,
        description="Send the entity's data from this moment first, then register it (D409); "
        "none registers at once",
    )


class EntityIntegrationRead(BaseModel):
    """An integration of the project that registers its entities, as one entity sees it."""

    integration_id: uuid.UUID
    name: str
    connector_key: str
    connector_label: str
    enabled: bool
    subject: IntegrationSubjectRead | None = None
    deployments: list[DeploymentRead] = Field(
        default_factory=list, description="The entity's devices on the target, newest first"
    )


class DeviceIntegrationRead(BaseModel):
    """An integration of the project that registers its entities, as one device sees it
    (decision D418): the entity it is on now, how that entity stands, and the device's
    deployments on the target."""

    integration_id: uuid.UUID
    name: str
    connector_key: str
    connector_label: str
    enabled: bool
    entity_id: uuid.UUID | None = Field(default=None, description="The entity it is on now")
    entity_name: str | None = None
    subject: IntegrationSubjectRead | None = None
    deployments: list[DeploymentRead] = Field(
        default_factory=list, description="The device's deployments, newest first"
    )


class GatewayRead(ORMModel):
    id: uuid.UUID
    data_source_id: uuid.UUID
    data_source_name: str | None = None
    external_id: str
    name: str | None
    name_override: str | None
    display_name: str = ""
    description: str | None
    geometry: dict[str, Any] | None = None
    altitude_m: float | None
    location_source: str | None = None
    location_at: datetime | None = None
    device_id: uuid.UUID | None = Field(
        default=None,
        description="The device this gateway is, when it is one of ours (decision D319): an "
        "offload station",
    )
    status: str
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_stats_at: datetime | None
    stats: dict[str, Any]
    attributes: dict[str, Any]
    #: The window's figures: receptions of the scope's devices, distinct devices, mean signal.
    receptions: int = 0
    devices: int = 0
    mean_rssi: float | None = None
    mean_snr: float | None = None
    #: The newest reception of the scope's devices in the last 30 days, whatever the window,
    #: so a quiet day does not read as "never"; None when there was none in 30 days.
    last_reception_at: datetime | None = None
    #: The range of the gateway over the window (decision D374): the shortest, mean and
    #: longest distance in metres from the positions it heard to its own location, and how
    #: many positions; on the detail read, for a gateway with a location.
    range_min_m: float | None = None
    range_mean_m: float | None = None
    range_max_m: float | None = None
    range_positions: int = 0
    links: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class GatewayDeviceStat(BaseModel):
    device_id: uuid.UUID | None
    device_name: str | None
    receptions: int
    mean_rssi: float | None
    mean_snr: float | None
    last_reception_at: datetime | None


class GatewayDetail(BaseModel):
    gateway: GatewayRead
    devices: list[GatewayDeviceStat]


class GatewayDay(BaseModel):
    """One UTC day of a gateway's receptions of the scope's devices (decision D369)."""

    day: date
    receptions: int
    devices: int
    mean_rssi: float | None
    mean_snr: float | None


class GatewayUpdateRequest(BaseModel):
    name_override: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude_m: float | None = None
    description: str | None = None


class GatewayNameRequest(BaseModel):
    """The name a person gives a gateway (decision D247): empty gives the platform's name back."""

    name: str | None = Field(default=None, max_length=200)


class GatewayLocationRequest(BaseModel):
    """A location set by a person for a gateway the platform gave none (decision D239): both
    coordinates, or both empty to clear a location set by hand."""

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude_m: float | None = None


class GatewaySyncResult(BaseModel):
    synced: int


class DeviceConnectivity(BaseModel):
    device_id: uuid.UUID
    device_name: str | None
    receptions: int
    uplinks: int
    gateway_count: int
    best_gateway_id: uuid.UUID | None
    best_gateway_name: str | None
    best_gateway_share: float | None = Field(
        default=None, description="Share of uplinks the best gateway received"
    )
    mean_rssi: float | None
    mean_snr: float | None
    last_reception_at: datetime | None
    gateways: list[dict[str, Any]] = Field(default_factory=list)


class CursorReset(BaseModel):
    since: datetime | None = Field(
        default=None, description="Rescan from this instant; empty resets to the default window"
    )
