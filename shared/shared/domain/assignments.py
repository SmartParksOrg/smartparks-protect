"""Resolve which project and entity a device record belongs to (architecture 28.5 and 28.9).

The only place that answers this question. Attribution uses the canonical device-origin time of
the record, never ingest, network or upload time. A raw log uploaded on 20 August with a fix from
15 July belongs to the project that owned the device on 15 July.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

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
