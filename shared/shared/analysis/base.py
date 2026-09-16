"""The contract between the analysis runner and a module: parameters in, a result document
out, progress and cancellation in between. Kept small on purpose: two modules use it."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

#: Reports progress (0 to 100) and the step under way; the runner writes it to the run row.
Progress = Callable[[int, str], Awaitable[None]]


class Period(BaseModel):
    """A window of time the analysis covers, and its role: the main one or a comparison."""

    key: Literal["main", "comparison"] = "main"
    time_from: datetime
    time_to: datetime


class Subject(BaseModel):
    """An entity or a device the analysis is about, as the result names it. A device subject
    (decision D214) says which entity it tracked in the period, when it tracked one."""

    id: uuid.UUID
    name: str
    type: str | None = None
    kind: Literal["entity", "device"] = "entity"
    tracked: str | None = None


class Warning(BaseModel):
    """A data quality or method warning shown above the results, per subject when it applies."""

    code: str
    level: Literal["notice", "warning"] = "warning"
    subject_id: uuid.UUID | None = None
    text: str


class Provenance(BaseModel):
    """Enough to understand or reproduce a result (plan, section 19)."""

    module: str
    method_version: str
    subjects: list[Subject]
    periods: list[Period]
    parameters: dict[str, Any]
    input_count: int
    excluded_count: int
    computed_at: datetime
    sources: list[str] = Field(default_factory=list)


class Chart(BaseModel):
    """Chart data the interface draws; never styling."""

    key: str
    kind: Literal["line", "bar", "rose", "stacked"]
    unit: str | None = None
    series: list[dict[str, Any]]


class Table(BaseModel):
    key: str
    columns: list[str]
    rows: list[list[Any]]


class ResultDocument(BaseModel):
    """What a completed run stores on its row (`analysis_runs.result`); the geometries go to
    their own table and are counted here."""

    version: int = 1
    module: str
    method_version: str
    subjects: list[Subject]
    periods: list[Period]
    summary: dict[str, Any] = Field(default_factory=dict)
    tables: list[Table] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    geometries: dict[str, int] = Field(default_factory=dict)
    warnings: list[Warning] = Field(default_factory=list)
    provenance: Provenance


class Geometry(BaseModel):
    """One result polygon or point the module hands the runner for `analysis_geometries`."""

    kind: str
    subject_id: uuid.UUID | None = None
    label: str
    level: float | None = None
    geojson: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    document: ResultDocument
    geometries: list[Geometry] = Field(default_factory=list)


class RunContext(BaseModel):
    """What the runner gives a module: the project, the run and a session to read core data."""

    model_config = {"arbitrary_types_allowed": True}

    project_id: uuid.UUID
    run_id: uuid.UUID
    session: AsyncSession
    progress: Progress
    cancelled: Callable[[], Awaitable[bool]]


class AnalysisModule(Protocol):
    """A module: a key, a label, a version string for the provenance, a parameters model the
    API validates with, and the run itself. A module may also declare `subject_kind =
    "device"` when its subjects are devices rather than entities (decision D214); the API
    reads it with a default of `entity`."""

    key: str
    label: str
    version: str
    parameters: type[BaseModel]

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult: ...


class AnalysisCancelled(Exception):
    """Raised inside a run when the person cancelled it; the runner marks the row cancelled."""


class AnalysisTooLarge(Exception):
    """The module read or produced more than the run may hold; the runner stores it."""
