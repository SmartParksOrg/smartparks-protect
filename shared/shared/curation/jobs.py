"""Bulk curation jobs (architecture 28.5, 28.8, 28.9, decision D82).

A job is a selection (project, devices or entities, record type, metrics, an effective time
window) and one constrained transformation. `preview` counts the affected records, shows
samples before and after, and estimates the impact: attribution changes for a time shift,
outbound deliveries that will become stale, enabled rules. `run_job` applies the job as one
correction per record in batches of one transaction each, then recomputes the current state
of every device touched and, on request, runs the rule replay over the affected window as a
report. `revert` pops every correction of the job.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.curation.apply import (
    apply_correction,
    effective_of,
    model_for,
    recompute_current_state,
    revert_correction,
)
from shared.curation.effective import effective_time, effective_value_num, in_window
from shared.database import session_scope
from shared.domain.assignments import resolve_attribution
from shared.enums import (
    CorrectionStatus,
    CurationField,
    CurationJobStatus,
    CurationTarget,
    DeliveryStatus,
    ErrorCode,
)
from shared.logger import get_logger
from shared.models import (
    CurationJob,
    DataCorrection,
    IntegrationDelivery,
    Measurement,
    Position,
    Rule,
    RuleVersion,
)
from shared.rules.replay import ReplayTooLarge, replay
from shared.rules.schema import TriggerKind, parse_document
from shared.timeutil import utc_now
from shared.trace import ApplicationError

log = get_logger("curation")

MAX_JOB_ROWS = 200_000
PREVIEW_SAMPLES = 10
IMPACT_SCAN = 5_000
BATCH = 500


class Transformation(BaseModel):
    """The constrained transformations of architecture 28.5."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["time_offset", "set_valid", "value_offset", "value_scale"]
    seconds: int = Field(default=0, ge=-366 * 86400, le=366 * 86400)
    valid: bool = False
    delta: float = 0.0
    factor: float = Field(default=1.0, gt=0)

    @property
    def field(self) -> CurationField:
        return {
            "time_offset": CurationField.TIME,
            "set_valid": CurationField.VALID,
            "value_offset": CurationField.VALUE,
            "value_scale": CurationField.VALUE,
        }[self.kind]

    def apply(self, current: Any) -> Any:
        if self.kind == "time_offset":
            return (
                datetime.fromisoformat(str(current)) + timedelta(seconds=self.seconds)
            ).isoformat()
        if self.kind == "set_valid":
            return self.valid
        if self.kind == "value_offset":
            return float(current) + self.delta
        return float(current) * self.factor

    def describe(self) -> str:
        if self.kind == "time_offset":
            sign = "+" if self.seconds >= 0 else "-"
            return f"time {sign} {abs(self.seconds)} s"
        if self.kind == "set_valid":
            return "mark valid" if self.valid else "mark invalid"
        if self.kind == "value_offset":
            return f"value {'+' if self.delta >= 0 else '-'} {abs(self.delta)}"
        return f"value x {self.factor}"


def _error(message: str) -> ApplicationError:
    return ApplicationError(
        code=ErrorCode.CANONICALIZATION_FAILED,
        message=message,
        component="curation",
        user_actionable=True,
    )


def validate_job(job: CurationJob) -> Transformation:
    transformation = Transformation.model_validate(job.transformation)
    if job.time_to <= job.time_from:
        raise _error("the period must end after it starts")
    if (
        transformation.field == CurationField.VALUE
        and job.target_type != CurationTarget.MEASUREMENT
    ):
        raise _error("value transformations apply to measurements")
    if transformation.kind == "time_offset" and transformation.seconds == 0:
        raise _error("a time offset of zero changes nothing")
    return transformation


