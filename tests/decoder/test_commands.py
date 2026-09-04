"""Provider signals and device responses move commands; unfinished commands expire."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.bus import Topic
from shared.control.commands import expire_commands, interpret_device_records
from shared.device_drivers.base import DecodedMeasurement, DecodedRecords
from shared.device_drivers.opencollar import OpenCollarDriver
from shared.enums import CommandStatus
from shared.ingest import store_inbound
from shared.models import Command, CommandExecution
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio


async def _command(db, world, status=CommandStatus.QUEUED, **extra) -> Command:
    command = Command(
        device_id=world.device.id,
        project_id=world.project_a.id,
        action_key="REQUEST_STATUS",
        driver_key="opencollar",
        status=status,
        data_source_id=world.source.id,
        external_id=world.external_id,
        provider_ref=extra.pop("provider_ref", "q-1"),
        submitted_at=datetime.now(UTC) - timedelta(minutes=5),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        **extra,
    )
    db.add(command)
    await db.commit()
    return command


async def test_txack_and_ack_move_the_command(db, world):
    command = await _command(db, world)
    stored = await store_inbound(
        db,
        world.source,
        inbound(
            world.external_id,
            {"queueItemId": "q-1", "fCntDown": 2, "gatewayId": "gw1"},
            event_type="downlink_transmitted",
        ),
    )
    await db.commit()
    outcome = await process_source_event(
        db, stored.source_event.id, stored.source_event.ingested_at
    )
    await db.commit()
    await db.refresh(command)
    assert command.status == CommandStatus.TRANSMITTED and command.transmitted_at is not None
    assert [t for t, _ in outcome.messages] == [Topic.COMMAND_UPDATED]
    stored = await store_inbound(
        db,
        world.source,
        inbound(
            world.external_id,
            {"queueItemId": "q-1", "acknowledged": True},
            event_type="downlink_ack",
        ),
    )
    await db.commit()
    await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    await db.commit()
    await db.refresh(command)
    assert command.status == CommandStatus.ACKNOWLEDGED
    executions = (
        await db.scalars(
            select(CommandExecution)
            .where(CommandExecution.command_id == command.id)
            .order_by(CommandExecution.id)
        )
    ).all()
    assert [e.status for e in executions] == ["transmitted", "acknowledged"]
    assert executions[0].source == "adapter:downlink_transmitted"


async def test_platform_error_fails_the_command(db, world):
    command = await _command(db, world, provider_ref="q-2")
    stored = await store_inbound(
        db,
        world.source,
        inbound(
            world.external_id,
            {
                "level": "ERROR",
                "code": "DOWNLINK_PAYLOAD_SIZE",
                "description": "too large",
                "context": {"queue_item_id": "q-2"},
            },
            event_type="log",
        ),
    )
    await db.commit()
    await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    await db.commit()
    await db.refresh(command)
    assert command.status == CommandStatus.FAILED and command.error_message == "too large"


async def test_device_status_confirms_a_status_request(db, world):
    command = await _command(db, world, status=CommandStatus.TRANSMITTED, provider_ref="q-3")
    stored = await store_inbound(db, world.source, inbound(world.external_id, {"x": 1}))
    await db.commit()
    event = stored.source_event
    records = DecodedRecords(
        measurements=[
            DecodedMeasurement(
                time=datetime.now(UTC),
                metric_key="battery_voltage",
                value=3.9,
                record_type="status",
            )
        ]
    )
    messages = await interpret_device_records(db, world.device, OpenCollarDriver(), event, records)
    await db.commit()
    await db.refresh(command)
    assert command.status == CommandStatus.CONFIRMED_BY_DEVICE and command.confirmed_at is not None
    assert command.result["source_event_id"] == event.id
    assert messages[0][1]["status"] == "confirmed_by_device"
    # a second status uplink changes nothing
    assert (
        await interpret_device_records(db, world.device, OpenCollarDriver(), event, records) == []
    )


async def test_expiry(db, world):
    stale = await _command(db, world, provider_ref="q-4")
    stale.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    fresh = await _command(db, world, provider_ref="q-5")
    await db.commit()
    messages = await expire_commands(db)
    await db.commit()
    await db.refresh(stale)
    await db.refresh(fresh)
    assert stale.status == CommandStatus.EXPIRED and stale.error_code == "COMMAND_EXPIRED"
    assert fresh.status == CommandStatus.QUEUED
    assert [m[1]["command_id"] for m in messages] == [str(stale.id)]
