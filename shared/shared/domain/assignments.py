"""Resolve which project and entity a device record belongs to (architecture 28.5 and 28.9).

The only place that answers this question. Attribution uses the canonical device-origin time of
the record, never ingest, network or upload time. A raw log uploaded on 20 August with a fix from
15 July belongs to the project that owned the device on 15 July.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import DeviceEntityAssignment, DeviceProjectAssignment
from shared.timeutil import require_aware


@dataclass(frozen=True, slots=True)
class Attribution:
    project_id: uuid.UUID | None
    entity_id: uuid.UUID | None

    @property
    def assigned(self) -> bool:
        return self.project_id is not None


async def resolve_attribution(
    session: AsyncSession, device_id: uuid.UUID, at: datetime
) -> Attribution:
    """Project and entity that were assigned to the device at `at`. Either can be None."""
    require_aware(at)
    project_id = await session.scalar(
        select(DeviceProjectAssignment.project_id).where(
            DeviceProjectAssignment.device_id == device_id,
            DeviceProjectAssignment.validity.op("@>")(at),
        )
    )
    entity_id = await session.scalar(
        select(DeviceEntityAssignment.entity_id).where(
            DeviceEntityAssignment.device_id == device_id,
            DeviceEntityAssignment.validity.op("@>")(at),
        )
    )
    return Attribution(project_id=project_id, entity_id=entity_id)


def _contains(validity: Any, at: datetime) -> bool:
    """Whether a `tstzrange` as asyncpg hands it back holds `at` (the assignments use `[)`)."""
    lower, upper = validity.lower, validity.upper
    below = lower is not None and (at < lower or (at == lower and not validity.lower_inc))
    above = upper is not None and (at > upper or (at == upper and not validity.upper_inc))
    return not below and not above


async def resolve_attributions(
    session: AsyncSession, device_id: uuid.UUID, times: set[datetime]
) -> dict[datetime, Attribution]:
    """`resolve_attribution` for many times in two queries: the device's project and entity
    assignments that overlap the span of the times are read once and each time is placed in
    memory. A frame of a log file or a card carries dozens of records at distinct times, and
    two queries per time were a tenth of the decoder's round trips (2026-10-16)."""
    if not times:
        return {}
    for at in times:
        require_aware(at)
    earliest, latest = min(times), max(times)
    span = func.tstzrange(earliest, latest, "[]")
    projects = (
        await session.execute(
            select(DeviceProjectAssignment.project_id, DeviceProjectAssignment.validity).where(
                DeviceProjectAssignment.device_id == device_id,
                DeviceProjectAssignment.validity.op("&&")(span),
            )
        )
    ).all()
    entities = (
        await session.execute(
            select(DeviceEntityAssignment.entity_id, DeviceEntityAssignment.validity).where(
                DeviceEntityAssignment.device_id == device_id,
                DeviceEntityAssignment.validity.op("&&")(span),
            )
        )
    ).all()
    result: dict[datetime, Attribution] = {}
    for at in times:
        project_id = next((p for p, v in projects if _contains(v, at)), None)
        entity_id = next((e for e, v in entities if _contains(v, at)), None)
        result[at] = Attribution(project_id=project_id, entity_id=entity_id)
    return result


async def rewrite_attribution(
    session: AsyncSession, device_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[dict[str, int], set[uuid.UUID | None]]:
    """Rewrite the project and entity of the device's records whose effective time lies in
    `[start, end)` from the assignments as they stand now (decision D103): after an assignment
    start moved back, records that had no project or the wrong one get the right attribution.
    Records in a gap get none. Every table stamped with a project or an entity is covered
    (decision D292): positions, measurements, contacts, state history, events with their
    alerts, commands and log files, each by device and time so a hypertable decompresses the
    device's segment of the window alone. Returns the rows touched per table and the entities
    involved (None stands for the gaps), for the current-state recompute the caller runs; the
    attribution job (decision D206) runs this per window and recomputes once at the end."""
    from sqlalchemy import and_, func, text, update

    from shared.curation.effective import effective_time
    from shared.models import (
        Alert,
        Command,
        DeviceContact,
        DeviceLogFile,
        DeviceStateHistory,
        Event,
        Measurement,
        Position,
    )

    require_aware(start)
    require_aware(end)
    tables: list[tuple[Any, str, Any, bool]] = [
        (Position, "positions", effective_time(Position), True),
        (Measurement, "measurements", effective_time(Measurement), True),
        (DeviceContact, "contacts", DeviceContact.time, True),
        (DeviceStateHistory, "states", DeviceStateHistory.time, False),
        (Event, "events", Event.time, True),
        (Command, "commands", Command.created_at, True),
        (
            DeviceLogFile,
            "log_files",
            func.coalesce(DeviceLogFile.period_start, DeviceLogFile.uploaded_at),
            False,
        ),
    ]
    if end <= start:
        return {name: 0 for _, name, _, _ in tables}, {None}
    # Records older than the compression horizon live in compressed chunks; the update must
    # be allowed to decompress them.
    await session.execute(
        text("SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
    )
    projects = (
        await session.scalars(
            select(DeviceProjectAssignment).where(DeviceProjectAssignment.device_id == device_id)
        )
    ).all()
    entities = (
        await session.scalars(
            select(DeviceEntityAssignment).where(DeviceEntityAssignment.device_id == device_id)
        )
    ).all()

    def overlap(validity: Any) -> tuple[datetime, datetime] | None:
        lower = max(validity.lower, start) if validity.lower else start
        upper = min(validity.upper, end) if validity.upper else end
        return (lower, upper) if lower < upper else None

    counts: dict[str, int] = {}
    entity_ids: set[uuid.UUID | None] = {None}
    for model, name, when, has_entity in tables:
        window = and_(model.device_id == device_id, when >= start, when < end)
        cleared_values: dict[str, Any] = {"project_id": None}
        if has_entity:
            cleared_values["entity_id"] = None
        cleared = await session.execute(
            update(model).where(window).values(**cleared_values),
            execution_options={"synchronize_session": False},
        )
        counts[name] = int(getattr(cleared, "rowcount", 0) or 0)
        for project_assignment in projects:
            span = overlap(project_assignment.validity)
            if span:
                await session.execute(
                    update(model)
                    .where(window, when >= span[0], when < span[1])
                    .values(project_id=project_assignment.project_id),
                    execution_options={"synchronize_session": False},
                )
        if not has_entity:
            continue
        for entity_assignment in entities:
            span = overlap(entity_assignment.validity)
            if span:
                entity_ids.add(entity_assignment.entity_id)
                await session.execute(
                    update(model)
                    .where(window, when >= span[0], when < span[1])
                    .values(entity_id=entity_assignment.entity_id),
                    execution_options={"synchronize_session": False},
                )
    # an alert belongs where its event does
    alerts = await session.execute(
        update(Alert)
        .where(Alert.event_id == Event.id, Event.device_id == device_id)
        .where(Event.time >= start, Event.time < end)
        .values(project_id=Event.project_id),
        execution_options={"synchronize_session": False},
    )
    counts["alerts"] = int(getattr(alerts, "rowcount", 0) or 0)
    return counts, entity_ids


async def reattribute(
    session: AsyncSession, device_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, int]:
    """`rewrite_attribution` and the current-state recompute in one call, for a window small
    enough for one transaction: the curation overlay's time change of a record. Assignment
    changes queue an attribution job instead (`shared/domain/attribution.py`)."""
    from shared.curation.apply import recompute_current_state

    counts, entity_ids = await rewrite_attribution(session, device_id, start, end)
    await recompute_current_state(session, device_id, entity_ids)
    return counts