def conditions(job: CurationJob, transformation: Transformation) -> list[Any]:
    model = model_for(job.target_type)
    conditions: list[Any] = [
        model.project_id == job.project_id,
        in_window(model, job.time_from, job.time_to),
    ]
    if job.device_ids:
        conditions.append(model.device_id.in_([uuid.UUID(d) for d in job.device_ids]))
    if job.entity_ids:
        conditions.append(model.entity_id.in_([uuid.UUID(e) for e in job.entity_ids]))
    if job.target_type == CurationTarget.MEASUREMENT:
        if job.metric_keys:
            conditions.append(Measurement.metric_key.in_(list(job.metric_keys)))
        if transformation.field == CurationField.VALUE:
            conditions.append(effective_value_num().is_not(None))
    return conditions


def selection(job: CurationJob, transformation: Transformation) -> Select[Any]:
    return select(model_for(job.target_type)).where(*conditions(job, transformation))


def _sample(record: Position | Measurement, transformation: Transformation) -> dict[str, Any]:
    before = effective_of(record, transformation.field)
    return {
        "target_id": record.id,
        "target_time": record.time.isoformat(),
        "effective_time": (record.curated_time or record.time).isoformat(),
        "device_id": str(record.device_id),
        "entity_id": str(record.entity_id) if record.entity_id else None,
        "metric_key": getattr(record, "metric_key", None),
        "before": before,
        "after": transformation.apply(before),
    }


async def preview(session: AsyncSession, job: CurationJob) -> dict[str, Any]:
    """Count, samples and impact (architecture 28.5, 28.9, 28.10). Stored on the job."""
    transformation = validate_job(job)
    model = model_for(job.target_type)
    statement = selection(job, transformation)
    count = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    if count > MAX_JOB_ROWS:
        raise _error(
            f"{count} records exceed the job limit of {MAX_JOB_ROWS}; narrow the selection"
        )
    ordered = statement.order_by(effective_time(model), model.id)
    samples = [
        _sample(record, transformation)
        for record in (await session.scalars(ordered.limit(PREVIEW_SAMPLES))).all()
    ]
    scanned = (await session.scalars(ordered.limit(IMPACT_SCAN))).all()
    attribution_changes = 0
    if transformation.kind == "time_offset":
        cache: dict[tuple[uuid.UUID, datetime], tuple[uuid.UUID | None, uuid.UUID | None]] = {}
        for record in scanned:
            new_time = (record.curated_time or record.time) + timedelta(
                seconds=transformation.seconds
            )
            key = (record.device_id, new_time)
            if key not in cache:
                attribution = await resolve_attribution(session, record.device_id, new_time)
                cache[key] = (attribution.project_id, attribution.entity_id)
            if cache[key] != (record.project_id, record.entity_id):
                attribution_changes += 1
    deliveries = 0
    ids = [str(r.id) for r in scanned]
    for start in range(0, len(ids), 1000):
        deliveries += int(
            await session.scalar(
                select(func.count())
                .select_from(IntegrationDelivery)
                .where(
                    IntegrationDelivery.object_type == job.target_type,
                    IntegrationDelivery.object_id.in_(ids[start : start + 1000]),
                    IntegrationDelivery.status == DeliveryStatus.SENT,
                )
            )
            or 0
        )
    rules = int(
        await session.scalar(
            select(func.count())
            .select_from(Rule)
            .where(Rule.project_id == job.project_id, Rule.enabled.is_(True))
        )
        or 0
    )
    result = {
        "count": count,
        "transformation": transformation.describe(),
        "field": transformation.field.value,
        "samples": samples,
        "impact": {
            "scanned": len(scanned),
            "estimated": count > len(scanned),
            "attribution_changes": attribution_changes,
            "deliveries_sent": deliveries,
            "enabled_rules": rules,
        },
        "previewed_at": utc_now().isoformat(),
    }
    job.preview = result
    job.affected_count = count
    return result


