"""The parameters both modules share (docs/ANALYTICS_PHASE1_PLAN.md, section 12): who the
analysis is about and when. The API resolves a group or a type to entity ids before the run
is stored, so a run stays reproducible when the group changes later."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from shared.analysis.limits import MAX_DAYS, MAX_DEVICES


class SubjectSelection(BaseModel):
    """Entities by id, or everything in a group (with its subgroups), or every entity of a
    type; the API turns the latter two into ids and keeps them in `entity_ids`. A module whose
    subjects are devices (decision D214) takes devices by id, every device of a type, or every
    device of the project instead; the API keeps the resolved ids in `device_ids`."""

    entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    group_id: uuid.UUID | None = None
    entity_type_id: uuid.UUID | None = None
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_DEVICES)
    device_type_id: uuid.UUID | None = None
    all_devices: bool = False


class Window(BaseModel):
    time_from: datetime
    time_to: datetime

    @model_validator(mode="after")
    def _ordered_and_bounded(self) -> Window:
        if self.time_to <= self.time_from:
            raise ValueError("the period must end after it starts")
        if self.time_to - self.time_from > timedelta(days=MAX_DAYS):
            raise ValueError(f"the period may span at most {MAX_DAYS} days")
        return self


class CommonParameters(SubjectSelection, Window):
    """What every module takes: the subjects, the period, an optional comparison period, and
    the gap above which an interval between two fixes is a gap and not movement."""

    comparison: Window | None = None
    gap_hours: float = Field(default=4, ge=0.25, le=168)
