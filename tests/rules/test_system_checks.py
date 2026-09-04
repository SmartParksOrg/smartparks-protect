"""System checks open one alert per finding and resolve it when the finding clears."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from protect_rules.system_checks import EVENT_WORKER_STALE, run_system_checks
from shared.bus import HEARTBEAT_PREFIX
from shared.enums import AlertStatus
from shared.models import Alert, Event

pytestmark = pytest.mark.asyncio


async def _stale_alerts(db):
    return (
        await db.execute(
            select(Alert, Event)
            .join(Event, Event.id == Alert.event_id)
            .where(
                Event.event_type == EVENT_WORKER_STALE,
                Event.context["subject"].astext == "export",
                Alert.status != AlertStatus.RESOLVED,
            )
        )
    ).all()


async def test_stale_worker_opens_then_resolves(db, bus):
    now = datetime.now(UTC)
    for worker in ("ingest", "decoder", "rules", "automation"):
        await bus.redis.set(HEARTBEAT_PREFIX + worker, now.isoformat())
    await bus.redis.set(HEARTBEAT_PREFIX + "export", (now - timedelta(hours=1)).isoformat())

    opened, resolved = await run_system_checks(bus)
    assert opened >= 1
    rows = await _stale_alerts(db)
    assert len(rows) == 1
    alert, event = rows[0]
    assert alert.status == AlertStatus.OPEN and event.project_id is None
    assert event.severity == "critical" and "export" in event.title

    # nothing new while it stays stale
    await run_system_checks(bus)
    assert len(await _stale_alerts(db)) == 1

    await bus.redis.set(HEARTBEAT_PREFIX + "export", datetime.now(UTC).isoformat())
    _, resolved = await run_system_checks(bus)
    assert resolved >= 1
    await db.rollback()  # end the test's transaction so the query sees the worker's commit
    assert await _stale_alerts(db) == []
    await db.refresh(alert)
    assert alert.status == AlertStatus.RESOLVED and "automatically" in (alert.note or "")
