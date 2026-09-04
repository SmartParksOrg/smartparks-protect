"""Trace retention per class (architecture 26.9): routine telemetry traces are short-lived,
failed flows, commands and audit-class traces live longer. Runs daily from the rules service
ticker and deletes in bounded batches so one run never holds a long transaction."""

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.enums import TraceClass
from shared.logger import get_logger
from shared.models import ProcessingTrace
from shared.timeutil import utc_now

log = get_logger("rules.retention")

BATCH = 5_000
MAX_BATCHES = 200


def retention_days() -> dict[str, int]:
    settings = get_settings()
    return {
        TraceClass.ROUTINE: settings.trace_retention_routine_days,
        TraceClass.FAILED: settings.trace_retention_failed_days,
        TraceClass.COMMAND: settings.trace_retention_command_days,
        TraceClass.AUDIT: settings.trace_retention_audit_days,
    }


async def apply_trace_retention(session: AsyncSession) -> dict[str, int]:
    """Delete traces older than their class allows. Steps cascade; application errors stay
    referenced by nothing and are removed with the trace they belonged to. Returns the count
    per class."""
    now = utc_now()
    deleted: dict[str, int] = {}
    for trace_class, days in retention_days().items():
        cutoff = now - timedelta(days=days)
        total = 0
        for _ in range(MAX_BATCHES):
            ids = list(
                await session.scalars(
                    select(ProcessingTrace.id)
                    .where(
                        ProcessingTrace.trace_class == trace_class,
                        ProcessingTrace.started_at < cutoff,
                    )
                    .limit(BATCH)
                )
            )
            if not ids:
                break
            await session.execute(delete(ProcessingTrace).where(ProcessingTrace.id.in_(ids)))
            await session.commit()
            total += len(ids)
            if len(ids) < BATCH:
                break
        deleted[str(trace_class)] = total
    if any(deleted.values()):
        log.info("trace retention applied", counts=deleted)
    return deleted
