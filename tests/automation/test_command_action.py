"""An automation sends a command through the same path as a person."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects.postgresql import Range

from protect_automation.actions import handle_event
from shared.connectivity.adapters.chirpstack import ChirpStackCommands
from shared.enums import DeliveryStatus, DeviceStatus
from shared.models import (
    Command,
    DataSource,
    Device,
    DeviceProjectAssignment,
    DeviceType,
    Event,
    ExternalIdentity,
)
from tests.automation.conftest import create_automation
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_command_action_creates_a_command(db, world, monkeypatch):
    device_type = DeviceType(
        key=unique_name("oc").replace("-", "_"), label="OpenCollar", driver_key="opencollar"
    )
    source = DataSource(
        name=unique_name("cs"),
        adapter_key="chirpstack",
        config={"mqtt_host": "x"},
        capabilities={"uplink": True, "downlink": True},
    )
    db.add_all([device_type, source])
    await db.flush()
    device = Device(
        name=unique_name("dev"), device_type_id=device_type.id, status=DeviceStatus.ACTIVE
    )
    db.add(device)
    await db.flush()
    db.add_all(
        [
            ExternalIdentity(
                data_source_id=source.id,
                device_id=device.id,
                external_id=uuid.uuid4().hex[:16].upper(),
            ),
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=world.project.id,
                validity=Range(datetime(2026, 1, 1, tzinfo=UTC), None, bounds="[)"),
            ),
        ]
    )
    event = Event(
        time=datetime.now(UTC),
        project_id=world.project.id,
        device_id=device.id,
        event_type="NO_DATA",
        severity="warning",
        title="silent",
        context={},
    )
    db.add(event)
    await db.commit()

    async def submit(self, external_id, payload, options):
        return {"provider_ref": "q-auto", "statuses": ["accepted_by_network", "queued"]}

    monkeypatch.setattr(ChirpStackCommands, "submit", submit)
    automation = await create_automation(
        db,
        world.project,
        [{"type": "command", "action_key": "REQUEST_STATUS", "parameters": {}}],
        event_types=["NO_DATA"],
    )
    messages: list = []
    retry = await handle_event(
        db,
        {"event_id": str(event.id), "project_id": str(world.project.id), "alert_id": None},
        messages,
    )
    assert retry is False
    command = await db.scalar(
        __import__("sqlalchemy").select(Command).where(Command.automation_id == automation.id)
    )
    assert (
        command is not None and command.status == "queued" and command.actor["kind"] == "automation"
    )
    assert command.event_id == event.id and command.provider_ref == "q-auto"
    assert messages[0][0] == "command.updated" and messages[0][1]["command_id"] == str(command.id)
    delivery = (
        await db.scalars(
            __import__("sqlalchemy")
            .select(__import__("shared.models", fromlist=["ActionDelivery"]).ActionDelivery)
            .where(
                __import__("shared.models", fromlist=["ActionDelivery"]).ActionDelivery.event_id
                == event.id
            )
        )
    ).one()
    assert delivery.status == DeliveryStatus.SENT and delivery.response["command_id"] == str(
        command.id
    )


async def test_command_action_without_device_fails_permanently(db, world):
    await create_automation(
        db, world.project, [{"type": "command", "action_key": "REQUEST_STATUS"}]
    )
    assert (
        await handle_event(
            db,
            {
                "event_id": str(world.event.id),
                "project_id": str(world.project.id),
                "alert_id": None,
            },
            [],
        )
        is False
    )
    from sqlalchemy import select

    from shared.models import ActionDelivery

    delivery = (
        await db.scalars(select(ActionDelivery).where(ActionDelivery.event_id == world.event.id))
    ).one()
    assert delivery.status == DeliveryStatus.FAILED and "no device" in delivery.error_message
