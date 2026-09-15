"""Resolve which project and entity a device record belongs to (architecture 28.5 and 28.9).

The only place that answers this question. Attribution uses the canonical device-origin time of
the record, never ingest, network or upload time. A raw log uploaded on 20 August with a fix from
15 July belongs to the project that owned the device on 15 July.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
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


async def rewrite_attribution(
    session: AsyncSession, device_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[dict[str, int], set[uuid.UUID | None]]:
    """Rewrite the project and entity of the device's records whose effective time lies in
    `[start, end)` from the assignments as they stand now (decision D103): after an assignment
    start moved back, records that had no project or the wrong one get the right attribution.
    Records in a gap get none. Returns the rows touched per table and the entities involved
    (None stands for the gaps), for the current-state recompute the caller runs; the
    attribution job (decision D206) runs this per window and recomputes once at the end."""
    from sqlalchemy import and_, text, update

    from shared.curation.effective import effective_time
    from shared.models import Measurement, Position

    require_aware(start)
    require_aware(end)
    if end <= start:
        return {"positions": 0, "measurements": 0}, {None}
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
    for model, name in ((Position, "positions"), (Measurement, "measurements")):
        when = effective_time(model)
        window = and_(model.device_id == device_id, when >= start, when < end)
        cleared = await session.execute(
            update(model).where(window).values(project_id=None, entity_id=None),
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