async def replay_report(session: AsyncSession, job: CurationJob) -> dict[str, Any]:
    """What the enabled rules would have fired over the corrected window (decision D82): a
    report, not events. The window covers the records before and after a time shift."""
    transformation = Transformation.model_validate(job.transformation)
    shift = (
        timedelta(seconds=transformation.seconds)
        if transformation.kind == "time_offset"
        else timedelta()
    )
    time_from = min(job.time_from, job.time_from + shift)
    time_to = max(job.time_to, job.time_to + shift)
    wanted = (
        TriggerKind.POSITION
        if job.target_type == CurationTarget.POSITION
        else TriggerKind.MEASUREMENT
    )
    rows = (
        await session.execute(
            select(Rule, RuleVersion)
            .join(
                RuleVersion,
                (RuleVersion.rule_id == Rule.id) & (RuleVersion.version == Rule.current_version),
            )
            .where(Rule.project_id == job.project_id, Rule.enabled.is_(True))
            .order_by(Rule.name)
        )
    ).all()
    report: list[dict[str, Any]] = []
    for rule, version in rows:
        try:
            doc = parse_document(version.document)
        except Exception as exc:  # a stored document that no longer parses
            report.append({"rule": rule.name, "error": str(exc)})
            continue
        if doc.trigger.kind is not wanted:
            continue
        try:
            result = await replay(
                session, job.project_id, doc, time_from, time_to, rule_name=rule.name
            )
        except ReplayTooLarge as exc:
            report.append({"rule": rule.name, "error": str(exc)})
            continue
        report.append(
            {
                "rule": rule.name,
                "rule_id": str(rule.id),
                "events": result.total,
                "samples": result.samples,
                "truncated": result.truncated,
                "first_events": [
                    {"time": e.time.isoformat(), "title": e.title, "subject": e.subject_key}
                    for e in result.events[:5]
                ],
            }
        )
    return {"from": time_from.isoformat(), "to": time_to.isoformat(), "rules": report}


async def _keys(
    session: AsyncSession, job: CurationJob, transformation: Transformation
) -> list[tuple[int, datetime]]:
    model = model_for(job.target_type)
    statement = (
        select(model.id, model.time)
        .where(*conditions(job, transformation))
        .order_by(effective_time(model), model.id)
        .limit(MAX_JOB_ROWS + 1)
    )
    rows = (await session.execute(statement)).all()
    if len(rows) > MAX_JOB_ROWS:
        raise _error(f"more than {MAX_JOB_ROWS} records; narrow the selection")
    return [(int(r[0]), r[1]) for r in rows]


async def apply_job(job_id: uuid.UUID, *, user_id: uuid.UUID | None) -> None:
    async with session_scope() as session:
        job = await session.get(CurationJob, job_id)
        if job is None:
            return
        transformation = validate_job(job)
        job.status = CurationJobStatus.APPLYING
        job.error_message = None
        await session.commit()
        keys = await _keys(session, job, transformation)
        project_id = job.project_id
        target_type = job.target_type
        reason, comment = job.reason_code, job.comment
        replay_rules = bool(job.replay_rules)

    devices: dict[uuid.UUID, set[uuid.UUID | None]] = {}
    applied = 0
    flagged = 0
    model = model_for(target_type)
    for start in range(0, len(keys), BATCH):
        batch = keys[start : start + BATCH]
        async with session_scope() as session:
            job = await session.get(CurationJob, job_id)
            assert job is not None
            rows = cast(
                Sequence[Position | Measurement],
                (
                    await session.scalars(
                        select(model).where(
                            model.id.in_([k[0] for k in batch]),
                            model.time.in_([k[1] for k in batch]),
                        )
                    )
                ).all(),
            )
            by_key = {(r.id, r.time): r for r in rows}
            for key in batch:
                record = by_key.get(key)
                if record is None:
                    continue
                before = effective_of(record, transformation.field)
                correction = DataCorrection(
                    project_id=project_id,
                    target_type=target_type,
                    target_id=record.id,
                    target_time=record.time,
                    device_id=record.device_id,
                    entity_id=record.entity_id,
                    metric_key=getattr(record, "metric_key", None),
                    field=transformation.field,
                    original_value=before,
                    corrected_value=transformation.apply(before),
                    reason_code=reason,
                    comment=comment,
                    status=CorrectionStatus.PENDING,
                    curation_job_id=job_id,
                    created_by_user_id=user_id,
                    applied_at=None,
                )
                session.add(correction)
                await session.flush()
                result = await apply_correction(session, correction)
                devices.setdefault(result.device_id, set()).update(result.entity_ids)
                flagged += result.deliveries_flagged
                applied += 1
            job.applied_count = applied
            await session.commit()

    async with session_scope() as session:
        job = await session.get(CurationJob, job_id)
        assert job is not None
        for device_id, entity_ids in devices.items():
            await recompute_current_state(session, device_id, entity_ids)
        impact: dict[str, Any] = {
            **(job.impact or {}),
            "applied": applied,
            "deliveries_flagged": flagged,
            "devices": len(devices),
        }
        if replay_rules:
            impact["replay"] = await replay_report(session, job)
        job.impact = impact
        job.status = CurationJobStatus.APPLIED
        job.applied_at = utc_now()
        job.applied_by_user_id = user_id
        job.applied_count = applied
        await session.commit()


