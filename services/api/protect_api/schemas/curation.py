"""Data curation (architecture 28, phase 12)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel


class CorrectionCreate(BaseModel):
    target_type: str = Field(pattern="^(position|measurement)$")
    target_id: int = Field(ge=1)
    target_time: datetime = Field(description="The record's original time, its key")
    field: str = Field(pattern="^(time|coordinates|value|valid)$")
    corrected_value: Any
    reason_code: str = Field(min_length=1, max_length=48)
    comment: str | None = Field(default=None, max_length=2000)


class CorrectionRevert(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class CorrectionRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    target_type: str
    target_id: int
    target_time: datetime
    device_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    metric_key: str | None
    field: str
    original_value: Any
    corrected_value: Any
    reason_code: str
    comment: str | None
    status: str
    impact: dict[str, Any]
    curation_job_id: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    applied_at: datetime | None
    reverted_by_user_id: uuid.UUID | None
    reverted_at: datetime | None
    revert_comment: str | None
    trace_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TransformationIn(BaseModel):
    kind: str = Field(pattern="^(time_offset|set_valid|value_offset|value_scale)$")
    seconds: int = 0
    valid: bool = False
    delta: float = 0.0
    factor: float = 1.0


class JobCreate(BaseModel):
    target_type: str = Field(pattern="^(position|measurement)$")
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    metric_keys: list[str] = Field(default_factory=list, max_length=100)
    time_from: datetime
    time_to: datetime
    transformation: TransformationIn
    reason_code: str = Field(min_length=1, max_length=48)
    comment: str | None = Field(default=None, max_length=2000)
    replay_rules: bool = Field(
        default=False, description="Run the rule replay over the corrected window as a report"
    )


class JobRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    target_type: str
    device_ids: list[str]
    entity_ids: list[str]
    metric_keys: list[str]
    time_from: datetime
    time_to: datetime
    transformation: dict[str, Any]
    reason_code: str
    comment: str | None
    replay_rules: bool
    preview: dict[str, Any]
    impact: dict[str, Any]
    affected_count: int
    applied_count: int
    reverted_count: int
    created_by_user_id: uuid.UUID | None
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    applied_by_user_id: uuid.UUID | None
    applied_at: datetime | None
    reverted_by_user_id: uuid.UUID | None
    reverted_at: datetime | None
    error_message: str | None
    trace_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CurationSummary(BaseModel):
    requires_approval: bool
    pending_corrections: int
    active_corrections: int
    reverted_corrections: int
    jobs: dict[str, int]
    stale_deliveries: int
    reasons: list[str]
    curatable: dict[str, list[str]]
    transformations: list[str]


class RecordHistory(BaseModel):
    """A record's effective and original values with every correction on it."""

    target_type: str
    target_id: int
    target_time: datetime
    effective: dict[str, Any]
    original: dict[str, Any]
    curated_fields: list[str]
    valid: bool
    curation_version: int
    corrections: list[CorrectionRead]
