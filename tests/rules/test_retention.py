"""Trace retention per class (architecture 26.9)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from protect_rules.retention import apply_trace_retention
from shared.enums import TraceClass, TraceStatus
from shared.models import ProcessingStep, ProcessingTrace

pytestmark = pytest.mark.asyncio


def _trace(trace_class: str, age: timedelta) -> ProcessingTrace:
    return ProcessingTrace(
        root_object_type="test",
        root_object_id="x",
        status=TraceStatus.SUCCESS,
        trace_class=trace_class,
        started_at=datetime.now(UTC) - age,
    )


async def test_old_traces_go_per_class_and_steps_follow(db):
    kept_routine = _trace(TraceClass.ROUTINE, timedelta(days=10))
    old_routine = _trace(TraceClass.ROUTINE, timedelta(days=40))
    old_but_failed = _trace(TraceClass.FAILED, timedelta(days=40))
    ancient_failed = _trace(TraceClass.FAILED, timedelta(days=400))
    old_command = _trace(TraceClass.COMMAND, timedelta(days=200))
    old_audit = _trace(TraceClass.AUDIT, timedelta(days=800))
    rows = [kept_routine, old_routine, old_but_failed, ancient_failed, old_command, old_audit]
    db.add_all(rows)
    await db.flush()
    db.add(
        ProcessingStep(
            trace_id=old_routine.id,
            sequence=1,
            component="t",
            operation="o",
            status="success",
            started_at=datetime.now(UTC),
        )
    )
    await db.commit()
    ids = {r.id for r in rows}

    deleted = await apply_trace_retention(db)
    assert deleted[TraceClass.ROUTINE] >= 1
    assert deleted[TraceClass.FAILED] >= 1
    assert deleted[TraceClass.AUDIT] >= 1
    assert deleted[TraceClass.COMMAND] == 0 or old_command.id not in ids  # 200 days < 365
    remaining = set(await db.scalars(select(ProcessingTrace.id).where(ProcessingTrace.id.in_(ids))))
    assert remaining == {kept_routine.id, old_but_failed.id, old_command.id}
    steps = await db.scalar(
        select(func.count())
        .select_from(ProcessingStep)
        .where(ProcessingStep.trace_id == old_routine.id)
    )
    assert steps == 0
