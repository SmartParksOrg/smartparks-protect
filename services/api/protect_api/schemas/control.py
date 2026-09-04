"""Request and response models for device control (phase 6)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel


class ActionAvailability(BaseModel):
    key: str
    label: str
    description: str
    parameters_schema: dict[str, Any]
    permission: str
    confirmation: str
    required_capability: str
    confirms: bool
    schema_version: int
    available: bool
    reason: str | None = None
    permitted: bool = True


class CommandCreate(BaseModel):
    action_key: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = Field(
        default=False, description="The user confirmed an action whose policy asks for it"
    )
    route_data_source_id: uuid.UUID | None = Field(
        default=None,
        description="Deliver through this data source (decision D79); default the most "
        "recently seen route that needs no connected client",
    )


class RouteOptionRead(BaseModel):
    data_source_id: uuid.UUID
    name: str
    adapter_key: str
    channel: str
    external_id: str
    identity_type: str
    last_seen_at: datetime | None
    available: bool
    reason: str | None
    requires_client: bool
    default: bool


class BrowserResult(BaseModel):
    """What the browser reports after executing a WebBLE command."""

    status: str = Field(pattern="^(transmitted|failed)$")
    detail: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, max_length=500)


class CommandRead(ORMModel):
    id: uuid.UUID
    device_id: uuid.UUID
    project_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    action_key: str
    driver_key: str
    schema_version: int
    parameters: dict[str, Any]
    payload_hex: str | None
    f_port: int | None
    confirmed_downlink: bool
    data_source_id: uuid.UUID | None
    external_id: str | None
    route: str | None
    status: str
    provider_ref: str | None
    provider_response: dict[str, Any]
    result: dict[str, Any]
    error_code: str | None
    error_message: str | None
    actor: dict[str, Any]
    requested_by_user_id: uuid.UUID | None
    automation_id: uuid.UUID | None
    event_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    submitted_at: datetime | None
    transmitted_at: datetime | None
    acknowledged_at: datetime | None
    confirmed_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CommandExecutionRead(ORMModel):
    id: int
    command_id: uuid.UUID
    time: datetime
    status: str
    source: str
    detail: dict[str, Any]


class CommandDetail(BaseModel):
    command: CommandRead
    executions: list[CommandExecutionRead]


class QueueItem(BaseModel):
    id: str | None = None
    f_port: int | None = None
    confirmed: bool | None = None
    is_pending: bool | None = None
    f_cnt_down: int | None = None
    data_hex: str | None = None


class QueueState(BaseModel):
    data_source_id: uuid.UUID | None
    external_id: str | None
    supported: bool
    items: list[QueueItem]
