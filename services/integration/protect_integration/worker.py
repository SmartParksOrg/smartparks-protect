"""The live path (bus messages to delivery rows), the delivery loop (due rows to the target on
the retry schedule) and backfill requests. Every part isolates the target: the bus handler
only writes rows and acknowledges, the loop takes one integration at a time and stops on the
first transient failure of that integration in a cycle (architecture 18, decision D61)."""

import asyncio
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import Message, RedisStreamsBus, Topic
from shared.database import session_scope
from shared.enums import DeliveryOrigin, DeliveryStatus, IntegrationObjectType
from shared.integrations.deliveries import (
    ObjectRef,
    attempt,
    backfill,
    due_deliveries,
    enqueue,
    event_ref,
    measurement_ref,
)
from shared.logger import get_logger
from shared.models import Event, Integration, Measurement
from shared.timeutil import require_aware, utc_now

log = get_logger("integration")

RELOAD_SECONDS = 30
LOOP_SECONDS = 2.0
BATCH = 200


class IntegrationCache:
    """Enabled integrations by project, re-read every `RELOAD_SECONDS`."""

    def __init__(self) -> None:
        self.by_project: dict[uuid.UUID, list[Integration]] = {}
        self.loaded_at: datetime | None = None

    async def refresh(self, session: AsyncSession, *, force: bool = False) -> None:
        now = utc_now()
        if (
            not force
            and self.loaded_at is not None
            and (now - self.loaded_at).total_seconds() < RELOAD_SECONDS
        ):
            return
        rows = (
            await session.scalars(select(Integration).where(Integration.enabled.is_(True)))
        ).all()
        session.expunge_all()
        by_project: dict[uuid.UUID, list[Integration]] = {}
        for row in rows:
            by_project.setdefault(row.project_id, []).append(row)
        self.by_project = by_project
        self.loaded_at = now

    def for_project(self, project_id: uuid.UUID | None) -> list[Integration]:
        return list(self.by_project.get(project_id, [])) if project_id else []

    @property
    def any(self) -> bool:
        return bool(self.by_project)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def refs_from_message(session: AsyncSession, message: Message) -> list[ObjectRef]:
    payload = message.payload
    if message.topic == Topic.POSITION_CREATED:
        project_id = _uuid(payload.get("project_id"))
        if project_id is None:
            return []
        return [
            ObjectRef(
                object_type=IntegrationObjectType.POSITION,
                object_id=str(payload["position_id"]),
                time=require_aware(datetime.fromisoformat(str(payload["time"]))),
                project_id=project_id,
                entity_id=_uuid(payload.get("entity_id")),
                device_id=_uuid(payload.get("device_id")),
            )
        ]
    if message.topic == Topic.EVENT_CREATED:
        event_id = _uuid(payload.get("event_id"))
        event = await session.get(Event, event_id) if event_id else None
        return [event_ref(event)] if event is not None and event.project_id else []
    if message.topic == Topic.MEASUREMENT_CREATED:
        ids = [int(i) for i in payload.get("measurement_ids") or []]
        if not ids:
            return []
        rows = (await session.scalars(select(Measurement).where(Measurement.id.in_(ids)))).all()
        return [measurement_ref(row) for row in rows if row.project_id]
    return []


async def handle_message(session: AsyncSession, cache: IntegrationCache, message: Message) -> int:
    await cache.refresh(session)
    if not cache.any:
        return 0
    refs = await refs_from_message(session, message)
    if not refs:
        return 0
    integrations = cache.for_project(refs[0].project_id)
    if not integrations:
        return 0
    queued = await enqueue(session, integrations, refs, origin=DeliveryOrigin.LIVE)
    await session.commit()
    return queued


async def deliver_due(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """One cycle: every due row, grouped per integration, in order. A transient failure ends
    the integration's share of the cycle so an unreachable target gets one request, not two
    hundred."""
    now = now or utc_now()
    rows = await due_deliveries(session, now, limit=BATCH)
    if not rows:
        return {}
    integration_ids = {row.integration_id for row in rows}
    integrations = {
        row.id: row
        for row in (
            await session.scalars(select(Integration).where(Integration.id.in_(integration_ids)))
        ).all()
    }
    outcome: dict[str, int] = {}
    halted: set[uuid.UUID] = set()
    for delivery in rows:
        integration = integrations.get(delivery.integration_id)
        if integration is None:
            continue
        if delivery.integration_id in halted:
            continue
        if not integration.enabled:
            delivery.next_attempt_at = None
            delivery.status = DeliveryStatus.SKIPPED
            delivery.error_message = "integration disabled"
            await session.commit()
            outcome["skipped"] = outcome.get("skipped", 0) + 1
            continue
        status = await attempt(session, delivery, integration, now=now)
        await session.commit()
        outcome[status] = outcome.get(status, 0) + 1
        if status == DeliveryStatus.QUEUED:
            halted.add(delivery.integration_id)
    return outcome


async def delivery_loop(bus: RedisStreamsBus) -> None:
    while True:
        try:
            async with session_scope() as session:
                outcome = await deliver_due(session)
            if outcome:
                log.info("deliveries", outcome=outcome)
            await bus.heartbeat("integration")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("delivery loop failed", exc_info=True)
        await asyncio.sleep(LOOP_SECONDS)


async def handle_backfill(session: AsyncSession, payload: dict[str, Any]) -> int:
    integration = await session.get(Integration, _uuid(payload.get("integration_id")))
    if integration is None:
        log.warning("backfill for unknown integration", payload=payload)
        return 0
    time_from = require_aware(datetime.fromisoformat(str(payload["from"])))
    time_to = require_aware(datetime.fromisoformat(str(payload["to"])))
    queued = await backfill(session, integration, time_from, time_to)
    log.info(
        "backfill done",
        integration=integration.name,
        queued=queued,
        time_from=time_from.isoformat(),
        time_to=time_to.isoformat(),
    )
    return queued
