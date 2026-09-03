"""The export worker runs queued jobs from `export.requested`."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from protect_export.main import build_worker
from shared.bus import Message, Topic
from shared.database import get_session_factory
from shared.enums import ExportStatus
from shared.models import ExportJob, Project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db(migrated_database: str):
    """The production session factory, so the worker runs exactly as in its container."""
    async with get_session_factory()() as session:
        yield session


async def test_worker_runs_a_queued_job(db, monkeypatch):
    project = Project(name=unique_name("P"), slug=unique_name("p"))
    db.add(project)
    await db.flush()
    job = ExportJob(
        project_id=project.id,
        dataset="positions",
        format="csv",
        parameters={
            "dataset": "positions",
            "format": "csv",
            "time_from": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            "time_to": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
        },
    )
    db.add(job)
    await db.commit()
    job_id = job.id

    worker = build_worker()
    assert [topic for topic, _ in worker._subscriptions] == [Topic.EXPORT_REQUESTED]
    handler = worker._subscriptions[0][1]
    await handler(
        Message(
            id="0-0",
            topic=Topic.EXPORT_REQUESTED,
            payload={"job_id": str(job_id)},
            trace_id=None,
        )
    )
    await db.refresh(job)
    done = job
    assert done.status == ExportStatus.DONE and done.row_count == 0
    assert done.object_key == f"projects/{project.id}/{job_id}.csv" and done.size_bytes > 0

    # a job that vanished is logged, not an error
    await handler(
        Message(
            id="0-1",
            topic=Topic.EXPORT_REQUESTED,
            payload={"job_id": str(uuid.uuid4())},
            trace_id=None,
        )
    )
