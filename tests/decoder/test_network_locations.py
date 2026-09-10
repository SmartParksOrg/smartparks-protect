"""Network locations in the decoder (decisions D162 and D164): a position of its own record
type next to the device's fixes, and the current position following the location source of the
device and the entity."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.connectivity.network_location import NETWORK_RECORD_TYPE, NetworkLocation
from shared.connectivity.satellite import SatelliteSession
from shared.enums import AcquisitionChannel, IngestionMethod, LocationSource
from shared.ingest import store_inbound
from shared.models import DeviceCurrentState, Entity, EntityCurrentState, Position
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio

# Inside the world's entity assignment (January to the handover on 1 August).
FIX_AT = datetime(2026, 6, 10, 9, 57, 38, tzinfo=UTC)
SESSION_AT = datetime(2026, 6, 10, 10, 43, 56, tzinfo=UTC)


async def _process(db, world, message):
    stored = await store_inbound(db, world.source, message)
    await db.commit()
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    return outcome


def _uplink(world, fix: tuple[float, float] | None, estimate_at: datetime, sequence: int = 1):
    payload = (
        {"time": FIX_AT.isoformat(), "lat": fix[0], "lon": fix[1]}
        if fix
        else {"time": FIX_AT.isoformat(), "state": {"note": "no fix"}}
    )
    return inbound(
        world.external_id,
        payload,
        acquisition_channel=AcquisitionChannel.IRIDIUM,
        ingestion_method=IngestionMethod.WEBHOOK,
        satellite_delivered_at=estimate_at,
        satellite_session=SatelliteSession(
            status="ok",
            sequence=sequence,
            latitude=46.5829,
            longitude=15.594,
            cep_km=5.0,
            bytes=42,
            session_at=estimate_at,
        ),
    )


def _location_event(world, at: datetime, lat: float, lon: float):
    """A network's own location report, the way ThingPark or The Things Stack deliver one."""
    return inbound(
        world.external_id,
        {"report": "location"},
        event_type="location",
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        network_received_at=at,
        network_location=NetworkLocation(
            latitude=lat, longitude=lon, time=at, method="thingpark_geoloc", accuracy_m=350.0
        ),
    )


async def test_the_estimate_is_a_position_of_its_own_kind_and_the_fix_stays_current(db, world):
    outcome = await _process(db, world, _uplink(world, (46.558, 15.616), SESSION_AT))
    assert outcome.created["positions"] == 2
    rows = (
        await db.scalars(
            select(Position).where(Position.device_id == world.device.id).order_by(Position.time)
        )
    ).all()
    kinds = {p.record_type: p for p in rows}
    assert set(kinds) == {"gnss", NETWORK_RECORD_TYPE}
    network = kinds[NETWORK_RECORD_TYPE]
    assert network.accuracy_m == 5000.0 and network.time == SESSION_AT
    assert network.attributes["method"] == "iridium_estimate"
    assert [t for t, _ in outcome.messages].count("position.created") == 2
    payloads = [p for t, p in outcome.messages if t == "position.created"]
    assert {p["record_type"] for p in payloads} == {"gnss", NETWORK_RECORD_TYPE}
    # the device's own fix is the current position although the estimate is newer
    current = await db.get(DeviceCurrentState, world.device.id)
    assert current.latest_position_time == FIX_AT and current.latest_position_kind == "device"
    assert current.latest_fix_time == FIX_AT
    entity_state = await db.get(EntityCurrentState, world.entity.id)
    assert entity_state.latest_position_time == FIX_AT
    assert entity_state.latest_position_kind == "device"


async def test_network_locations_stand_in_only_as_the_setting_allows(db, world):
    # device only: a location report moves nothing
    await _process(db, world, _uplink(world, (46.558, 15.616), SESSION_AT))
    await _process(db, world, _location_event(world, SESSION_AT + timedelta(hours=2), 46.6, 15.7))
    current = await db.get(DeviceCurrentState, world.device.id)
    await db.refresh(current)
    assert current.latest_position_kind == "device" and current.latest_position_time == FIX_AT

    # device, else the network after 24 hours: not yet, the fix is two hours old
    entity = await db.get(Entity, world.entity.id)
    entity.location_source = LocationSource.DEVICE_ELSE_NETWORK
    entity.location_fallback_hours = 24
    world.device.location_source = LocationSource.DEVICE_ELSE_NETWORK
    world.device.location_fallback_hours = 24
    await db.commit()
    await _process(db, world, _location_event(world, SESSION_AT + timedelta(hours=3), 46.61, 15.71))
    await db.refresh(current)
    assert current.latest_position_kind == "device"
    # a day and a half later without a fix, the network location stands in
    late = FIX_AT + timedelta(hours=36)
    await _process(db, world, _location_event(world, late, 46.62, 15.72))
    await db.refresh(current)
    assert current.latest_position_kind == NETWORK_RECORD_TYPE
    assert current.latest_position_time == late and current.latest_fix_time == FIX_AT
    entity_state = await db.get(EntityCurrentState, world.entity.id)
    await db.refresh(entity_state)
    assert entity_state.latest_position_kind == NETWORK_RECORD_TYPE

    # a new device fix takes the position back, whatever the network said meanwhile
    fresh = inbound(
        world.external_id,
        {"time": (late + timedelta(minutes=5)).isoformat(), "lat": 46.56, "lon": 15.62},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        network_received_at=late + timedelta(minutes=6),
    )
    await _process(db, world, fresh)
    await db.refresh(current)
    assert current.latest_position_kind == "device"
    assert current.latest_position_time == late + timedelta(minutes=5)

    # network: the newest of both wins
    world.device.location_source = LocationSource.NETWORK
    await db.commit()
    newest = late + timedelta(hours=1)
    await _process(db, world, _location_event(world, newest, 46.63, 15.73))
    await db.refresh(current)
    assert current.latest_position_kind == NETWORK_RECORD_TYPE
    assert current.latest_position_time == newest
