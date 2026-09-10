"""The satellite session in the decoder (decisions D158 to D160): the estimate against the
decoded fix on the trace, the last session on the connectivity state, and an MTMSN moving the
oldest pending command of the route to transmitted."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.bus import Topic
from shared.connectivity.satellite import SatelliteSession
from shared.enums import AcquisitionChannel, CommandStatus, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import Command, CommandExecution, ConnectivityState, ProcessingTrace
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio

SESSION_AT = datetime(2026, 9, 10, 10, 43, 56, tzinfo=UTC)


def satellite_uplink(world, lat: float, lon: float, **session):
    return inbound(
        world.external_id,
        {"time": "2026-09-10T09:57:38+00:00", "lat": lat, "lon": lon},
        acquisition_channel=AcquisitionChannel.IRIDIUM,
        ingestion_method=IngestionMethod.WEBHOOK,
        satellite_delivered_at=SESSION_AT,
        satellite_session=SatelliteSession(
            status=session.pop("status", "ok"),
            sequence=session.pop("sequence", 10),
            latitude=46.5448,
            longitude=15.0995,
            cep_km=4.0,
            bytes=42,
            session_at=SESSION_AT,
            **session,
        ),
    )


async def _process(db, bus, world, message):
    stored = await store_inbound(db, world.source, message)
    await commit_and_publish(db, bus, [stored])
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    return stored.source_event, outcome


async def test_a_fix_far_from_the_estimate_is_noted_and_the_session_kept(db, bus, world):
    event, outcome = await _process(db, bus, world, satellite_uplink(world, 47.5, 15.1))
    trace = await db.get(ProcessingTrace, outcome.trace_id)
    decoded = next(s for s in trace.compact_steps if s["operation"] == "payload decoded")
    assert "km from the Iridium estimate (CEP 4 km)" in decoded["note"]
    connectivity = await db.get(ConnectivityState, (world.device.id, world.source.id))
    assert connectivity.attributes["satellite"]["sequence"] == 10
    assert connectivity.attributes["satellite"]["status"] == "ok"
    assert event.provider_metadata["satellite_session"]["status_text"] == "session completed"

    # a fix inside the circle says nothing
    _, outcome = await _process(db, bus, world, satellite_uplink(world, 46.55, 15.11, sequence=11))
    trace = await db.get(ProcessingTrace, outcome.trace_id)
    decoded = next(s for s in trace.compact_steps if s["operation"] == "payload decoded")
    assert "Iridium estimate" not in (decoded.get("note") or "")


async def test_an_mtmsn_moves_the_oldest_pending_command_of_the_route(db, bus, world):
    older = Command(
        device_id=world.device.id,
        project_id=world.project_a.id,
        action_key="REQUEST_STATUS",
        driver_key="generic_json",
        status=CommandStatus.QUEUED,
        data_source_id=world.source.id,
        external_id=world.external_id,
        provider_ref="mt-1",
        submitted_at=SESSION_AT - timedelta(hours=2),
        expires_at=SESSION_AT + timedelta(days=1),
    )
    newer = Command(
        device_id=world.device.id,
        project_id=world.project_a.id,
        action_key="REQUEST_STATUS",
        driver_key="generic_json",
        status=CommandStatus.QUEUED,
        data_source_id=world.source.id,
        external_id=world.external_id,
        provider_ref="mt-2",
        submitted_at=SESSION_AT - timedelta(hours=1),
        expires_at=SESSION_AT + timedelta(days=1),
    )
    db.add_all([older, newer])
    await db.commit()

    # a session without a mobile-terminated transfer moves nothing
    _, outcome = await _process(
        db, bus, world, satellite_uplink(world, 46.55, 15.11, mt_sequence=0)
    )
    await db.refresh(older)
    assert older.status == CommandStatus.QUEUED
    assert Topic.COMMAND_UPDATED not in [t for t, _ in outcome.messages]

    # one carried a message: the oldest pending command on the route was transmitted
    _, outcome = await _process(
        db, bus, world, satellite_uplink(world, 46.55, 15.11, sequence=12, mt_sequence=7)
    )
    await db.refresh(older)
    await db.refresh(newer)
    assert older.status == CommandStatus.TRANSMITTED and older.transmitted_at == SESSION_AT
    assert newer.status == CommandStatus.QUEUED
    assert Topic.COMMAND_UPDATED in [t for t, _ in outcome.messages]
    execution = await db.scalar(
        select(CommandExecution)
        .where(CommandExecution.command_id == older.id, CommandExecution.status == "transmitted")
        .order_by(CommandExecution.time.desc())
    )
    assert execution.source == "adapter:satellite_session"
    assert execution.detail["mt_sequence"] == 7
