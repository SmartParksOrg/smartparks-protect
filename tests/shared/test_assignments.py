"""Assignment resolution and overlap rejection (architecture 28.9 and 28.10)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from shared.domain.assignments import resolve_attribution
from shared.models import (
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityType,
    Project,
)
from shared.timeutil import NaiveDatetimeError
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _fixture(session):
    device_type = DeviceType(
        key=unique_name("opencollar"), label="OpenCollar", driver_key="opencollar"
    )
    entity_type = EntityType(
        key=unique_name("animal"), label="Animal", group_key="tracked", icon_key="wildlife.generic"
    )
    project_a = Project(name=unique_name("A"), slug=unique_name("a"))
    project_b = Project(name=unique_name("B"), slug=unique_name("b"))
    session.add_all([device_type, entity_type, project_a, project_b])
    await session.flush()
    device = Device(name=unique_name("SP05"), device_type_id=device_type.id)
    rhino = Entity(project_id=project_a.id, entity_type_id=entity_type.id, name="Rhino 14")
    session.add_all([device, rhino])
    await session.flush()
    return device, rhino, project_a, project_b


async def test_raw_log_fix_belongs_to_the_old_project(session):
    """Device in project A until 1 August, in B from 10 August. A fix from 15 July is A's."""
    device, rhino, project_a, project_b = await _fixture(session)
    session.add_all(
        [
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project_a.id,
                validity=Range(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)),
            ),
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project_b.id,
                validity=Range(datetime(2026, 8, 10, tzinfo=UTC), None),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=rhino.id,
                validity=Range(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)),
            ),
        ]
    )
    await session.flush()

    july = await resolve_attribution(session, device.id, datetime(2026, 7, 15, tzinfo=UTC))
    assert july.project_id == project_a.id
    assert july.entity_id == rhino.id

    august = await resolve_attribution(session, device.id, datetime(2026, 8, 20, tzinfo=UTC))
    assert august.project_id == project_b.id
    assert august.entity_id is None

    gap = await resolve_attribution(session, device.id, datetime(2026, 8, 5, tzinfo=UTC))
    assert not gap.assigned


async def test_overlapping_project_assignments_are_rejected(session):
    device, _, project_a, project_b = await _fixture(session)
    session.add(
        DeviceProjectAssignment(
            device_id=device.id,
            project_id=project_a.id,
            validity=Range(datetime(2026, 1, 1, tzinfo=UTC), None),
        )
    )
    await session.flush()
    session.add(
        DeviceProjectAssignment(
            device_id=device.id,
            project_id=project_b.id,
            validity=Range(datetime(2026, 6, 1, tzinfo=UTC), None),
        )
    )
    with pytest.raises(IntegrityError, match="ex_device_project_assignments_no_overlap"):
        await session.flush()


async def test_naive_time_is_refused(session):
    device, *_ = await _fixture(session)
    with pytest.raises(NaiveDatetimeError):
        await resolve_attribution(session, device.id, datetime(2026, 7, 15))
