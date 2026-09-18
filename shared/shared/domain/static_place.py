"""A device's place set by a person, and the sightings that place gives a position to.

Setting a place is the whole way a device that reports no position ever reaches the map, so the
place has to land on the current state rather than wait for a record that will never come. Two
current states carry it: the device's own, and the one of the entity the device is on, which is
what the map's Entities layer draws. Putting only the device on the map leaves the scanner's
entity blank, which is what happened before this module existed.

The second half is the sightings. A reader with a place gives every device it hears a position
at the reader (decision D258), and for an animal wearing only a Bluetooth tag that is the only
position there will ever be. That happens as the scan is decoded, which is fine as long as the
place and the addresses were known first — and in the field they never are. A reader is put up,
it scans for a week, and only then does somebody measure where it stands and record the tags'
addresses. So both of those repair the past: the sightings already stored get their positions
when the place arrives, and the sightings of a device get theirs when its address arrives and
they stop being unknown neighbours. `shared.domain.contacts.resolve_waiting` already repairs the
resolution; without this the position that should follow from it was never written.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.connectivity.network_location import PROXIMITY_RECORD_TYPE, STATIC_RECORD_TYPE
from shared.device_drivers.base import canonical_key
from shared.domain.assignments import resolve_attribution
from shared.enums import ContactResolution, LocationSource
from shared.models import (
    Device,
    DeviceContact,
    DeviceCurrentState,
    Entity,
    EntityCurrentState,
    Position,
)
from shared.timeutil import utc_now

#: The most sightings one repair walks. A reader that has been up for a year and hears a herd
#: every minute would otherwise hold a request open for minutes; the rest are a rerun away.
MAX_PAST_SIGHTINGS = 20_000


@dataclass(slots=True)
class Sighting:
    """One device heard another, and where the delivery that said so came from."""

    seen_id: uuid.UUID
    when: datetime
    data_source_id: uuid.UUID | None = None
    source_event_id: int | None = None
    source_event_ingested_at: datetime | None = None


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


async def place_sightings(
    session: AsyncSession, reader: Device, sightings: Iterable[Sighting]
) -> int:
    """A position at the reader for every device it heard (decision D258); how many were written.

    An estimate with a radius, not a fix, carrying a record type of its own so that every reader
    of positions which already separates a fix from an estimate treats it correctly without being
    taught anything new. Existing rows are left alone, so this is safe to run again.
    """
    if reader.static_geom is None:
        return 0
    rows = sorted(sightings, key=lambda s: s.when)
    if not rows:
        return 0
    settings = get_settings()
    keys = {(s.seen_id, s.when): canonical_key(s.seen_id, s.when, _key_for(reader)) for s in rows}
    known = set(
        await session.scalars(
            select(Position.canonical_key).where(Position.canonical_key.in_(set(keys.values())))
        )
    )
    written = 0
    newest: dict[uuid.UUID, datetime] = {}
    for sighting in rows:
        # every sighting counts towards where the device is now, even one whose position was
        # already written: a repair has to leave the state right, not only the rows
        newest[sighting.seen_id] = max(newest.get(sighting.seen_id, sighting.when), sighting.when)
        key = keys[(sighting.seen_id, sighting.when)]
        if key in known:
            continue
        known.add(key)
        attribution = await resolve_attribution(session, sighting.seen_id, sighting.when)
        session.add(
            Position(
                time=sighting.when,
                device_id=sighting.seen_id,
                project_id=attribution.project_id,
                entity_id=attribution.entity_id,
                record_type=PROXIMITY_RECORD_TYPE,
                canonical_key=key,
                geom=reader.static_geom,
                accuracy_m=settings.contact_position_accuracy_m,
                attributes={"heard_by": str(reader.id), "heard_by_name": reader.name},
                data_source_id=sighting.data_source_id,
                source_event_id=sighting.source_event_id,
                source_event_ingested_at=sighting.source_event_ingested_at,
            )
        )
        written += 1
    # only the newest sighting per device can change where that device is now, and the rule
    # below reads three rows per call, which over a repair of thousands is worth not repeating
    for seen_id, when in newest.items():
        attribution = await resolve_attribution(session, seen_id, when)
        await place_current_state(session, seen_id, attribution, reader, when)
    return written


async def place_current_state(
    session: AsyncSession, seen_id: uuid.UUID, attribution: Any, reader: Device, when: datetime
) -> None:
    """Put the heard device, and the animal it is on, at the reader.

    An estimate never displaces a newer device fix: a collar that fixes for itself keeps its own
    position and the sighting is only a contact. A device that has never fixed at all, which is
    every tag, takes the estimate whatever its location setting says, because that setting is
    there to choose between a fix and an estimate and there is no fix to choose."""
    seen = await session.get(Device, seen_id)
    if seen is None:
        return
    settings = get_settings()
    owners: list[tuple[Any, str, int]] = []
    device_state = await session.get(DeviceCurrentState, seen_id)
    if device_state is not None:
        owners.append((device_state, seen.location_source, seen.location_fallback_hours))
        if device_state.last_seen_at is None or when > device_state.last_seen_at:
            device_state.last_seen_at = when
    if attribution.entity_id is not None and attribution.project_id is not None:
        entity_state = await session.get(EntityCurrentState, attribution.entity_id)
        if entity_state is None:
            # an animal wearing only a tag has never had a record of its own, so its state row
            # does not exist yet; without creating it the first sighting places nothing
            entity_state = EntityCurrentState(
                entity_id=attribution.entity_id, project_id=attribution.project_id
            )
            session.add(entity_state)
        # being heard is the only sign a tag is alive, so it is the only thing that can ever
        # move the animal's "last seen"; without this the panel says never of an animal a
        # reader heard twenty minutes ago
        if entity_state.last_seen_at is None or when > entity_state.last_seen_at:
            entity_state.last_seen_at = when
        entity = await session.get(Entity, attribution.entity_id)
        owners.append(
            (
                entity_state,
                entity.location_source if entity else LocationSource.DEVICE,
                entity.location_fallback_hours if entity else 24,
            )
        )
    for state, source, fallback in owners:
        never_fixed = state.latest_fix_time is None
        newer = state.latest_position_time is None or when > state.latest_position_time
        stale = never_fixed or (when - state.latest_fix_time) > timedelta(hours=max(0, fallback))
        allowed = never_fixed or source in (
            LocationSource.NETWORK,
            LocationSource.DEVICE_ELSE_NETWORK,
        )
        if newer and allowed and (source == LocationSource.NETWORK or stale):
            state.latest_position_time = when
            state.latest_position = reader.static_geom
            state.latest_position_kind = PROXIMITY_RECORD_TYPE
            state.latest_accuracy_m = settings.contact_position_accuracy_m
            if isinstance(state, EntityCurrentState):
                state.device_id = seen_id


async def place_past_sightings(session: AsyncSession, reader: Device) -> int:
    """The sightings this reader already made, now that it has a place to give them.

    A reader is measured after it has been scanning for weeks, and without this every sighting
    from before that afternoon says when but never where."""
    if reader.static_geom is None:
        return 0
    rows = (
        await session.scalars(
            select(DeviceContact)
            .where(
                DeviceContact.device_id == reader.id,
                DeviceContact.resolution == ContactResolution.RESOLVED,
                DeviceContact.contact_device_id.is_not(None),
            )
            .order_by(DeviceContact.time.desc())
            .limit(MAX_PAST_SIGHTINGS)
        )
    ).all()
    # the query already excludes a null counterpart; the narrowing is for the type checker
    sightings = [_sighting_of(r, r.contact_device_id) for r in rows if r.contact_device_id]
    return await place_sightings(session, reader, sightings)


async def place_past_sightings_of(session: AsyncSession, seen: Device) -> int:
    """The sightings of this device that placed readers already made.

    Its address arrived after they heard it, so they were stored as unknown neighbours and no
    position followed. `resolve_waiting` has just given them the device; this gives them the
    place, which for a tag is the whole of what the platform can say about where it was."""
    rows = (
        await session.scalars(
            select(DeviceContact)
            .where(
                DeviceContact.contact_device_id == seen.id,
                DeviceContact.resolution == ContactResolution.RESOLVED,
            )
            .order_by(DeviceContact.time.desc())
            .limit(MAX_PAST_SIGHTINGS)
        )
    ).all()
    by_reader: dict[uuid.UUID, list[DeviceContact]] = {}
    for row in rows:
        by_reader.setdefault(row.device_id, []).append(row)
    written = 0
    for reader_id, contacts in by_reader.items():
        reader = await session.get(Device, reader_id)
        if reader is None or reader.static_geom is None:
            continue
        written += await place_sightings(
            session, reader, [_sighting_of(c, seen.id) for c in contacts]
        )
    return written


def _sighting_of(row: DeviceContact, seen_id: uuid.UUID) -> Sighting:
    return Sighting(
        seen_id=seen_id,
        when=row.time,
        data_source_id=row.data_source_id,
        source_event_id=row.source_event_id,
        source_event_ingested_at=row.source_event_ingested_at,
    )


def _key_for(reader: Device) -> str:
    return f"{PROXIMITY_RECORD_TYPE}:{reader.id}"


def _place(state: DeviceCurrentState | EntityCurrentState, geom: Any, when: datetime) -> None:
    state.latest_position = geom
    state.latest_position_time = when
    state.latest_position_kind = STATIC_RECORD_TYPE
    state.latest_accuracy_m = None
    state.updated_at = utc_now()
