"""Phase 13 schemas: manual events, AI actions and policy, project icons, dashboards."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel

KEY_PATTERN = r"^[A-Z][A-Z0-9_]{1,63}$"


class EventCreate(BaseModel):
    """A report by a person (or an AI client on their behalf): an event that is a fact."""

    event_type: str = Field(
        pattern=KEY_PATTERN, description="Upper snake case, for example SIGHTING"
    )
    title: str = Field(min_length=1, max_length=200)
    severity: Literal["info", "warning", "critical"] = "info"
    description: str | None = Field(default=None, max_length=4000)
    time: datetime | None = Field(default=None, description="Default now")
    entity_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    context: dict[str, Any] = Field(default_factory=dict)
    create_alert: bool = Field(default=False, description="Also open an alert for a person")


class AiActionRequest(BaseModel):
    action: str = Field(
        pattern="^(create_event|acknowledge_alert|request_device_status|request_device_position)$"
    )
    parameters: dict[str, Any] = Field(default_factory=dict)


class AiActionRead(BaseModel):
    id: uuid.UUID | None
    action: str
    status: Literal["executed", "confirmation_required", "expired"]
    summary: str
    expires_at: datetime | None = None
    result: dict[str, Any] | None = None


class AiActionInfo(BaseModel):
    action: str
    action_class: str
    scope: str
    mode: str


class AiPolicyRead(BaseModel):
    policy: dict[str, str]
    actions: list[AiActionInfo]
    modes: list[str]
    updated_at: datetime | None = None


class AiPolicyUpdate(BaseModel):
    policy: dict[str, str]


class ProjectIconCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    key: str | None = Field(
        default=None,
        pattern=r"^project\.[a-z][a-z0-9_]{0,60}$",
        description="Default project.<slug of the label>",
    )
    svg: str = Field(min_length=10, max_length=65536)


class ProjectIconRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    label: str
    svg: str
    sha256: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class DashboardTile(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    kind: Literal["saved_view", "map", "alerts", "events", "entity_status"]
    size: Literal["s", "m", "l"] = "m"
    title: str | None = Field(default=None, max_length=120)
    saved_view_id: uuid.UUID | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[DashboardTile] = Field(default_factory=list, max_length=30)


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tiles: list[DashboardTile] | None = Field(default=None, max_length=30)


class DashboardRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    tiles: list[dict[str, Any]]
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
