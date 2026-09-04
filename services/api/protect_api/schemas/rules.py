"""Request and response models for rules, events, alerts, automations, notification targets
and deliveries (phase 5)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel
from shared.enums import ActionType, NotificationChannel, Severity


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    document: dict[str, Any]
    enabled: bool = False


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    enabled: bool | None = None


class RuleDocumentUpdate(BaseModel):
    document: dict[str, Any]


class RuleRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    current_version: int
    document: dict[str, Any] = Field(default_factory=dict)
    reserved_types: list[str] = Field(default_factory=list)
    last_fired_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class RuleVersionRead(ORMModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    version: int
    document: dict[str, Any]
    schema_version: int
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class RuleTemplateRead(BaseModel):
    key: str
    name: str
    description: str
    document: dict[str, Any]


class ReplayRequest(BaseModel):
    time_from: datetime = Field(alias="from")
    time_to: datetime = Field(alias="to")
    version: int | None = Field(default=None, description="Rule version; default current")
    document: dict[str, Any] | None = Field(
        default=None, description="Test this document instead of a saved version"
    )


class ReplayEventRead(BaseModel):
    time: datetime
    subject_key: str
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    title: str
    reason: str
    context: dict[str, Any]


class ReplayResultRead(BaseModel):
    events: list[ReplayEventRead]
    total: int
    samples: int
    truncated: bool


class EventRead(ORMModel):
    id: uuid.UUID
    time: datetime
    created_at: datetime
    project_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    event_type: str
    severity: str
    title: str
    description: str | None
    geometry: dict[str, Any] | None = None
    context: dict[str, Any]
    rule_version_id: uuid.UUID | None
    source_event_id: int | None
    source_event_ingested_at: datetime | None
    trace_id: uuid.UUID | None
    alert_id: uuid.UUID | None = None
    alert_status: str | None = None


class AlertRead(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID
    project_id: uuid.UUID | None
    status: str
    severity: str
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolved_by_user_id: uuid.UUID | None
    note: str | None
    title: str = ""
    event_type: str = ""
    entity_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    time: datetime | None = None


class AlertAction(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ActionDeliveryRead(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID
    alert_id: uuid.UUID | None
    automation_id: uuid.UUID | None
    project_id: uuid.UUID | None
    action_index: int
    action_type: str
    target_id: uuid.UUID | None
    status: str
    attempts: int
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    error_code: str | None
    error_message: str | None
    response: dict[str, Any]
    trace_id: uuid.UUID | None
    created_at: datetime


class EventDetail(BaseModel):
    event: EventRead
    alert: AlertRead | None
    deliveries: list[ActionDeliveryRead]


class ActionSpec(BaseModel):
    type: ActionType
    target_id: uuid.UUID | None = None
    url: str | None = Field(default=None, max_length=2000)
    secret: str | None = Field(default=None, max_length=200)
    action_key: str | None = Field(default=None, max_length=64, description="Command actions")
    parameters: dict[str, Any] | None = Field(default=None, description="Command parameters")


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    enabled: bool = True
    event_types: list[str] = Field(default_factory=list)
    min_severity: Severity = Severity.INFO
    require_alert: bool = False
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    rule_ids: list[uuid.UUID] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(min_length=1, max_length=20)
    max_event_age_seconds: int = Field(default=21_600, ge=60, le=30 * 86_400)


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    enabled: bool | None = None
    event_types: list[str] | None = None
    min_severity: Severity | None = None
    require_alert: bool | None = None
    entity_ids: list[uuid.UUID] | None = None
    rule_ids: list[uuid.UUID] | None = None
    actions: list[ActionSpec] | None = Field(default=None, min_length=1, max_length=20)
    max_event_age_seconds: int | None = Field(default=None, ge=60, le=30 * 86_400)


class AutomationRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    description: str | None
    enabled: bool
    event_types: list[str]
    min_severity: str
    require_alert: bool
    entity_ids: list[str]
    rule_ids: list[str]
    actions: list[dict[str, Any]]
    max_event_age_seconds: int
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NotificationTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel: NotificationChannel
    address: str | None = Field(default=None, max_length=320)
    enabled: bool = True


class NotificationTargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=320)
    enabled: bool | None = None


class NotificationTargetRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    channel: str
    address: str | None
    enabled: bool
    linked: bool = False
    telegram_link_code: str | None = None
    telegram_link_expires_at: datetime | None = None
    link_url: str | None = None
    created_at: datetime
    updated_at: datetime


class TestSendResult(BaseModel):
    status: str
    detail: str | None = None


class NotificationCapabilities(BaseModel):
    mail_configured: bool
    telegram_configured: bool
    telegram_bot_username: str | None = None
