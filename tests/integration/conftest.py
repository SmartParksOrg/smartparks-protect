"""A project with an entity, a device, a position, an event and a measurement, plus a fake
outbound connector registered for the tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
import pytest_asyncio
from geoalchemy2 import WKTElement
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from shared.bus import RedisStreamsBus
from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    PermanentFailure,
    Skipped,
    TransientFailure,
)
from shared.integrations.registry import CONNECTORS
from shared.models import (
    DataSource,
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityCurrentState,
    EntityType,
    Event,
    Integration,
    Measurement,
    Position,
    Project,
)
from shared.secrets import encrypt_json
from tests.conftest import unique_name

T0 = datetime(2026, 5, 1, 12, tzinfo=UTC)


class FakeConnector:
    """Records what it is asked to deliver; `mode` decides the outcome."""

    key: ClassVar[str] = "fake"
    label: ClassVar[str] = "Fake target"
    description: ClassVar[str] = "test double"
    supports: ClassVar[frozenset[str]] = frozenset({"position", "event"})
    config_schema: ClassVar[dict[str, Any]] = {"type": "object"}
    config_example: ClassVar[dict[str, Any]] = {}
    credentials_schema: ClassVar[dict[str, str]] = {"token": "x"}
    setup_hint: ClassVar[str] = ""

    def __init__(self) -> None:
        self.mode = "ok"
        self.delivered: list[dict[str, Any]] = []
        self.tests: list[Any] = []

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        if self.mode == "skip":
            raise Skipped("nothing to send")
        return {"type": item.object_type, "id": item.object_id, "entity": item.entity_name}

    async def deliver(self, integration, item, payload) -> DeliveryResult:
        if self.mode == "transient":
            raise TransientFailure("target down")
        if self.mode == "permanent":
            raise PermanentFailure("target refused")
        if self.mode == "crash":
            raise RuntimeError("boom")
        self.delivered.append({**payload, "token": integration.credentials.get("token")})
        return DeliveryResult(external_id=f"ext-{len(self.delivered)}", response={"ok": True})

    async def test(self, integration, location) -> dict[str, Any]:
        self.tests.append(location)
        return {"ok": True}


@pytest.fixture
def fake_connector():
    connector = FakeConnector()
    CONNECTORS["fake"] = connector
    yield connector
    CONNECTORS.pop("fake", None)


@dataclass
class World:
    project: Project
    entity: Entity
    device: Device
    source: DataSource
    position: Position
    event: Event
    measurement: Measurement
    integration: Integration


@pytest_asyncio.fixture
async def db(migrated_database: str):
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


@pytest_asyncio.fixture
async def world(db: AsyncSession, fake_connector) -> World:
    project = Project(name=unique_name("Park"), slug=unique_name("park"))
    entity_type = EntityType(
        key=unique_name("rhino").replace("-", "_"),
        label="Rhino",
        group_key="tracked",
        icon_key="wildlife.rhino",
    )
    device_type = DeviceType(
        key=unique_name("gj").replace("-", "_"), label="Generic", driver_key="generic_json"
    )
    source = DataSource(name=unique_name("SRC"), adapter_key="generic_http")
    db.add_all([project, entity_type, device_type, source])
    await db.flush()
    entity = Entity(project_id=project.id, entity_type_id=entity_type.id, name="Rhino 14")
    device = Device(name=unique_name("dev"), device_type_id=device_type.id, status="active")
    db.add_all([entity, device])
    await db.flush()
    db.add_all(
        [
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project.id,
                validity=Range(T0 - timedelta(days=30), None, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=entity.id,
                validity=Range(T0 - timedelta(days=30), None, bounds="[)"),
            ),
        ]
    )
    position = Position(
        time=T0,
        device_id=device.id,
        project_id=project.id,
        entity_id=entity.id,
        data_source_id=source.id,
        canonical_key=f"{device.id}|{T0.isoformat()}|gnss",
        geom=WKTElement("POINT(31.5 -24.9)", srid=4326),
        speed_mps=1.5,
    )
    event = Event(
        time=T0 + timedelta(minutes=5),
        project_id=project.id,
        entity_id=entity.id,
        device_id=device.id,
        event_type="GEOFENCE_EXIT",
        severity="warning",
        title="Rhino 14 left Core zone",
        context={"rule_id": str(uuid.uuid4())},
    )
    measurement = Measurement(
        time=T0,
        device_id=device.id,
        project_id=project.id,
        entity_id=entity.id,
        data_source_id=source.id,
        metric_key="battery_voltage",
        canonical_key=f"{device.id}|battery|{T0.isoformat()}",
        value_num=3.7,
    )
    db.add_all(
        [
            position,
            event,
            measurement,
            EntityCurrentState(
                entity_id=entity.id,
                project_id=project.id,
                device_id=device.id,
                latest_position_time=T0,
                latest_position=WKTElement("POINT(31.5 -24.9)", srid=4326),
            ),
        ]
    )
    integration = Integration(
        project_id=project.id,
        name=unique_name("fake"),
        connector_key="fake",
        credentials_encrypted=encrypt_json({"token": "secret"}),
        object_types=["position", "event"],
        max_object_age_seconds=10 * 365 * 86_400,
    )
    db.add(integration)
    await db.commit()
    return World(
        project=project,
        entity=entity,
        device=device,
        source=source,
        position=position,
        event=event,
        measurement=measurement,
        integration=integration,
    )
