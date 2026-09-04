"""Integrations, deliveries and gateways (phase 8)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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
    status: str
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_stats_at: datetime | None
    stats: dict[str, Any]
    attributes: dict[str, Any]
    receptions: int = 0
    devices: int = 0
    mean_rssi: float | None = None
    mean_snr: float | None = None
    last_reception_at: datetime | None = None
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


class GatewayUpdateRequest(BaseModel):
    name_override: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    altitude_m: float | None = None
    description: str | None = None


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
