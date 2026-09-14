"""The analysis API's shapes (docs/ANALYTICS_PHASE1_PLAN.md, section 12)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from protect_api.schemas.common import ORMModel


class AnalysisModuleRead(BaseModel):
    key: str
    label: str
    version: str
    #: The bounds the form shows: subjects, areas, days, fixes.
    limits: dict[str, int]


class AnalysisRunCreate(BaseModel):
    module: str = Field(max_length=32)
    parameters: dict[str, Any]
    name: str | None = Field(default=None, max_length=200)


class AnalysisRunUpdate(BaseModel):
    #: A name keeps the run; null lets it expire again.
    name: str | None = Field(default=None, max_length=200)


class AnalysisRunRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    module: str
    status: str
    name: str | None
    parameters: dict[str, Any]
    method_version: str
    progress: int
    cancel_requested: bool
    input_count: int | None
    excluded_count: int | None
    result: dict[str, Any] | None
    result_version: int
    error_code: str | None
    error_message: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    source_run_id: uuid.UUID | None


class AnalysisEstimate(BaseModel):
    """What a run would read, before it is queued: the counts and which bound it would cross."""

    module: str
    subjects: int
    days: float
    fixes: int
    max_subjects: int
    max_days: int
    max_fixes: int
    ok: bool
    reasons: list[str] = Field(default_factory=list)
