"""An event with an alert in a project, notification targets, and the session."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from shared.bus import RedisStreamsBus
from shared.models import Alert, Automation, Event, NotificationTarget, Project
from tests.conftest import unique_name


@dataclass
class World:
    project: Project
    event: Event
    alert: Alert
    email: NotificationTarget
    telegram: NotificationTarget


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
    project = Project(name=unique_name("Park"), slug=unique_name("park"))
    db.add(project)
    await db.flush()
    event = Event(
        time=datetime.now(UTC),
        project_id=project.id,
        event_type="BATTERY_LOW",
        severity="warning",
        title="Rhino 14 battery at 3.1 V",
        context={"rule_id": str(uuid.uuid4()), "value": 3.1},
    )
    db.add(event)
    await db.flush()
    alert = Alert(event_id=event.id, project_id=project.id, severity="warning")
    email = NotificationTarget(
        project_id=project.id, name="Ops mail", channel="email", address="ops@example.org"
    )
    telegram = NotificationTarget(
        project_id=project.id, name="Rangers", channel="telegram", telegram_chat_id="12345"
    )
    db.add_all([alert, email, telegram])
    await db.commit()
    return World(project=project, event=event, alert=alert, email=email, telegram=telegram)


async def create_automation(
    db: AsyncSession, project: Project, actions: list[dict], **extra
) -> Automation:
    automation = Automation(
        project_id=project.id, name=unique_name("auto"), actions=actions, **extra
    )
    db.add(automation)
    await db.commit()
    return automation
