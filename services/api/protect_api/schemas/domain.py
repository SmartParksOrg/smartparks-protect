import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from protect_api.schemas.common import GeoJSONGeometry, ORMModel
from shared.enums import DeviceStatus, EntityGroup, EntityStatus, FeatureType, ValueType
from shared.timeutil import require_aware

KEY_PATTERN = "^[a-z][a-z0-9_]{1,62}$"
ICON_PATTERN = "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$"


class EntityTypeCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    group_key: EntityGroup
    icon_key: str = Field(pattern=ICON_PATTERN)
    attribute_schema: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class EntityTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    group_key: EntityGroup | None = None
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    attribute_schema: dict[str, Any] | None = None
    description: str | None = None


class EntityTypeRead(ORMModel):
    id: uuid.UUID
    key: str
    label: str
    group_key: str
    icon_key: str
    attribute_schema: dict[str, Any]
    description: str | None
    created_at: datetime


class EntityCreate(BaseModel):
    entity_type_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    status: EntityStatus = EntityStatus.ACTIVE
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    geometry: GeoJSONGeometry | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class EntityUpdate(BaseModel):
    entity_type_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: EntityStatus | None = None
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    geometry: GeoJSONGeometry | None = None
    attributes: dict[str, Any] | None = None
    notes: str | None = None


class EntityRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    entity_type_id: uuid.UUID
    name: str
    status: str
    icon_key: str | None
    geometry: dict[str, Any] | None = None
    attributes: dict[str, Any]
    notes: str | None
    created_at: datetime
    updated_at: datetime


class FeatureCreate(BaseModel):
    feature_type: FeatureType
    name: str = Field(min_length=1, max_length=200)
    geometry: GeoJSONGeometry
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    attributes: dict[str, Any] = Field(default_factory=dict)


class FeatureUpdate(BaseModel):
    feature_type: FeatureType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geometry: GeoJSONGeometry | None = None
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    attributes: dict[str, Any] | None = None


class FeatureRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    feature_type: str
    name: str
    geometry: dict[str, Any] | None = None
    icon_key: str | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeviceTypeCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    driver_key: str = Field(pattern=KEY_PATTERN)
    manufacturer: str | None = None
    icon_key: str = Field(default="device.sensor", pattern=ICON_PATTERN)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    default_settings: dict[str, Any] = Field(default_factory=dict)


class DeviceTypeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    driver_key: str | None = Field(default=None, pattern=KEY_PATTERN)
    manufacturer: str | None = None
    icon_key: str | None = Field(default=None, pattern=ICON_PATTERN)
    capabilities: dict[str, Any] | None = None
    default_settings: dict[str, Any] | None = None


class DeviceTypeRead(ORMModel):
    id: uuid.UUID
    key: str
    label: str
    driver_key: str
    manufacturer: str | None
    icon_key: str
    capabilities: dict[str, Any]
    default_settings: dict[str, Any]
    created_at: datetime


class DeviceCreate(BaseModel):
    device_type_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    serial_number: str | None = Field(default=None, max_length=128)
    status: DeviceStatus = DeviceStatus.INVENTORY
    firmware_version: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class DeviceUpdate(BaseModel):
    device_type_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    serial_number: str | None = Field(default=None, max_length=128)
    status: DeviceStatus | None = None
    firmware_version: str | None = None
    attributes: dict[str, Any] | None = None
    notes: str | None = None


class DeviceRead(ORMModel):
    id: uuid.UUID
    device_type_id: uuid.UUID
    name: str
    serial_number: str | None
    status: str
    firmware_version: str | None
    attributes: dict[str, Any]
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AssignmentRead(ORMModel):
    id: uuid.UUID
    device_id: uuid.UUID
    valid_from: datetime
    valid_to: datetime | None
    reason: str | None
    created_at: datetime


class ProjectAssignmentRead(AssignmentRead):
    project_id: uuid.UUID


class EntityAssignmentRead(AssignmentRead):
    entity_id: uuid.UUID


class _Validity(BaseModel):
    valid_from: datetime
    valid_to: datetime | None = None
    reason: str | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value is not None else None


class ProjectAssignmentCreate(_Validity):
    project_id: uuid.UUID


class EntityAssignmentCreate(_Validity):
    device_id: uuid.UUID
    entity_id: uuid.UUID


class AssignmentEnd(BaseModel):
    valid_to: datetime

    @field_validator("valid_to")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class HandoverRequest(BaseModel):
    """Move a device to another project from `effective_at` (architecture 28.10)."""

    project_id: uuid.UUID
    effective_at: datetime
    reason: str | None = None

    @field_validator("effective_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value)


class DeviceWithAssignments(DeviceRead):
    project_assignments: list[ProjectAssignmentRead]
    entity_assignments: list[EntityAssignmentRead]
    external_identities: list["ExternalIdentityRead"]


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    adapter_key: str = Field(pattern=KEY_PATTERN)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] | None = Field(default=None, description="Write only")
    capabilities: dict[str, Any] = Field(default_factory=dict)
    link_templates: dict[str, Any] = Field(default_factory=dict)
    retention_days: int | None = Field(default=None, ge=1)
    project_ids: list[uuid.UUID] = Field(default_factory=list)


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = Field(default=None, description="Write only")
    capabilities: dict[str, Any] | None = None
    link_templates: dict[str, Any] | None = None
    retention_days: int | None = Field(default=None, ge=1)
    project_ids: list[uuid.UUID] | None = None


class DataSourceRead(ORMModel):
    id: uuid.UUID
    name: str
    adapter_key: str
    enabled: bool
    config: dict[str, Any]
    has_credentials: bool = False
    has_webhook_token: bool = False
    webhook_token: str | None = Field(
        default=None, description="Only in the response that created it"
    )
    webhook_url: str | None = None
    capabilities: dict[str, Any]
    link_templates: dict[str, Any]
    retention_days: int | None
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExternalIdentityCreate(BaseModel):
    data_source_id: uuid.UUID
    external_id: str = Field(min_length=1, max_length=256)
    identity_type: str = Field(default="dev_eui", pattern=KEY_PATTERN)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExternalIdentityUpdate(BaseModel):
    device_id: uuid.UUID | None = None
    identity_type: str | None = Field(default=None, pattern=KEY_PATTERN)
    attributes: dict[str, Any] | None = None
    ignored: bool | None = None


class ExternalIdentityRead(ORMModel):
    id: uuid.UUID
    data_source_id: uuid.UUID
    device_id: uuid.UUID | None
    external_id: str
    identity_type: str
    attributes: dict[str, Any]
    ignored: bool
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    event_count: int
    created_at: datetime


class MetricCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=32)
    value_type: ValueType
    category: str = Field(pattern=KEY_PATTERN)
    description: str | None = None


class MetricUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, pattern=KEY_PATTERN)
    description: str | None = None


class MetricRead(ORMModel):
    key: str
    label: str
    unit: str | None
    value_type: str
    category: str
    description: str | None
    created_at: datetime


class ImportRowResult(BaseModel):
    row: int
    device_name: str
    status: str
    message: str | None = None
    device_id: uuid.UUID | None = None


class ImportResult(BaseModel):
    created: int
    rows: list[ImportRowResult]
