"""Rules engine: which rules a sample touches, evaluation, event creation, state persistence
(architecture 15). Each rule is evaluated in its own transaction so one failing rule cannot
block the others; a failure lands on `rules.last_error` and a failed trace. A rule that fires
gets a compact trace with the matched subject, the evaluated values, the event and the alert;
silent evaluations write nothing (a trace per position per rule would outgrow the telemetry).
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import Float, Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import session_scope
from shared.enums import ErrorCode, TraceClass
from shared.logger import get_logger
from shared.models import (
    Device,
    Entity,
    Measurement,
    Position,
    Rule,
    RuleState,
    RuleVersion,
)
from shared.rules.data import SqlDataAccess
from shared.rules.evaluator import (
    RuleNotSupported,
    Sample,
    Subject,
    SubjectState,
    evaluate,
    format_title,
)
from shared.rules.events import NewEvent, create_event, event_messages
from shared.rules.replay import (
    entity_types,
    in_scope,
    position_values,
    schedule_subjects,
)
from shared.rules.schema import RuleDocument, TriggerKind
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("rules")


def func_value() -> Any:
    """Numeric value of a measurement: the number, or a boolean as 0 and 1."""
    return func.coalesce(Measurement.value_num, cast(cast(Measurement.value_bool, Integer), Float))


@dataclass(slots=True)
class LoadedRule:
    rule_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version_id: uuid.UUID
    version: int
    doc: RuleDocument


class RuleCache:
    """Enabled rules with their current version, per project, re-read every
    `RULES_RELOAD_SECONDS`."""

    def __init__(self) -> None:
        self._by_project: dict[uuid.UUID, list[LoadedRule]] = {}
        self._loaded_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def rules(self, project_id: uuid.UUID, kind: TriggerKind) -> list[LoadedRule]:
        await self._refresh_if_due()
        return [r for r in self._by_project.get(project_id, []) if r.doc.trigger.kind is kind]

    async def all(self, kind: TriggerKind) -> list[LoadedRule]:
        await self._refresh_if_due()
        return [
            r for rules in self._by_project.values() for r in rules if r.doc.trigger.kind is kind
        ]

    async def _refresh_if_due(self) -> None:
        settings = get_settings()
        now = utc_now()
        if (
            self._loaded_at is not None
            and (now - self._loaded_at).total_seconds() < settings.rules_reload_seconds
        ):
            return
        async with self._lock:
            if (
                self._loaded_at is not None
                and (now - self._loaded_at).total_seconds() < settings.rules_reload_seconds
            ):
                return
            await self.reload()

    async def reload(self) -> None:
        async with session_scope() as session:
            rows = await session.execute(
                select(Rule, RuleVersion)
                .join(
                    RuleVersion,
                    (RuleVersion.rule_id == Rule.id)
                    & (RuleVersion.version == Rule.current_version),
                )
                .where(Rule.enabled.is_(True))
            )
            loaded: dict[uuid.UUID, list[LoadedRule]] = {}
            for rule, version in rows:
                try:
                    doc = RuleDocument.model_validate(version.document)
                except ValueError as exc:
                    log.error(
                        "rule document invalid, skipped", rule_id=str(rule.id), error=str(exc)
                    )
                    continue
                loaded.setdefault(rule.project_id, []).append(
                    LoadedRule(
                        rule_id=rule.id,
                        project_id=rule.project_id,
                        name=rule.name,
                        version_id=version.id,
                        version=version.version,
                        doc=doc,
                    )
                )
        self._by_project = loaded
        self._loaded_at = utc_now()


async def _load_state(session: AsyncSession, rule_id: uuid.UUID, key: str) -> RuleState:
    row = await session.get(RuleState, (rule_id, key))
    if row is None:
        row = RuleState(rule_id=rule_id, subject_key=key, state={})
        session.add(row)
    return row


async def evaluate_rule(
    session: AsyncSession,
    bus: RedisStreamsBus,
    loaded: LoadedRule,
    subject: Subject,
    sample: Sample,
    data: SqlDataAccess,
) -> list[tuple[str, dict[str, Any]]]:
    """Evaluate one rule for one subject inside the caller's transaction. Returns the bus
    messages to publish after commit."""
    row = await _load_state(session, loaded.rule_id, subject.key)
    state = SubjectState.from_dict(row.state)
    try:
        verdict = await evaluate(loaded.doc, subject, sample, state, data)
    except RuleNotSupported as exc:
        raise ApplicationError(
            code=ErrorCode.RULE_EVALUATION_FAILED,
            message=str(exc),
            component="rules",
            user_actionable=True,
            context={"rule_id": str(loaded.rule_id)},
        ) from exc
    row.state = state.to_dict()
    row.updated_at = utc_now()
    if not verdict.fire:
        return []

    tracer = Tracer(
        session,
        root_object_type="rule",
        root_object_id=str(loaded.rule_id),
        compact=True,
        project_id=subject.project_id,
        device_id=subject.device_id,
    )
    await tracer.start()
    async with tracer.step("rules", "rule matched", input_ref=subject.key) as step:
        step.metadata.update(rule=loaded.name, version=loaded.version, trigger=sample.kind.value)
    async with tracer.step("rules", "conditions evaluated") as step:
        step.metadata.update(reason=verdict.reason, values=verdict.context.get("values", {}))
    entity = await session.get(Entity, subject.entity_id) if subject.entity_id else None
    device = await session.get(Device, subject.device_id) if subject.device_id else None
    title = format_title(
        loaded.doc.event.title,
        entity=entity.name if entity else (device.name if device else None),
        device=device.name if device else None,
        feature=verdict.context.get("feature"),
        metric=verdict.context.get("metric"),
        value=verdict.context.get("value"),
        rule=loaded.name,
    )
    async with tracer.step("rules", "event created") as step:
        event, alert = await create_event(
            session,
            NewEvent(
                time=sample.time,
                event_type=loaded.doc.event.event_type,
                severity=loaded.doc.event.severity,
                title=title,
                description=loaded.doc.event.description,
                project_id=subject.project_id,
                entity_id=subject.entity_id,
                device_id=subject.device_id,
                point=verdict.point,
                context={
                    **verdict.context,
                    "rule_id": str(loaded.rule_id),
                    "rule_name": loaded.name,
                    "rule_version": loaded.version,
                    "subject_key": subject.key,
                    "age_seconds": sample.age_seconds,
                },
                rule_version_id=loaded.version_id,
                source_event_id=sample.source_event_id,
                source_event_ingested_at=sample.source_event_ingested_at,
                trace_id=tracer.trace_id,
                create_alert=loaded.doc.event.create_alert,
            ),
        )
        step.output_ref = f"event:{event.id}"
        if alert is not None:
            step.metadata["alert_id"] = str(alert.id)
    await tracer.finish()
    rule = await session.get(Rule, loaded.rule_id)
    if rule is not None:
        rule.last_fired_at = utc_now()
        rule.last_error = None
    log.info(
        "rule fired",
        rule=loaded.name,
        subject=subject.key,
        event_id=str(event.id),
        alert=alert is not None,
    )
    return event_messages(event, alert, rule_id=loaded.rule_id)


async def run_rules(
    bus: RedisStreamsBus,
    rules: list[LoadedRule],
    subject: Subject,
    sample: Sample,
    entity_type_id: uuid.UUID | None,
) -> int:
    """Evaluate every rule in scope, each in its own transaction. Returns how many fired."""
    fired = 0
    for loaded in rules:
        if not in_scope(loaded.doc.scope, subject.entity_id, entity_type_id, subject.device_id):
            continue
        if (
            loaded.doc.trigger.kind is TriggerKind.MEASUREMENT
            and loaded.doc.trigger.metric_key
            and loaded.doc.trigger.metric_key != sample.metric_key
        ):
            continue
        messages: list[tuple[str, dict[str, Any]]] = []
        try:
            async with session_scope() as session:
                data = SqlDataAccess(session)
                messages = await evaluate_rule(session, bus, loaded, subject, sample, data)
                await session.commit()
        except ApplicationError as error:
            await _record_failure(loaded, error)
            continue
        except Exception as exc:  # a bug in one rule must not stop the others
            log.error("rule evaluation crashed", rule=loaded.name, exc_info=True)
            await _record_failure(
                loaded,
                ApplicationError(
                    code=ErrorCode.RULE_EVALUATION_FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                    component="rules",
                ),
            )
            continue
        for topic, payload in messages:
            await bus.publish(topic, payload)
        fired += len(messages) > 0
    return fired


async def _record_failure(loaded: LoadedRule, error: ApplicationError) -> None:
    async with session_scope() as session:
        rule = await session.get(Rule, loaded.rule_id)
        if rule is not None:
            rule.last_error = str(error)[:2000]
        tracer = Tracer(
            session,
            root_object_type="rule",
            root_object_id=str(loaded.rule_id),
            trace_class=TraceClass.FAILED,
            project_id=loaded.project_id,
        )
        await tracer.start()
        try:
            async with tracer.step("rules", "rule evaluated"):
                raise error
        except ApplicationError:
            pass
        await session.commit()
    log.warning("rule evaluation failed", rule=loaded.name, error=str(error))


async def handle_position(bus: RedisStreamsBus, cache: RuleCache, payload: dict[str, Any]) -> None:
    project_id = payload.get("project_id")
    if not project_id:
        return
    rules = await cache.rules(uuid.UUID(project_id), TriggerKind.POSITION)
    if not rules:
        return
    async with session_scope() as session:
        position = await session.scalar(
            select(Position).where(
                Position.id == int(payload["position_id"]),
                Position.time == datetime.fromisoformat(payload["time"]),
            )
        )
        if position is None:
            return
        entity_type_id = None
        if position.entity_id is not None:
            entity_type_id = await session.scalar(
                select(Entity.entity_type_id).where(Entity.id == position.entity_id)
            )
        point = to_shape(position.geom)
        sample = Sample(
            time=position.time,
            kind=TriggerKind.POSITION,
            values=position_values(position.speed_mps, position.altitude_m, point.x, point.y),
            point=(point.x, point.y),
            source_event_id=position.source_event_id,
            source_event_ingested_at=position.source_event_ingested_at,
            age_seconds=float(payload.get("age_seconds") or 0.0),
        )
        subject = Subject(position.project_id, position.entity_id, position.device_id)  # type: ignore[arg-type]
    await run_rules(bus, rules, subject, sample, entity_type_id)


async def handle_measurements(
    bus: RedisStreamsBus, cache: RuleCache, payload: dict[str, Any]
) -> None:
    ids = [int(i) for i in payload.get("measurement_ids", [])]
    if not ids or not await cache.all(TriggerKind.MEASUREMENT):
        return  # nothing to evaluate: skip the row loads (matters when catching up a backlog)
    value = func_value()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    Measurement.time,
                    Measurement.project_id,
                    Measurement.entity_id,
                    Measurement.device_id,
                    Measurement.metric_key,
                    value,
                    Measurement.source_event_id,
                    Measurement.source_event_ingested_at,
                    Measurement.ingested_at,
                )
                .where(Measurement.id.in_(ids))
                .order_by(Measurement.time)
            )
        ).all()
        types: dict[uuid.UUID, uuid.UUID] = {}
        for row in rows:
            if row[1] is not None and row[2] is not None and row[1] not in types:
                types.update(await entity_types(session, row[1]))
    for (
        time,
        project_id,
        entity_id,
        device_id,
        metric_key,
        val,
        source_event_id,
        ingested,
        ingested_at,
    ) in rows:
        if project_id is None or val is None:
            continue
        rules = await cache.rules(project_id, TriggerKind.MEASUREMENT)
        if not rules:
            continue
        sample = Sample(
            time=time,
            kind=TriggerKind.MEASUREMENT,
            values={metric_key: float(val)},
            metric_key=metric_key,
            source_event_id=source_event_id,
            source_event_ingested_at=ingested,
            age_seconds=(ingested_at - time).total_seconds(),
        )
        await run_rules(
            bus, rules, Subject(project_id, entity_id, device_id), sample, types.get(entity_id)
        )


async def handle_state(bus: RedisStreamsBus, cache: RuleCache, payload: dict[str, Any]) -> None:
    """Device state changes carry a dict; numeric entries become values for threshold rules."""
    device_id = payload.get("device_id")
    if not device_id:
        return
    if not await cache.all(TriggerKind.STATE):
        return
    state = payload.get("state") or {}
    values = {
        k: float(v)
        for k, v in state.items()
        if isinstance(v, int | float) and not isinstance(v, bool)
    }
    if not values:
        return
    async with session_scope() as session:
        from shared.domain.assignments import resolve_attribution

        time = datetime.fromisoformat(payload["time"])
        attribution = await resolve_attribution(session, uuid.UUID(device_id), time)
        if attribution.project_id is None:
            return
        entity_type_id = (
            await session.scalar(
                select(Entity.entity_type_id).where(Entity.id == attribution.entity_id)
            )
            if attribution.entity_id
            else None
        )
    rules = await cache.rules(attribution.project_id, TriggerKind.STATE)
    if not rules:
        return
    sample = Sample(
        time=time,
        kind=TriggerKind.STATE,
        values=values,
        source_event_id=payload.get("source_event_id"),
    )
    await run_rules(
        bus,
        rules,
        Subject(attribution.project_id, attribution.entity_id, uuid.UUID(device_id)),
        sample,
        entity_type_id,
    )


class Scheduler:
    """Runs schedule-triggered rules every `every_seconds` over the subjects in scope."""

    def __init__(self, bus: RedisStreamsBus, cache: RuleCache) -> None:
        self.bus = bus
        self.cache = cache
        self.last_run: dict[uuid.UUID, datetime] = {}

    async def tick(self, now: datetime | None = None) -> int:
        now = now or utc_now()
        fired = 0
        for loaded in await self.cache.all(TriggerKind.SCHEDULE):
            last = self.last_run.get(loaded.rule_id)
            if last is not None and (now - last).total_seconds() < loaded.doc.trigger.every_seconds:
                continue
            self.last_run[loaded.rule_id] = now
            fired += await self.run_rule(loaded, now)
        return fired

    async def run_rule(self, loaded: LoadedRule, now: datetime) -> int:
        async with session_scope() as session:
            types = await entity_types(session, loaded.project_id)
            subjects = await schedule_subjects(session, loaded.project_id, loaded.doc.scope, types)
        fired = 0
        for subject in subjects:
            sample = Sample(time=now, kind=TriggerKind.SCHEDULE)
            fired += await run_rules(
                self.bus,
                [loaded],
                subject,
                sample,
                types.get(subject.entity_id),  # type: ignore[arg-type]
            )
        return fired
