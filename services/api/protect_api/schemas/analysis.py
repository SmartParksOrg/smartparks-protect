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
    """What a person may change on a run: its name (a name saves it, null lets it expire
    again) and whether the project's members see it; a field left out stays as it is."""

    name: str | None = Field(default=None, max_length=200)
    shared: bool | None = None


class AnalysisRunRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    module: str
    status: str
    name: str | None
    parameters: dict[str, Any]
    method_version: str
    progress: int
    progress_step: str | None = None
    cancel_requested: bool
    input_count: int | None
    excluded_count: int | None
    result: dict[str, Any] | None
    result_version: int
    error_code: str | None
    error_message: str | None
    created_by_user_id: uuid.UUID | None
    #: The name of the person who ran it, for the runs table.
    created_by_name: str | None = None
    shared: bool = False
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    source_run_id: uuid.UUID | None
    #: The PDF report (decision D211): null until one is asked for, then queued, running,
    #: ready (downloadable) or failed with the error.
    report_status: str | None = None
    report_error: str | None = None
    report_at: datetime | None = None


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


class ProjectLayerRead(ORMModel):
    """A raster a project uploaded for the habitat analysis (phase 41, decision D315)."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    label: str
    kind: str
    size_bytes: int
    epsg: int
    width: int
    height: int
    pixel_m: float
    extent: dict[str, Any]
    nodata: float | None
    created_at: datetime


class LayerChoiceRead(BaseModel):
    """A layer a habitat run may name: the provider's, a distance to the project's features,
    or an upload (`shared.analysis.rasters.LayerChoice`)."""

    name: str
    label: str
    source: str
    kind: str
    description: str | None = None
    periodic: bool = False
    feature_type: str | None = None
    layer_id: uuid.UUID | None = None
