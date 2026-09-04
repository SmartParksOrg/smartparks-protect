"""The stateful rule evaluator (architecture 15).

`evaluate` takes a rule document, the subject (entity or device), the sample that triggered the
evaluation, the subject's stored state and a `DataAccess` for history, and answers whether the
rule fires now. It is pure apart from the data access, so the rules service, the replay runner
and the tests share it.

Firing semantics:
- The condition tree is evaluated for the sample. A FOR duration makes the condition count only
  once it has held continuously (as seen by the samples) for that long.
- Firing is edge-triggered: the rule fires when the condition becomes true. While it stays true
  it fires again only after `cooldown_seconds` (a reminder), never on every sample. ENTER and
  EXIT are true for the transition sample only, so they fire once per crossing.
- The state remembers whether the condition is active, since when it holds, when the rule last
  fired and which features the subject was inside of (needed for ENTER and EXIT).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from shared.rules.schema import (
    AllOf,
    AnyOf,
    NoDataCondition,
    NotOf,
    ReservedCondition,
    RuleDocument,
    SpatialCondition,
    ThresholdCondition,
    TriggerKind,
    WindowCondition,
)


class RuleNotSupported(Exception):
    """A reserved condition type reached the evaluator."""


@dataclass(frozen=True, slots=True)
class Subject:
    project_id: uuid.UUID
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None

    @property
    def key(self) -> str:
        if self.entity_id is not None:
            return f"entity:{self.entity_id}"
        return f"device:{self.device_id}"


@dataclass(slots=True)
class Sample:
    """What triggered the evaluation. `values` holds the metrics known without a lookup: the
    triggering measurement, or the derived metrics of a position."""

    time: datetime
    kind: TriggerKind
    values: dict[str, float] = field(default_factory=dict)
    point: tuple[float, float] | None = None
    metric_key: str | None = None
    source_event_id: int | None = None
    source_event_ingested_at: datetime | None = None
    age_seconds: float = 0.0


@dataclass(slots=True)
class FeatureGeometry:
    id: uuid.UUID
    name: str
    feature_type: str
    geometry: BaseGeometry


class DataAccess(Protocol):
    async def latest_value(
        self, subject: Subject, metric: str, before: datetime
    ) -> float | None: ...

    async def latest_point(
        self, subject: Subject, before: datetime
    ) -> tuple[tuple[float, float], datetime] | None: ...

    async def window(
        self, subject: Subject, metric: str, aggregate: str, seconds: int, at: datetime
    ) -> float | None: ...

    async def features(
        self, project_id: uuid.UUID, feature_ids: list[uuid.UUID], feature_type: str | None
    ) -> list[FeatureGeometry]: ...

    async def last_seen(self, subject: Subject, at: datetime) -> datetime | None: ...


@dataclass(slots=True)
class SubjectState:
    active: bool = False
    holding_since: datetime | None = None
    last_fired_at: datetime | None = None
    inside: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "holding_since": self.holding_since.isoformat() if self.holding_since else None,
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
            "inside": self.inside,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SubjectState":
        data = data or {}
        return cls(
            active=bool(data.get("active", False)),
            holding_since=_parse(data.get("holding_since")),
            last_fired_at=_parse(data.get("last_fired_at")),
            inside=dict(data.get("inside") or {}),
        )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(slots=True)
class Verdict:
    fire: bool
    condition: bool
    reason: str
    context: dict[str, Any]
    point: tuple[float, float] | None


@dataclass(slots=True)
class _Eval:
    doc: RuleDocument
    subject: Subject
    sample: Sample
    state: SubjectState
    data: DataAccess
    values: dict[str, Any] = field(default_factory=dict)
    inside_now: dict[str, bool] = field(default_factory=dict)
    feature: str | None = None
    metric: str | None = None
    value: float | None = None
    point: tuple[float, float] | None = None
    missing: list[str] = field(default_factory=list)


def compare(op: str, left: float, right: float) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    raise ValueError(f"unknown operator {op!r}")


async def _point(e: _Eval) -> tuple[float, float] | None:
    if e.point is not None:
        return e.point
    if e.sample.point is not None:
        e.point = e.sample.point
        return e.point
    latest = await e.data.latest_point(e.subject, e.sample.time)
    if latest is not None:
        e.point = latest[0]
    return e.point


async def _leaf(cond: Any, e: _Eval) -> bool:
    if isinstance(cond, ThresholdCondition):
        value = e.sample.values.get(cond.metric)
        if value is None:
            value = await e.data.latest_value(e.subject, cond.metric, e.sample.time)
        if value is None:
            e.missing.append(cond.metric)
            return False
        e.values[cond.metric] = value
        if e.metric is None:
            e.metric, e.value = cond.metric, value
        return compare(cond.op, value, cond.value)

    if isinstance(cond, SpatialCondition):
        point = await _point(e)
        if point is None:
            e.missing.append("position")
            return False
        features = await e.data.features(e.subject.project_id, cond.feature_ids, cond.feature_type)
        if not features:
            e.missing.append("features")
            return False
        location = Point(point[0], point[1])
        inside = {str(f.id): bool(f.geometry.covers(location)) for f in features}
        e.inside_now.update(inside)
        previous = e.state.inside
        if cond.relation == "inside":
            hits = [f for f in features if inside[str(f.id)]]
        elif cond.relation == "outside":
            hits = [] if any(inside.values()) else list(features)
        elif cond.relation == "enter":
            hits = [f for f in features if inside[str(f.id)] and previous.get(str(f.id)) is False]
        else:  # exit
            hits = [
                f for f in features if not inside[str(f.id)] and previous.get(str(f.id)) is True
            ]
        if hits:
            e.feature = hits[0].name
            e.values["features"] = [f.name for f in hits]
        return bool(hits)

    if isinstance(cond, NoDataCondition):
        last = await e.data.last_seen(e.subject, e.sample.time)
        if last is None:
            return False  # never reported is not "stopped reporting"
        gap = (e.sample.time - last).total_seconds()
        e.values["silence_hours"] = round(gap / 3600, 1)
        e.values["last_seen"] = last.isoformat()
        return gap >= cond.for_seconds

    if isinstance(cond, WindowCondition):
        value = await e.data.window(
            e.subject, cond.metric, cond.aggregate, cond.seconds, e.sample.time
        )
        if value is None:
            if cond.aggregate != "count":
                e.missing.append(f"{cond.aggregate}({cond.metric})")
                return False
            value = 0.0
        key = f"{cond.aggregate}_{cond.metric}"
        e.values[key] = value
        if e.metric is None:
            e.metric, e.value = cond.metric, value
        return compare(cond.op, value, cond.value)

    if isinstance(cond, ReservedCondition):
        raise RuleNotSupported(f"condition type {cond.type!r} is not implemented yet")
    raise RuleNotSupported(f"unknown condition {type(cond).__name__}")


async def _tree(cond: Any, e: _Eval) -> bool:
    if isinstance(cond, AllOf):
        result = True
        for child in cond.all:  # evaluate every branch so spatial state stays complete
            if not await _tree(child, e):
                result = False
        return result
    if isinstance(cond, AnyOf):
        result = False
        for child in cond.any:
            if await _tree(child, e):
                result = True
        return result
    if isinstance(cond, NotOf):
        return not await _tree(cond.not_, e)
    return await _leaf(cond, e)


async def evaluate(
    doc: RuleDocument,
    subject: Subject,
    sample: Sample,
    state: SubjectState,
    data: DataAccess,
) -> Verdict:
    """Evaluate one sample. Mutates `state`; the caller persists it."""
    e = _Eval(doc=doc, subject=subject, sample=sample, state=state, data=data)
    condition = await _tree(doc.conditions, e)
    if e.inside_now:
        state.inside = {**state.inside, **e.inside_now}

    if condition:
        if state.holding_since is None or sample.time < state.holding_since:
            state.holding_since = sample.time
        held = (sample.time - state.holding_since).total_seconds() >= doc.for_seconds
    else:
        state.holding_since = None
        held = False

    fire = False
    reason = "condition false" if not condition else "holding"
    if held:
        if not state.active:
            fire, reason = True, "condition became true"
        elif (
            doc.cooldown_seconds
            and state.last_fired_at is not None
            and (sample.time - state.last_fired_at).total_seconds() >= doc.cooldown_seconds
        ):
            fire, reason = True, "reminder after cooldown"
        else:
            reason = "still active"
        state.active = True
    else:
        state.active = False
    if fire:
        state.last_fired_at = sample.time

    context: dict[str, Any] = {
        "values": e.values,
        "trigger": sample.kind.value,
        "metric": e.metric or sample.metric_key,
        "value": e.value,
        "feature": e.feature,
    }
    if e.missing:
        context["missing"] = e.missing
    return Verdict(fire=fire, condition=condition, reason=reason, context=context, point=e.point)


class _Safe(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "?"


def format_title(template: str, **fields: Any) -> str:
    """`{entity}`, `{device}`, `{feature}`, `{metric}`, `{value}`, `{rule}`; unknown placeholders
    render as `?` instead of raising, a rule must never fail on its title."""
    values = {k: _format_value(v) for k, v in fields.items()}
    try:
        return template.format_map(_Safe(values))
    except (ValueError, IndexError, KeyError):
        return template


def _format_value(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)
