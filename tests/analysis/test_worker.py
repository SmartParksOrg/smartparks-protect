"""The analysis worker runs queued runs from `analysis.requested` and stores every outcome on
the row (docs/ANALYTICS_PHASE1_PLAN.md, section 17): a stub module completes, one that raises
fails the run and the handler returns, a slow one times out, a cancelled one stops, a disabled
module is refused, and a redelivery for a finished run does nothing."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from pydantic import BaseModel

from protect_analysis.main import build_worker
from shared.analysis import MODULES
from shared.analysis.base import (
    Geometry,
    Period,
    Provenance,
    ResultDocument,
    RunContext,
    RunResult,
    Subject,
)
from shared.bus import Message, Topic
from shared.config import get_settings
from shared.database import get_session_factory
from shared.enums import AnalysisStatus
from shared.models import AnalysisGeometry, AnalysisRun, Project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


class StubParameters(BaseModel):
    behaviour: str = "complete"


class StubModule:
    key = "movement"
    label = "Stub"
    version = "stub/1"
    parameters = StubParameters

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, StubParameters)
        await ctx.progress(10, "start")
        if params.behaviour == "raise":
            raise RuntimeError("the module broke")
        if params.behaviour == "slow":
            await asyncio.sleep(5)
        if params.behaviour == "cancel":
            # the API set the flag meanwhile; the next progress call raises
            await ctx.progress(50, "half way")
        now = datetime(2026, 9, 14, tzinfo=UTC)
        subject = Subject(id=uuid.uuid4(), name="Wolf 1")
        document = ResultDocument(
            module="movement",
            method_version="stub/1",
            subjects=[subject],
            periods=[Period(time_from=now, time_to=now)],
            summary={"distance_km": 1.5},
            provenance=Provenance(
                module="movement",
                method_version="stub/1",
                subjects=[subject],
                periods=[Period(time_from=now, time_to=now)],
                parameters=params.model_dump(),
                input_count=42,
                excluded_count=1,
                computed_at=now,
            ),
            geometries={"mcp": 1},
        )
        square = {
            "type": "Polygon",
            "coordinates": [
                [[5.36, 52.09], [5.37, 52.09], [5.37, 52.10], [5.36, 52.10], [5.36, 52.09]]
            ],
        }
        return RunResult(
            document=document,
            geometries=[
                Geometry(
                    kind="mcp", subject_id=subject.id, label="MCP 95", level=0.95, geojson=square
                )
            ],
        )


@pytest_asyncio.fixture
async def db(migrated_database: str):
    async with get_session_factory()() as session:
        yield session


@pytest.fixture
def stub(monkeypatch):
    module = StubModule()
    monkeypatch.setitem(MODULES, "movement", module)
    return module


async def _queued(db, behaviour: str = "complete") -> AnalysisRun:
    project = Project(name=unique_name("P"), slug=unique_name("p"))
    db.add(project)
    await db.flush()
    run = AnalysisRun(
        project_id=project.id,
        module="movement",
        parameters={"behaviour": behaviour},
        method_version="stub/1",
    )
    db.add(run)
    await db.commit()
    return run


async def _deliver(run_id: uuid.UUID) -> None:
    worker = build_worker()
    assert [topic for topic, _ in worker._subscriptions] == [Topic.ANALYSIS_REQUESTED]
    handler = worker._subscriptions[0][1]
    await handler(
        Message(
            id="0-0", topic=Topic.ANALYSIS_REQUESTED, payload={"run_id": str(run_id)}, trace_id=None
        )
    )


async def test_a_run_completes_with_its_document_and_geometry(db, stub):
    run = await _queued(db)
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.COMPLETED and run.progress == 100
    assert run.result is not None and run.result["summary"] == {"distance_km": 1.5}
    assert run.input_count == 42 and run.excluded_count == 1
    assert run.expires_at is not None and run.finished_at is not None
    rows = list(
        await db.scalars(
            AnalysisGeometry.__table__.select().where(AnalysisGeometry.run_id == run.id)
        )
    )
    assert len(rows) == 1
    area = await db.scalar(
        AnalysisGeometry.__table__.select()
        .with_only_columns(AnalysisGeometry.area_m2)
        .where(AnalysisGeometry.run_id == run.id)
    )
    assert area is not None and 700_000 < area < 800_000

    # a redelivery for a finished run changes nothing
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.COMPLETED


async def test_a_module_that_raises_fails_the_run_and_the_handler_returns(db, stub):
    run = await _queued(db, "raise")
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.FAILED
    assert run.error_code == "ANALYSIS_FAILED" and "broke" in (run.error_message or "")


async def test_a_slow_run_times_out(db, stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "analysis_timeout_seconds", 1)
    run = await _queued(db, "slow")
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.FAILED and run.error_code == "ANALYSIS_TIMEOUT"


async def test_a_cancel_request_stops_the_run(db, stub):
    run = await _queued(db, "cancel")
    run.cancel_requested = True
    await db.commit()
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.CANCELLED and run.error_code == "CANCELLED"


async def test_a_disabled_module_is_refused(db, stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "analysis_modules", "grazing")
    run = await _queued(db)
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.FAILED and run.error_code == "MODULE_DISABLED"


async def test_a_kept_run_never_expires(db, stub):
    run = await _queued(db)
    run.name = "Wolves, September"
    await db.commit()
    await _deliver(run.id)
    await db.refresh(run)
    assert run.status == AnalysisStatus.COMPLETED and run.expires_at is None
