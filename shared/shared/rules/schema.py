"""The rule document (decision D9, ADR 0012).

A rule is a JSON document validated by these models. Version 1 of the schema supports what the
evaluator implements in phase 5: threshold, spatial ENTER/EXIT/INSIDE/OUTSIDE, speed as a
threshold on the derived `speed_kmh` metric, FOR duration, no-data on a schedule, and window
aggregates. NEAR, DWELL, CROSSED, baseline, correlation and event chaining are accepted by the
schema as reserved types so documents can be written now, but a rule that uses them cannot be
enabled until phase 13 implements them.
"""

import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.enums import Severity

SCHEMA_VERSION = 1

# Metrics an evaluator derives from a position instead of reading from the measurements table.
DERIVED_METRICS = frozenset({"speed_kmh", "speed_mps", "altitude_m", "latitude", "longitude"})

RESERVED_TYPES = ("near", "dwell", "crossed", "baseline", "correlation", "event_chain")

Op = Literal["<", "<=", ">", ">=", "==", "!="]


class TriggerKind(StrEnum):
    POSITION = "position"
    MEASUREMENT = "measurement"
    STATE = "state"
    EVENT = "event"
    SCHEDULE = "schedule"


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TriggerKind
    metric_key: str | None = Field(
        default=None, description="Measurement trigger: only this metric (null means any)"
    )
    event_type: str | None = Field(default=None, description="Event trigger (reserved)")
    every_seconds: int = Field(
        default=300, ge=60, le=86_400, description="Schedule trigger: evaluation interval"
    )


class Scope(BaseModel):
    """Which subjects the rule applies to. Empty lists mean every subject of the project."""

    model_config = ConfigDict(extra="forbid")

    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    entity_type_ids: list[uuid.UUID] = Field(default_factory=list)
    device_ids: list[uuid.UUID] = Field(default_factory=list)


class ThresholdCondition(BaseModel):
    """`metric op value`. The metric is the triggering measurement, a derived position metric
    (`speed_kmh`, `altitude_m`, ...) or the latest value of another metric of the subject."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["threshold"]
    metric: str = Field(min_length=1, max_length=64)
    op: Op
    value: float


class SpatialCondition(BaseModel):
    """Relation between the subject's position and project features. `feature_ids` selects
    specific features; empty means every feature of `feature_type` in the project."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["spatial"]
    relation: Literal["enter", "exit", "inside", "outside"]
    feature_ids: list[uuid.UUID] = Field(default_factory=list)
    feature_type: Literal["site", "zone", "geofence", "route"] | None = None

    @model_validator(mode="after")
    def _some_features(self) -> "SpatialCondition":
        if not self.feature_ids and self.feature_type is None:
            raise ValueError("spatial condition needs feature_ids or feature_type")
        return self


class NoDataCondition(BaseModel):
    """The subject has not been seen for `for_seconds`. Needs a schedule trigger."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["no_data"]
    for_seconds: int = Field(ge=60, le=90 * 86_400)


class WindowCondition(BaseModel):
    """An aggregate of a metric over the last `seconds`, compared with a value."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["window"]
    metric: str = Field(min_length=1, max_length=64)
    aggregate: Literal["avg", "min", "max", "sum", "count"]
    seconds: int = Field(ge=60, le=90 * 86_400)
    op: Op
    value: float


class ReservedCondition(BaseModel):
    """Accepted by the schema, rejected at activation until phase 13 implements it."""

    model_config = ConfigDict(extra="allow")

    type: Literal["near", "dwell", "crossed", "baseline", "correlation", "event_chain"]


Leaf = Annotated[
    ThresholdCondition | SpatialCondition | NoDataCondition | WindowCondition | ReservedCondition,
    Field(discriminator="type"),
]


class AllOf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all: list["Condition"] = Field(min_length=1)


class AnyOf(BaseModel):
    model_config = ConfigDict(extra="forbid")

    any: list["Condition"] = Field(min_length=1)


class NotOf(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    not_: "Condition" = Field(alias="not")


Condition = Leaf | AllOf | AnyOf | NotOf

AllOf.model_rebuild()
AnyOf.model_rebuild()
NotOf.model_rebuild()


class EventTemplate(BaseModel):
    """What the rule creates when it fires. Titles are templates with `{entity}`, `{device}`,
    `{feature}`, `{metric}`, `{value}` and `{rule}` placeholders."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    severity: Severity = Severity.WARNING
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    create_alert: bool = True


class RuleDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    trigger: Trigger
    scope: Scope = Field(default_factory=Scope)
    conditions: Condition
    for_seconds: int = Field(
        default=0, ge=0, le=90 * 86_400, description="Condition must hold this long before firing"
    )
    cooldown_seconds: int = Field(
        default=0,
        ge=0,
        le=365 * 86_400,
        description="While the condition stays active, fire again after this long (0: never)",
    )
    event: EventTemplate

    @model_validator(mode="after")
    def _trigger_matches_conditions(self) -> "RuleDocument":
        leaves = list(iter_leaves(self.conditions))
        kinds = {leaf.type for leaf in leaves}
        if "no_data" in kinds and self.trigger.kind is not TriggerKind.SCHEDULE:
            raise ValueError("a no_data condition needs a schedule trigger")
        if self.trigger.kind is TriggerKind.SCHEDULE and not kinds & {
            "no_data",
            "window",
            "spatial",
            "threshold",
            *RESERVED_TYPES,
        }:
            raise ValueError("a schedule trigger needs at least one condition")
        for leaf in leaves:
            if (
                isinstance(leaf, SpatialCondition)
                and leaf.relation in ("enter", "exit")
                and self.trigger.kind is not TriggerKind.POSITION
            ):
                raise ValueError("enter and exit relations need a position trigger")
        if self.trigger.kind is TriggerKind.EVENT:
            raise ValueError("event triggers are reserved until event chaining is implemented")
        return self

    def reserved_types(self) -> list[str]:
        """Condition types the current evaluator cannot run. Non-empty blocks activation."""
        return sorted(
            {leaf.type for leaf in iter_leaves(self.conditions) if leaf.type in RESERVED_TYPES}
        )

    def metrics(self) -> set[str]:
        keys: set[str] = set()
        for leaf in iter_leaves(self.conditions):
            if isinstance(leaf, ThresholdCondition | WindowCondition):
                keys.add(leaf.metric)
        return keys


def iter_leaves(condition: Any) -> list[Any]:
    if isinstance(condition, AllOf):
        return [leaf for child in condition.all for leaf in iter_leaves(child)]
    if isinstance(condition, AnyOf):
        return [leaf for child in condition.any for leaf in iter_leaves(child)]
    if isinstance(condition, NotOf):
        return iter_leaves(condition.not_)
    return [condition]


def parse_document(data: dict[str, Any]) -> RuleDocument:
    """Validate a document. Raises pydantic.ValidationError with field paths for the UI."""
    return RuleDocument.model_validate(data)


def json_schema() -> dict[str, Any]:
    """JSON schema of the rule document, served to the frontend builder."""
    return RuleDocument.model_json_schema()