async def revert_job(job_id: uuid.UUID, *, user_id: uuid.UUID | None, comment: str | None) -> None:
    async with session_scope() as session:
        job = await session.get(CurationJob, job_id)
        if job is None:
            return
        job.status = CurationJobStatus.REVERTING
        await session.commit()
        ids = list(
            (
                await session.scalars(
                    select(DataCorrection.id)
                    .where(
                        DataCorrection.curation_job_id == job_id,
                        DataCorrection.status == CorrectionStatus.ACTIVE,
                    )
                    .order_by(DataCorrection.created_at.desc())
                )
            ).all()
        )
    devices: dict[uuid.UUID, set[uuid.UUID | None]] = {}
    reverted = 0
    for start in range(0, len(ids), BATCH):
        async with session_scope() as session:
            job = await session.get(CurationJob, job_id)
            assert job is not None
            for correction_id in ids[start : start + BATCH]:
                correction = await session.get(DataCorrection, correction_id)
                if correction is None or correction.status != CorrectionStatus.ACTIVE:
                    continue
                result = await revert_correction(
                    session, correction, user_id=user_id, comment=comment
                )
                devices.setdefault(result.device_id, set()).update(result.entity_ids)
                reverted += 1
            job.reverted_count = reverted
            await session.commit()
    async with session_scope() as session:
        job = await session.get(CurationJob, job_id)
        assert job is not None
        for device_id, entity_ids in devices.items():
            await recompute_current_state(session, device_id, entity_ids)
        job.status = CurationJobStatus.REVERTED
        job.reverted_at = utc_now()
        job.reverted_by_user_id = user_id
        job.reverted_count = reverted
        await session.commit()


async def run_job(bus: RedisStreamsBus, payload: dict[str, Any]) -> None:
    """Worker entry: `curation.job_requested` with `job_id` and `action` (apply or revert)."""
    job_id = uuid.UUID(str(payload["job_id"]))
    action = str(payload.get("action", "apply"))
    user_id = uuid.UUID(str(payload["user_id"])) if payload.get("user_id") else None
    try:
        if action == "revert":
            await revert_job(job_id, user_id=user_id, comment=payload.get("comment"))
        else:
            await apply_job(job_id, user_id=user_id)
    except ApplicationError as error:
        async with session_scope() as session:
            job = await session.get(CurationJob, job_id)
            if job is not None:
                job.status = CurationJobStatus.FAILED
                job.error_message = str(error)
                await session.commit()
        log.warning("curation job failed", job_id=str(job_id), error=str(error))
        return
    async with session_scope() as session:
        job = await session.get(CurationJob, job_id)
        if job is None:
            return
        await bus.publish(
            Topic.CURATION_APPLIED,
            {
                "job_id": str(job.id),
                "project_id": str(job.project_id),
                "action": action,
                "status": job.status,
                "target_type": job.target_type,
                "device_ids": list(job.device_ids or []),
                "time_from": job.time_from.isoformat(),
                "time_to": job.time_to.isoformat(),
            },
        )
    log.info("curation job finished", job_id=str(job_id), action=action)
