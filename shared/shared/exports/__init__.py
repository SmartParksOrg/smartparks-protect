"""Exports as a backend capability (architecture 14, decisions D39 and D40).

`ExportParameters` is what a job stores and what a direct export takes as query parameters;
`datasets` turns them into streamed rows, `writers` turn rows into bytes, `runner` runs a job.
"""

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.analytics import DEFAULT_AGGREGATES, Aggregate, GroupBy, Layout
from shared.enums import ExportDataset, ExportFormat

DIRECT_MAX_ROWS = 100_000  # architecture 13.8: interactive exports stop here, jobs take over
JOB_RETENTION_DAYS = 7

_TABULAR = frozenset({ExportFormat.CSV, ExportFormat.XLSX, ExportFormat.JSON})
FORMATS_BY_DATASET: dict[ExportDataset, frozenset[ExportFormat]] = {
    ExportDataset.SOURCE_EVENTS: _TABULAR,
    ExportDataset.MEASUREMENTS: _TABULAR,
    ExportDataset.AGGREGATES: _TABULAR,
    ExportDataset.POSITIONS: frozenset(ExportFormat),  # also GeoJSON and GPX
}


class ExportParameters(BaseModel):
    """Everything an export needs; stored on the job so it can be reproduced."""

    dataset: ExportDataset
    format: ExportFormat
    time_from: datetime
    time_to: datetime
    entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    metric_keys: list[str] = Field(default_factory=list, max_length=100)
    data_source_id: uuid.UUID | None = None
    timezone: str = Field(default="UTC", description="IANA name; times are written in this zone")
    include_names: bool = Field(
        default=True, description="Entity, device and metric names as columns"
    )
    view: Literal["effective", "original"] = Field(
        default="effective",
        description="Effective (curated) values, the default, or the original canonical values "
        "(positions and measurements; architecture 28.13, decision D83)",
    )
    curation_metadata: bool = Field(
        default=False,
        description="Add is_curated, curated_fields, curation_reason, original and effective "
        "time and value, curated_by, curated_at and curation_job_id columns",
    )
    # aggregates only
    bucket: str | None = Field(
        default=None, description="Ladder key, `all`, or empty for automatic"
    )
    aggregates: list[Aggregate] = Field(default_factory=lambda: list(DEFAULT_AGGREGATES))
    group_by: GroupBy = GroupBy.ENTITY
    layout: Layout = Layout.LONG

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r}") from None
        return value

    @field_validator("time_from", "time_to")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamps need a timezone offset")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "ExportParameters":
        if self.time_from >= self.time_to:
            raise ValueError("time_to must be after time_from")
        if self.format not in FORMATS_BY_DATASET[self.dataset]:
            allowed = ", ".join(sorted(f.value for f in FORMATS_BY_DATASET[self.dataset]))
            raise ValueError(
                f"{self.dataset.value} exports support {allowed}, not {self.format.value}"
            )
        if self.dataset is ExportDataset.AGGREGATES and not self.metric_keys:
            raise ValueError("aggregates need at least one metric")
        if self.dataset is ExportDataset.SOURCE_EVENTS and self.entity_ids:
            raise ValueError("source events are per device; filter by device_ids")
        if self.layout is Layout.SERIES:
            raise ValueError("exports use the long or wide layout")
        return self

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
