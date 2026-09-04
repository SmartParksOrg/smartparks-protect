"""Test a rule version against history without side effects (architecture 15.5). Canonical
positions and measurements of the project are replayed in time order through the evaluator with
in-memory state; schedule rules step through time. Bounded: a replay scans at most
`MAX_SAMPLES` rows and returns at most `MAX_EVENTS` would-be events."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from shared.curation.effective import (
    effective_geom,
    effective_number,
    effective_time,
    in_window,
    visible,
)
from shared.models import Device, Entity, EntityCurrentState, Measurement, Position
from shared.rules.data import SqlDataAccess
from shared.rules.evaluator import Sample, Subject, SubjectState, evaluate, format_title
from shared.rules.schema import RuleDocument, Scope, TriggerKind

MAX_SAMPLES = 50_000
MAX_EVENTS = 500
MAX_SCHEDULE_STEPS = 5_000


class ReplayTooLarge(ValueError):
    pass


@dataclass(slots=True)
class ReplayEvent:
    time: datetime
    subject_key: str
    entity_id: uuid.UUID | None
    device_id: uuid.UUID | None
    title: str
    reason: str
    context: dict[str, Any]


@dataclass(slots=True)
class ReplayResult:
    events: list[ReplayEvent] = field(default_factory=list)
    total: int = 0
    samples: int = 0
    truncated: bool = False


def in_scope(
    scope: Scope,
    entity_id: uuid.UUID | None,
    entity_type_id: uuid.UUID | None,
    device_id: uuid.UUID | None,
) -> bool:
    if not (scope.entity_ids or scope.entity_type_ids or scope.device_ids):
        return True
    return (
        (entity_id is not None and entity_id in scope.entity_ids)
        or (entity_type_id is not None and entity_type_id in scope.entity_type_ids)
        or (device_id is not None and device_id in scope.device_ids)
    )


def position_values(
    speed_mps: float | None, altitude_m: float | None, lon: float, lat: float
) -> dict[str, float]:
    values: dict[str, float] = {"latitude": lat, "longitude": lon}
    if speed_mps is not None:
        values["speed_mps"] = speed_mps
        values["speed_kmh"] = speed_mps * 3.6
    if altitude_m is not None:
        values["altitude_m"] = altitude_m
    return values


async def entity_types(session: AsyncSession, project_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    rows = await session.execute(
        select(Entity.id, Entity.entity_type_id).where(Entity.project_id == project_id)
    )
    return {row[0]: row[1] for row in rows}


async def _names(
    session: AsyncSession, entity_id: uuid.UUID | None, device_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    entity = await session.get(Entity, entity_id) if entity_id else None
    device = await session.get(Device, device_id) if device_id else None
    return (entity.name if entity else None, device.name if device else None)


async def replay(
    session: AsyncSession,
    project_id: uuid.UUID,
    doc: RuleDocument,
    time_from: datetime,
    time_to: datetime,
    *,
    rule_name: str = "rule",
) -> ReplayResult:
    if time_to <= time_from:
        raise ReplayTooLarge("`to` must be after `from`")
    data = SqlDataAccess(session, historical=True)
    types = await entity_types(session, project_id)
    states: dict[str, SubjectState] = {}
    result = ReplayResult()
    names: dict[str, tuple[str | None, str | None]] = {}

    async def run(subject: Subject, sample: Sample) -> None:
        state = states.setdefault(subject.key, SubjectState())
        verdict = await evaluate(doc, subject, sample, state, data)
        if not verdict.fire:
            return
        result.total += 1
        if len(result.events) >= MAX_EVENTS:
            result.truncated = True
            return
        if subject.key not in names:
            names[subject.key] = await _names(session, subject.entity_id, subject.device_id)
        entity_name, device_name = names[subject.key]
        title = format_title(
            doc.event.title,
            entity=entity_name or device_name,
            device=device_name,
            feature=verdict.context.get("feature"),
            metric=verdict.context.get("metric"),
            value=verdict.context.get("value"),
            rule=rule_name,
        )
        result.events.append(
            ReplayEvent(
                time=sample.time,
                subject_key=subject.key,
                entity_id=subject.entity_id,
                device_id=subject.device_id,
                title=title,
                reason=verdict.reason,
                context=verdict.context,
            )
        )

    if doc.trigger.kind is TriggerKind.SCHEDULE:
        step = timedelta(seconds=doc.trigger.every_seconds)
        steps = int((time_to - time_from) / step)
        if steps > MAX_SCHEDULE_STEPS:
            raise ReplayTooLarge(
                f"{steps} schedule steps exceed {MAX_SCHEDULE_STEPS}; shorten the range"
            )
        subjects = await schedule_subjects(session, project_id, doc.scope, types)
        at = time_from
        while at <= time_to:
            for subject in subjects:
                result.samples += 1
                await run(subject, Sample(time=at, kind=TriggerKind.SCHEDULE))
            at += step
        return result

    if doc.trigger.kind is TriggerKind.POSITION:
        statement = (
            select(
                effective_time(Position),
                Position.entity_id,
                Position.device_id,
                effective_geom(),
                Position.speed_mps,
                Position.altitude_m,
                Position.source_event_id,
            )
            .where(
                Position.project_id == project_id,
                in_window(Position, time_from, time_to),
                visible(Position),
            )
            .order_by(effective_time(Position))
            .limit(MAX_SAMPLES + 1)
        )
        rows = (await session.execute(statement)).all()
        if len(rows) > MAX_SAMPLES:
            raise ReplayTooLarge(f"more than {MAX_SAMPLES} positions in range; shorten it")
        for time, entity_id, device_id, geom, speed, altitude, source_event_id in rows:
            if not in_scope(doc.scope, entity_id, types.get(entity_id), device_id):
                continue
            point = to_shape(geom)
            result.samples += 1
            await run(
                Subject(project_id, entity_id, device_id),
                Sample(
                    time=time,
                    kind=TriggerKind.POSITION,
                    values=position_values(speed, altitude, point.x, point.y),
                    point=(point.x, point.y),
                    source_event_id=source_event_id,
                ),
            )
        return result

    if doc.trigger.kind is TriggerKind.MEASUREMENT:
        statement = (
            select(
                effective_time(Measurement),
                Measurement.entity_id,
                Measurement.device_id,
                Measurement.metric_key,
                effective_number(),
                Measurement.source_event_id,
            )
            .where(
                Measurement.project_id == project_id,
                in_window(Measurement, time_from, time_to),
                visible(Measurement),
            )
            .order_by(effective_time(Measurement))
            .limit(MAX_SAMPLES + 1)
        )
        if doc.trigger.metric_key:
            statement = statement.where(Measurement.metric_key == doc.trigger.metric_key)
        rows = (await session.execute(statement)).all()
        if len(rows) > MAX_SAMPLES:
            raise ReplayTooLarge(f"more than {MAX_SAMPLES} measurements in range; shorten it")
        for time, entity_id, device_id, metric_key, val, source_event_id in rows:
            if val is None or not in_scope(doc.scope, entity_id, types.get(entity_id), device_id):
                continue
            result.samples += 1
            await run(
                Subject(project_id, entity_id, device_id),
                Sample(
                    time=time,
                    kind=TriggerKind.MEASUREMENT,
                    values={metric_key: float(val)},
                    metric_key=metric_key,
                    source_event_id=source_event_id,
                ),
            )
        return result

    raise ReplayTooLarge(f"replay does not support {doc.trigger.kind} triggers")


async def schedule_subjects(
    session: AsyncSession,
    project_id: uuid.UUID,
    scope: Scope,
    types: dict[uuid.UUID, uuid.UUID],
) -> list[Subject]:
    """Subjects a schedule rule evaluates: the project's entities (with their current device),
    plus devices named in the scope."""
    subjects: list[Subject] = []
    rows = await session.execute(
        select(Entity.id, EntityCurrentState.device_id)
        .outerjoin(EntityCurrentState, EntityCurrentState.entity_id == Entity.id)
        .where(Entity.project_id == project_id, Entity.status == "active")
        .limit(5_000)
    )
    for entity_id, device_id in rows:
        if in_scope(scope, entity_id, types.get(entity_id), None):
            subjects.append(Subject(project_id, entity_id, device_id))
    for device_id in scope.device_ids:
        subjects.append(Subject(project_id, None, device_id))
    return subjects


__all__ = [
    "MAX_EVENTS",
    "MAX_SAMPLES",
    "ReplayEvent",
    "ReplayResult",
    "ReplayTooLarge",
    "in_scope",
    "position_values",
    "replay",
    "schedule_subjects",
    "union_all",
]
