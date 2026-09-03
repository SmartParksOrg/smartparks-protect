"""ProcessingTrace helpers (architecture 26).

Usage in a worker or endpoint:

    tracer = Tracer(session, root_object_type="source_event", root_object_id=str(event_id),
                    device_id=device.id, compact=True)
    await tracer.start()
    async with tracer.step("decoder", "decode payload", input_ref=f"source_event:{event_id}"):
        records = driver.decode(event)
    await tracer.finish()

A step that raises `ApplicationError` records the structured error and marks the step and the
trace failed. Any other exception is recorded as INTERNAL_ERROR and re-raised: crash early.
Compact traces (routine successful telemetry) keep their steps as JSON on the trace row instead
of one row per step (architecture 26.9).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import ErrorCode, ErrorSeverity, TraceClass, TraceStatus
from shared.models import ApplicationError as ApplicationErrorRow
from shared.models import ProcessingStep, ProcessingTrace
from shared.timeutil import utc_now


@dataclass
class ApplicationError(Exception):
    """A structured, expected failure. Not a bug: the code, flags and context tell an
    administrator what happened and whether a retry or an action helps."""

    code: ErrorCode
    message: str
    component: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    retryable: bool = False
    user_actionable: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_row(self) -> ApplicationErrorRow:
        return ApplicationErrorRow(
            error_code=self.code,
            severity=self.severity,
            retryable=self.retryable,
            user_actionable=self.user_actionable,
            component=self.component,
            message=self.message,
            technical_context=self.context,
        )


class Tracer:
    def __init__(
        self,
        session: AsyncSession,
        *,
        root_object_type: str,
        root_object_id: str,
        trace_class: TraceClass = TraceClass.ROUTINE,
        compact: bool = False,
        project_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        data_source_id: uuid.UUID | None = None,
        actor: dict[str, Any] | None = None,
        trace_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.compact = compact
        self.trace = ProcessingTrace(
            id=trace_id or uuid.uuid4(),
            root_object_type=root_object_type,
            root_object_id=root_object_id,
            status=TraceStatus.PROCESSING,
            trace_class=trace_class,
            compact=compact,
            compact_steps=[] if compact else None,
            project_id=project_id,
            device_id=device_id,
            data_source_id=data_source_id,
            actor=actor,
        )
        self._sequence = 0
        self._failed = False

    @property
    def trace_id(self) -> uuid.UUID:
        return self.trace.id

    async def start(self) -> ProcessingTrace:
        self.trace.started_at = utc_now()
        self.session.add(self.trace)
        await self.session.flush()
        return self.trace

    @classmethod
    async def resume(cls, session: AsyncSession, trace_id: uuid.UUID) -> "Tracer":
        """Continue a trace another service started (ingest starts, decoder continues)."""
        trace = await session.get(ProcessingTrace, trace_id)
        if trace is None:
            raise ValueError(f"trace {trace_id} not found")
        tracer = cls.__new__(cls)
        tracer.session = session
        tracer.compact = trace.compact
        tracer.trace = trace
        tracer._failed = trace.status in (TraceStatus.FAILED, TraceStatus.DEAD_LETTER)
        if trace.compact:
            tracer._sequence = len(trace.compact_steps or [])
        else:
            last = await session.scalar(
                select(func.max(ProcessingStep.sequence)).where(ProcessingStep.trace_id == trace.id)
            )
            tracer._sequence = int(last or 0)
        trace.status = TraceStatus.PROCESSING
        trace.completed_at = None
        return tracer

    @asynccontextmanager
    async def step(
        self,
        component: str,
        operation: str,
        *,
        input_ref: str | None = None,
        output_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator["StepHandle"]:
        self._sequence += 1
        handle = StepHandle(
            sequence=self._sequence,
            component=component,
            operation=operation,
            started_at=utc_now(),
            input_ref=input_ref,
            output_ref=output_ref,
            metadata=metadata or {},
        )
        try:
            yield handle
        except ApplicationError as error:
            handle.status = TraceStatus.FAILED
            await self._record(handle, error)
            self._failed = True
            self.trace.status = TraceStatus.FAILED
            self.trace.trace_class = TraceClass.FAILED
            self.trace.completed_at = utc_now()
            await self.session.flush()
            raise
        except Exception as exc:
            internal = ApplicationError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"{type(exc).__name__}: {exc}",
                component=component,
                severity=ErrorSeverity.CRITICAL,
            )
            handle.status = TraceStatus.FAILED
            await self._record(handle, internal)
            self._failed = True
            self.trace.status = TraceStatus.FAILED
            self.trace.trace_class = TraceClass.FAILED
            self.trace.completed_at = utc_now()
            await self.session.flush()
            raise
        else:
            if handle.status == TraceStatus.PROCESSING:
                handle.status = TraceStatus.SUCCESS
            await self._record(handle, None)

    async def _record(self, handle: "StepHandle", error: ApplicationError | None) -> None:
        completed = utc_now()
        duration_ms = int((completed - handle.started_at).total_seconds() * 1000)
        error_row: ApplicationErrorRow | None = None
        if error is not None:
            error_row = error.to_row()
            self.session.add(error_row)
            await self.session.flush()
            if self.trace.error_id is None:
                self.trace.error_id = error_row.id
        if self.compact and error is None:
            assert self.trace.compact_steps is not None
            self.trace.compact_steps = [
                *self.trace.compact_steps,
                {
                    "sequence": handle.sequence,
                    "component": handle.component,
                    "operation": handle.operation,
                    "status": handle.status,
                    "duration_ms": duration_ms,
                    "output_ref": handle.output_ref,
                },
            ]
            return
        self.session.add(
            ProcessingStep(
                trace_id=self.trace.id,
                sequence=handle.sequence,
                component=handle.component,
                operation=handle.operation,
                status=handle.status,
                started_at=handle.started_at,
                completed_at=completed,
                duration_ms=duration_ms,
                input_ref=handle.input_ref,
                output_ref=handle.output_ref,
                error_id=error_row.id if error_row is not None else None,
                metadata_=handle.metadata,
            )
        )

    async def finish(self, status: TraceStatus = TraceStatus.SUCCESS) -> ProcessingTrace:
        if not self._failed:
            self.trace.status = status
        self.trace.completed_at = utc_now()
        await self.session.flush()
        return self.trace


@dataclass
class StepHandle:
    sequence: int
    component: str
    operation: str
    started_at: datetime
    input_ref: str | None
    output_ref: str | None
    metadata: dict[str, Any]
    status: TraceStatus = TraceStatus.PROCESSING

    def skip(self, reason: str) -> None:
        self.status = TraceStatus.SKIPPED
        self.metadata["reason"] = reason

    def duplicate(self, of: str) -> None:
        self.status = TraceStatus.DUPLICATE
        self.output_ref = of
