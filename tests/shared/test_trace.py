import pytest
from sqlalchemy import select

from shared.enums import ErrorCode, TraceClass, TraceStatus
from shared.models import ApplicationError as ApplicationErrorRow
from shared.models import ProcessingStep
from shared.trace import ApplicationError, Tracer

pytestmark = pytest.mark.asyncio


async def test_full_trace_records_steps(session):
    tracer = Tracer(session, root_object_type="source_event", root_object_id="1")
    await tracer.start()
    async with tracer.step("ingest", "store source event", output_ref="source_event:1"):
        pass
    async with tracer.step("decoder", "decode") as step:
        step.duplicate(of="position:9")
    trace = await tracer.finish()

    steps = (
        (
            await session.execute(
                select(ProcessingStep)
                .where(ProcessingStep.trace_id == trace.id)
                .order_by(ProcessingStep.sequence)
            )
        )
        .scalars()
        .all()
    )
    assert [s.status for s in steps] == [TraceStatus.SUCCESS, TraceStatus.DUPLICATE]
    assert steps[1].output_ref == "position:9"
    assert trace.status == TraceStatus.SUCCESS
    assert trace.completed_at is not None


async def test_compact_trace_keeps_steps_inline(session):
    tracer = Tracer(session, root_object_type="source_event", root_object_id="2", compact=True)
    await tracer.start()
    async with tracer.step("decoder", "decode"):
        pass
    trace = await tracer.finish()
    rows = (
        (await session.execute(select(ProcessingStep).where(ProcessingStep.trace_id == trace.id)))
        .scalars()
        .all()
    )
    assert rows == []
    assert trace.compact_steps and trace.compact_steps[0]["operation"] == "decode"


async def test_application_error_marks_trace_failed(session):
    tracer = Tracer(session, root_object_type="source_event", root_object_id="3", compact=True)
    await tracer.start()
    with pytest.raises(ApplicationError):
        async with tracer.step("decoder", "decode"):
            raise ApplicationError(
                code=ErrorCode.PAYLOAD_DECODE_FAILED,
                message="port 13 unknown",
                component="decoder",
                user_actionable=True,
                context={"port": 13},
            )
    trace = await tracer.finish()
    assert trace.status == TraceStatus.FAILED
    assert trace.trace_class == TraceClass.FAILED
    error = await session.get(ApplicationErrorRow, trace.error_id)
    assert error is not None and error.error_code == ErrorCode.PAYLOAD_DECODE_FAILED
    # a failed compact trace still writes the failing step as a row
    steps = (
        (await session.execute(select(ProcessingStep).where(ProcessingStep.trace_id == trace.id)))
        .scalars()
        .all()
    )
    assert len(steps) == 1 and steps[0].error_id == error.id


async def test_unexpected_exception_is_internal_error_and_reraised(session):
    tracer = Tracer(session, root_object_type="command", root_object_id="4")
    await tracer.start()
    with pytest.raises(KeyError):
        async with tracer.step("api", "encode"):
            raise KeyError("boom")
    trace = await tracer.finish()
    assert trace.status == TraceStatus.FAILED
    error = await session.get(ApplicationErrorRow, trace.error_id)
    assert error is not None and error.error_code == ErrorCode.INTERNAL_ERROR
