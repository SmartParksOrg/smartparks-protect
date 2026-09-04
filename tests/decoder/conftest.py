"""Pipeline fixtures: a committed device with a generic JSON driver, a data source, a project."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from shared.connectivity.base import InboundMessage
from shared.enums import AcquisitionChannel, DeviceStatus, IngestionMethod
from shared.models import (
    DataSource,
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityType,
    ExternalIdentity,
    Project,
)
from tests.conftest import unique_name

T_PROJECT_A = datetime(2026, 1, 1, tzinfo=UTC)
T_HANDOVER = datetime(2026, 8, 1, tzinfo=UTC)


@dataclass
class World:
    source: DataSource
    device: Device
    identity: ExternalIdentity
    project_a: Project
    project_b: Project
    entity: Entity
    external_id: str


@pytest_asyncio.fixture
async def db(migrated_database: str):
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def world(db: AsyncSession) -> World:
    """Device in project A from January, handed to project B on 1 August, on entity in A."""
    device_type = DeviceType(
        key=unique_name("gj").replace("-", "_"), label="Generic", driver_key="generic_json"
    )
    entity_type = EntityType(
        key=unique_name("et").replace("-", "_"),
        label="Animal",
        group_key="tracked",
        icon_key="wildlife.generic",
    )
    source = DataSource(name=unique_name("HTTP"), adapter_key="generic_http")
    project_a = Project(name=unique_name("A"), slug=unique_name("a"))
    project_b = Project(name=unique_name("B"), slug=unique_name("b"))
    db.add_all([device_type, entity_type, source, project_a, project_b])
    await db.flush()
    device = Device(
        name=unique_name("dev"), device_type_id=device_type.id, status=DeviceStatus.ACTIVE
    )
    entity = Entity(project_id=project_a.id, entity_type_id=entity_type.id, name="Rhino 14")
    db.add_all([device, entity])
    await db.flush()
    external_id = uuid.uuid4().hex[:16].upper()
    identity = ExternalIdentity(
        data_source_id=source.id, device_id=device.id, external_id=external_id
    )
    db.add_all(
        [
            identity,
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project_a.id,
                validity=Range(T_PROJECT_A, T_HANDOVER, bounds="[)"),
            ),
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project_b.id,
                validity=Range(T_HANDOVER, None, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=entity.id,
                validity=Range(T_PROJECT_A, T_HANDOVER, bounds="[)"),
            ),
        ]
    )
    await db.commit()
    return World(
        source=source,
        device=device,
        identity=identity,
        project_a=project_a,
        project_b=project_b,
        entity=entity,
        external_id=external_id,
    )


def inbound(external_id: str | None, payload: dict, **kwargs) -> InboundMessage:
    kwargs.setdefault("acquisition_channel", AcquisitionChannel.API)
    kwargs.setdefault("ingestion_method", IngestionMethod.WEBHOOK)
    kwargs.setdefault("event_type", "uplink")
    return InboundMessage(external_id=external_id, payload=payload, **kwargs)
