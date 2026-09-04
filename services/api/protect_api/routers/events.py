"""Events and alerts (architecture 16): project lists newest first with a time cursor, the
alert lifecycle, event detail with deliveries, events on the map, and the server-level views
of system events for server admins."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import geom_to_geojson, get_or_404
from protect_api.deps import ProjectContext, require_permission, require_server_admin
from protect_api.pagination import Page, PageResponse, page
from protect_api.schemas.rules import (
    ActionDeliveryRead,
    AlertAction,
    AlertRead,
    EventDetail,
    EventRead,
)
from shared.database import get_session
from shared.enums import AlertStatus
from shared.models import ActionDelivery, Alert, Event, User
from shared.permissions import Permission
from shared.rules.events import close_alert
from shared.timeutil import utc_now

router = APIRouter(tags=["events"])
admin_router = APIRouter(
    prefix="/admin", tags=["events"], dependencies=[Depends(require_server_admin)]
)

ICON_BY_TYPE = {
    "GEOFENCE_ENTER": "event.geofence",
    "GEOFENCE_EXIT": "event.geofence",
    "NO_DATA": "event.device_offline",
    "SPECIES_DETECTION": "event.detection",
}


def _icon(event_type: str) -> str:
    if event_type.startswith("SYSTEM_"):
        return "event.device_offline"
    return ICON_BY_TYPE.get(event_type, "event.alert")


def event_read(event: Event, alert: Alert | None) -> EventRead:
    data = EventRead.model_validate(event)
    data.geometry = geom_to_geojson(event.geom)
    if alert is not None:
        data.alert_id = alert.id
        data.alert_status = alert.status
    return data


def alert_read(alert: Alert, event: Event) -> AlertRead:
    data = AlertRead.model_validate(alert)
    data.title = event.title
    data.event_type = event.event_type
    data.entity_id = event.entity_id
    data.device_id = event.device_id
    data.time = event.time
    return data


def _cursor_time(cursor: str | None) -> datetime | None:
    if cursor is None:
        return None
    try:
        return datetime.fromisoformat(cursor)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None


async def list_events_for(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    page: Page,
    *,
    event_type: str | None,
    severity: str | None,
    entity_id: uuid.UUID | None,
    time_from: datetime | None,
    time_to: datetime | None,
) -> PageResponse[EventRead]:
    statement = select(Event, Alert).outerjoin(Alert, Alert.event_id == Event.id)
    statement = (
        statement.where(Event.project_id == project_id)
        if project_id is not None
        else statement.where(Event.project_id.is_(None))
    )
    if event_type:
        statement = statement.where(Event.event_type == event_type)
    if severity:
        statement = statement.where(Event.severity == severity)
    if entity_id is not None:
        statement = statement.where(Event.entity_id == entity_id)
    if time_from is not None:
        statement = statement.where(Event.time >= time_from)
    if time_to is not None:
        statement = statement.where(Event.time < time_to)
    before = _cursor_time(page.cursor)
    if before is not None:
        statement = statement.where(Event.time < before)
    rows = (
        await session.execute(statement.order_by(Event.time.desc()).limit(page.limit + 1))
    ).all()
    items = [event_read(event, alert) for event, alert in rows[: page.limit]]
    next_cursor = items[-1].time.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)


async def list_alerts_for(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    page: Page,
    *,
    alert_status: str | None,
    severity: str | None,
    entity_id: uuid.UUID | None,
) -> PageResponse[AlertRead]:
    statement = select(Alert, Event).join(Event, Event.id == Alert.event_id)
    statement = (
        statement.where(Alert.project_id == project_id)
        if project_id is not None
        else statement.where(Alert.project_id.is_(None))
    )
    if alert_status:
        statement = statement.where(Alert.status == alert_status)
    if severity:
        statement = statement.where(Alert.severity == severity)
    if entity_id is not None:
        statement = statement.where(Event.entity_id == entity_id)
    before = _cursor_time(page.cursor)
    if before is not None:
        statement = statement.where(Alert.created_at < before)
    rows = (
        await session.execute(statement.order_by(Alert.created_at.desc()).limit(page.limit + 1))
    ).all()
    items = [alert_read(alert, event) for alert, event in rows[: page.limit]]
    next_cursor = items[-1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)


async def _scoped_alert(
    session: AsyncSession, alert_id: uuid.UUID, project_id: uuid.UUID | None
) -> tuple[Alert, Event]:
    alert = await get_or_404(session, Alert, alert_id, "Alert")
    if alert.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    event = await session.get(Event, alert.event_id)
    assert event is not None
    return alert, event


async def _transition(
    session: AsyncSession,
    alert_id: uuid.UUID,
    project_id: uuid.UUID | None,
    user: User,
    to: AlertStatus,
    body: AlertAction,
) -> AlertRead:
    alert, event = await _scoped_alert(session, alert_id, project_id)
    try:
        await close_alert(session, alert, to, user_id=user.id, note=body.note)
    except ValueError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    await record_audit(
        session,
        user=user,
        action=f"alert.{to.value}",
        object_type="alert",
        object_id=str(alert.id),
        project_id=project_id,
        details={"event_type": event.event_type, "note": body.note},
    )
    await session.commit()
    return alert_read(alert, event)


async def event_detail_for(
    session: AsyncSession, event_id: uuid.UUID, project_id: uuid.UUID | None
) -> EventDetail:
    event = await get_or_404(session, Event, event_id, "Event")
    if event.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    alert = await session.scalar(select(Alert).where(Alert.event_id == event.id))
    deliveries = await session.scalars(
        select(ActionDelivery)
        .where(ActionDelivery.event_id == event.id)
        .order_by(ActionDelivery.created_at)
        .limit(200)
    )
    return EventDetail(
        event=event_read(event, alert),
        alert=alert_read(alert, event) if alert else None,
        deliveries=[ActionDeliveryRead.model_validate(d) for d in deliveries],
    )


# Project scope


@router.get("/projects/{project_id}/events", response_model=PageResponse[EventRead])
async def list_events(
    page: Page = Depends(page),
    event_type: str | None = None,
    severity: str | None = None,
    entity_id: uuid.UUID | None = None,
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EventRead]:
    """Newest first. The cursor is the time of the last item of the previous page."""
    return await list_events_for(
        session,
        context.project.id,
        page,
        event_type=event_type,
        severity=severity,
        entity_id=entity_id,
        time_from=time_from,
        time_to=time_to,
    )


@router.get("/projects/{project_id}/events/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> EventDetail:
    return await event_detail_for(session, event_id, context.project.id)


@router.get("/projects/{project_id}/map/events")
async def map_events(
    hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(500, ge=1, le=2000),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recent events with a location as GeoJSON, for the event layer of the live map. Events use
    the event marker family so they never look like entities (architecture 24.5)."""
    since = utc_now() - timedelta(hours=hours)
    rows = (
        await session.execute(
            select(Event, Alert)
            .outerjoin(Alert, Alert.event_id == Event.id)
            .where(
                Event.project_id == context.project.id,
                Event.geom.is_not(None),
                Event.time >= since,
            )
            .order_by(Event.time.desc())
            .limit(limit)
        )
    ).all()
    features = []
    for event, alert in rows:
        features.append(
            {
                "type": "Feature",
                "id": str(event.id),
                "geometry": geom_to_geojson(event.geom),
                "properties": {
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "title": event.title,
                    "time": event.time.isoformat(),
                    "entity_id": str(event.entity_id) if event.entity_id else None,
                    "alert_id": str(alert.id) if alert else None,
                    "alert_status": alert.status if alert else None,
                    "icon_key": _icon(event.event_type),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features, "hours": hours}


@router.get("/projects/{project_id}/alerts", response_model=PageResponse[AlertRead])
async def list_alerts(
    page: Page = Depends(page),
    alert_status: str | None = Query(None, alias="status"),
    severity: str | None = None,
    entity_id: uuid.UUID | None = None,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AlertRead]:
    return await list_alerts_for(
        session,
        context.project.id,
        page,
        alert_status=alert_status,
        severity=severity,
        entity_id=entity_id,
    )


@router.post("/projects/{project_id}/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    body: AlertAction,
    context: ProjectContext = Depends(require_permission(Permission.ALERTS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    return await _transition(
        session, alert_id, context.project.id, context.user, AlertStatus.ACKNOWLEDGED, body
    )


@router.post("/projects/{project_id}/alerts/{alert_id}/resolve", response_model=AlertRead)
async def resolve_alert(
    alert_id: uuid.UUID,
    body: AlertAction,
    context: ProjectContext = Depends(require_permission(Permission.ALERTS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    return await _transition(
        session, alert_id, context.project.id, context.user, AlertStatus.RESOLVED, body
    )


# Server scope: system events and alerts (project null)


@admin_router.get("/events", response_model=PageResponse[EventRead])
async def list_system_events(
    page: Page = Depends(page),
    event_type: str | None = None,
    severity: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PageResponse[EventRead]:
    return await list_events_for(
        session,
        None,
        page,
        event_type=event_type,
        severity=severity,
        entity_id=None,
        time_from=None,
        time_to=None,
    )


@admin_router.get("/events/{event_id}", response_model=EventDetail)
async def get_system_event(
    event_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> EventDetail:
    return await event_detail_for(session, event_id, None)


@admin_router.get("/alerts", response_model=PageResponse[AlertRead])
async def list_system_alerts(
    page: Page = Depends(page),
    alert_status: str | None = Query(None, alias="status"),
    severity: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AlertRead]:
    return await list_alerts_for(
        session, None, page, alert_status=alert_status, severity=severity, entity_id=None
    )


@admin_router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_system_alert(
    alert_id: uuid.UUID,
    body: AlertAction,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    return await _transition(session, alert_id, None, user, AlertStatus.ACKNOWLEDGED, body)


@admin_router.post("/alerts/{alert_id}/resolve", response_model=AlertRead)
async def resolve_system_alert(
    alert_id: uuid.UUID,
    body: AlertAction,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> AlertRead:
    return await _transition(session, alert_id, None, user, AlertStatus.RESOLVED, body)
