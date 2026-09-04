"""Create events and alerts the same way everywhere: rules, system checks and later the API and
MCP. An event is a fact; an alert is an event that needs a person (architecture 16). Publishing
happens after the caller commits, through `event_messages`."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import Topic
from shared.enums import AlertStatus, Severity
from shared.models import Alert, EntityCurrentState, Event
from shared.timeutil import utc_now


@dataclass(slots=True)
class NewEvent:
    time: datetime
    event_type: str
    severity: Severity | str
    title: str
    project_id: uuid.UUID | None
    entity_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    description: str | None = None
    point: tuple[float, float] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    rule_version_id: uuid.UUID | None = None
    source_event_id: int | None = None
    source_event_ingested_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    create_alert: bool = False


async def create_event(session: AsyncSession, new: NewEvent) -> tuple[Event, Alert | None]:
    """Insert the event and, when asked, its alert; keeps the entity's open alert count."""
    event = Event(
        time=new.time,
        project_id=new.project_id,
        entity_id=new.entity_id,
        device_id=new.device_id,
        event_type=new.event_type,
        severity=str(new.severity),
        title=new.title[:300],
        description=new.description,
        geom=from_shape(Point(new.point[0], new.point[1]), srid=4326) if new.point else None,
        context=new.context,
        rule_version_id=new.rule_version_id,
        source_event_id=new.source_event_id,
        source_event_ingested_at=new.source_event_ingested_at,
        trace_id=new.trace_id,
    )
    session.add(event)
    await session.flush()
    alert: Alert | None = None
    if new.create_alert:
        alert = Alert(
            event_id=event.id,
            project_id=new.project_id,
            status=AlertStatus.OPEN,
            severity=str(new.severity),
        )
        session.add(alert)
        await session.flush()
        if new.entity_id is not None:
            await bump_alert_count(session, new.entity_id, 1)
    return event, alert


async def bump_alert_count(session: AsyncSession, entity_id: uuid.UUID, delta: int) -> None:
    state = await session.get(EntityCurrentState, entity_id)
    if state is None:
        return
    state.active_alert_count = max(0, state.active_alert_count + delta)
    state.updated_at = utc_now()


async def close_alert(
    session: AsyncSession,
    alert: Alert,
    status: AlertStatus,
    *,
    user_id: uuid.UUID | None,
    note: str | None = None,
) -> Alert:
    """Acknowledge or resolve. Resolving an open alert lowers the entity's open alert count."""
    now = utc_now()
    was_open = alert.status == AlertStatus.OPEN
    if status == AlertStatus.ACKNOWLEDGED:
        if alert.status == AlertStatus.RESOLVED:
            raise ValueError("a resolved alert cannot be acknowledged")
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = alert.acknowledged_at or now
        alert.acknowledged_by_user_id = alert.acknowledged_by_user_id or user_id
    elif status == AlertStatus.RESOLVED:
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = now
        alert.resolved_by_user_id = user_id
    else:
        raise ValueError(f"cannot move an alert to {status}")
    if note:
        alert.note = note
    if was_open:
        event = await session.get(Event, alert.event_id)
        if event is not None and event.entity_id is not None:
            await bump_alert_count(session, event.entity_id, -1)
    return alert


def event_messages(
    event: Event, alert: Alert | None, *, rule_id: uuid.UUID | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """Bus messages for a committed event: `event.created`, and `alert.created` when there is
    one. `age_seconds` lets automations skip stale history (architecture 25.8)."""
    point = to_shape(event.geom) if event.geom is not None else None
    payload: dict[str, Any] = {
        "event_id": str(event.id),
        "project_id": str(event.project_id) if event.project_id else None,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "device_id": str(event.device_id) if event.device_id else None,
        "event_type": event.event_type,
        "severity": event.severity,
        "title": event.title,
        "time": event.time.isoformat(),
        "rule_id": str(rule_id) if rule_id else None,
        "rule_version_id": str(event.rule_version_id) if event.rule_version_id else None,
        "alert_id": str(alert.id) if alert else None,
        "latitude": point.y if point is not None else None,
        "longitude": point.x if point is not None else None,
        "age_seconds": (utc_now() - event.time).total_seconds(),
    }
    messages: list[tuple[str, dict[str, Any]]] = [(Topic.EVENT_CREATED, payload)]
    if alert is not None:
        messages.append(
            (
                Topic.ALERT_CREATED,
                {
                    "alert_id": str(alert.id),
                    "event_id": str(event.id),
                    "project_id": payload["project_id"],
                    "entity_id": payload["entity_id"],
                    "severity": alert.severity,
                    "title": event.title,
                    "time": payload["time"],
                },
            )
        )
    return messages
