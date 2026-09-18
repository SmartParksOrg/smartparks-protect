"""A device's place set by a person, shown at once (decision D261).

Setting a place is the whole way a device that reports no position ever reaches the map, so the
place has to land on the current state rather than wait for a record that will never come. Two
current states carry it: the device's own, and the one of the entity the device is on, which is
what the map's Entities layer draws. Putting only the device on the map leaves the scanner's
entity blank, which is what happened before this module existed.

The same work is needed at three moments — a place is set, a place is cleared, a device that has
one is assigned to an entity — so it lives here instead of in whichever router noticed first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.connectivity.network_location import STATIC_RECORD_TYPE
from shared.domain.assignments import resolve_attribution
from shared.models import Device, DeviceCurrentState, EntityCurrentState


async def show_static_place(session: AsyncSession, device: Device, when: datetime) -> None:
    """Put the device's place on its own current state and on the entity it is on right now."""
    state = await session.get(DeviceCurrentState, device.id)
    if state is None:
        state = DeviceCurrentState(device_id=device.id, latest_state={})
        session.add(state)
    _place(state, device.static_geom, when)

    attribution = await resolve_attribution(session, device.id, when)
    if attribution.entity_id is None or attribution.project_id is None:
        return
    entity_state = await session.get(EntityCurrentState, attribution.entity_id)
    if entity_state is None:
        # a scanner's entity has never had a record of its own: the device reports nothing
        entity_state = EntityCurrentState(
            entity_id=attribution.entity_id, project_id=attribution.project_id
        )
        session.add(entity_state)
    entity_state.device_id = device.id
    _place(entity_state, device.static_geom, when)


async def place_entity_of(session: AsyncSession, device_id: uuid.UUID, when: datetime) -> bool:
    """Give the entity a device was just assigned to the device's place, if it has one.

    A scanner is often placed before anybody makes it an entity, and nothing else would ever put
    that entity on the map. Returns whether a place was carried over."""
    device = await session.get(Device, device_id)
    if device is None or device.static_geom is None:
        return False
    await show_static_place(session, device, device.static_position_at or when)
    return True


def _place(state: DeviceCurrentState | EntityCurrentState, geom: Any, when: datetime) -> None:
    state.latest_position = geom
    state.latest_position_time = when
    state.latest_position_kind = STATIC_RECORD_TYPE
    state.latest_accuracy_m = None
