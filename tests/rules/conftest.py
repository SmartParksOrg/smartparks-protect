"""A committed project with an entity, a device on it, a geofence and a bus."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest_asyncio
from geoalchemy2 import WKTElement
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from shared.bus import RedisStreamsBus
from shared.enums import DeviceStatus
from shared.models import (
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    EntityCurrentState,
    EntityType,
    Feature,
    Project,
    Rule,
    RuleVersion,
)
from tests.conftest import unique_name

T_START = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class World:
    project: Project
    entity: Entity
    device: Device
    fence: Feature


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
async def world(db: AsyncSession) -> World:
    device_type = DeviceType(
        key=unique_name("gj").replace("-", "_"), label="Generic", driver_key="generic_json"
    )
    entity_type = EntityType(
        key=unique_name("et").replace("-", "_"),
        label="Animal",
        group_key="tracked",
        icon_key="wildlife.rhino",
    )
    project = Project(name=unique_name("Park"), slug=unique_name("park"))
    db.add_all([device_type, entity_type, project])
    await db.flush()
    device = Device(
        name=unique_name("dev"), device_type_id=device_type.id, status=DeviceStatus.ACTIVE
    )
    entity = Entity(project_id=project.id, entity_type_id=entity_type.id, name="Rhino 14")
    fence = Feature(
        project_id=project.id,
        feature_type="geofence",
        name="Core area",
        geom=WKTElement("POLYGON((31 -25, 32 -25, 32 -24, 31 -24, 31 -25))", srid=4326),
    )
    db.add_all([device, entity, fence])
    await db.flush()
    db.add_all(
        [
            DeviceProjectAssignment(
                device_id=device.id,
                project_id=project.id,
                validity=Range(T_START, None, bounds="[)"),
            ),
            DeviceEntityAssignment(
                device_id=device.id, entity_id=entity.id, validity=Range(T_START, None, bounds="[)")
            ),
            EntityCurrentState(entity_id=entity.id, project_id=project.id, device_id=device.id),
        ]
    )
    await db.commit()
    return World(project=project, entity=entity, device=device, fence=fence)


async def create_rule(
    db: AsyncSession,
    project: Project,
    document: dict,
    *,
    name: str | None = None,
    enabled: bool = True,
) -> Rule:
    rule = Rule(
        project_id=project.id, name=name or unique_name("rule"), enabled=enabled, current_version=1
    )
    db.add(rule)
    await db.flush()
    db.add(RuleVersion(rule_id=rule.id, version=1, document=document))
    await db.commit()
    return rule


def measurement_doc(metric: str = "battery_voltage", op: str = "<", value: float = 3.2, **extra):
    return {
        "trigger": {"kind": "measurement", "metric_key": metric},
        "conditions": {"type": "threshold", "metric": metric, "op": op, "value": value},
        "event": {"event_type": "BATTERY_LOW", "title": "{entity} battery at {value} V"},
        **extra,
    }


def uuid_str() -> str:
    return str(uuid.uuid4())
