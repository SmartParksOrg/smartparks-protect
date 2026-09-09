"""Records (phase 20, decision D142): what an entity or a device produced, one row per device
timestamp with the position and every measurement and state field of that moment, newest first,
in pages with a `time,device` cursor and a separate count for the progress bar. The simplest
question, "give me everything this collar produced between these dates", answered the way the
data arrives. Every request stays bounded (architecture 13.10); the client pages through."""

import base64
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import ScopeContext, require_scope_permission
from shared.database import get_session
from shared.models import Position
from shared.permissions import Permission
from shared.records import RecordSelection, count_keys, fill, keys_statement
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["records"])

MAX_PAGE = 1000
MAX_IDS = 500
DEFAULT_WINDOW = timedelta(days=30)


class RecordPosition(BaseModel):
    id: int
    lat: float
    lon: float
    altitude_m: float | None
    speed_mps: float | None
    heading_deg: float | None
    accuracy_m: float | None
    satellites: int | None
    valid: bool
    curated_fields: list[str] = Field(default_factory=list)
    source_event_id: int | None
    source_event_ingested_at: datetime | None
    trace_id: uuid.UUID | None


class RecordRow(BaseModel):
    """One moment of one device: the effective time, the position if the moment has one, the
    measurements by metric key (effective values) and the state fields reported then."""

    time: datetime
    device_id: uuid.UUID
    device_name: str | None
    entity_id: uuid.UUID | None
    entity_name: str | None
    project_id: uuid.UUID | None
    position: RecordPosition | None
    measurements: dict[str, float | bool | str | dict[str, Any] | None]
    state: dict[str, Any] | None
    source_event_id: int | None
    source_event_ingested_at: datetime | None
    trace_id: uuid.UUID | None


class RecordsPage(BaseModel):
    items: list[RecordRow]
    next_cursor: str | None
    time_from: datetime
    time_to: datetime


class RecordsCount(BaseModel):
    count: int
    time_from: datetime
    time_to: datetime


def _cursor(time: datetime, device_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([time.isoformat(), str(device_id)]).encode()
    ).decode()


def _parse_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw_time, raw_device = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return require_aware(datetime.fromisoformat(raw_time)), uuid.UUID(raw_device)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None


def _selection(
    entity_id: list[uuid.UUID] | None,
    device_id: list[uuid.UUID] | None,
    time_from: datetime | None,
    time_to: datetime | None,
) -> tuple[list[uuid.UUID], list[uuid.UUID], datetime, datetime]:
    entity_ids = list(entity_id or [])
    device_ids = list(device_id or [])
    if not entity_ids and not device_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give at least one entity_id or device_id"
        )
    if len(entity_ids) > MAX_IDS or len(device_ids) > MAX_IDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"At most {MAX_IDS} entities and {MAX_IDS} devices per request",
        )
    until = require_aware(time_to) if time_to else utc_now()
    since = require_aware(time_from) if time_from else until - DEFAULT_WINDOW
    if since >= until:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "from must be before to")
    return entity_ids, device_ids, since, until


@router.get("/records/count", response_model=RecordsCount)
async def records_count(
    entity_id: list[uuid.UUID] | None = Query(None),
    device_id: list[uuid.UUID] | None = Query(None),
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    include_invalid: bool = Query(False, description="Also rows marked invalid by curation"),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> RecordsCount:
    """How many records the selection has in the window: the progress bar's total."""
    entity_ids, device_ids, since, until = _selection(entity_id, device_id, time_from, time_to)
    count = await count_keys(
        session,
        RecordSelection(
            context.where(Position.project_id, unassigned=True),
            entity_ids,
            device_ids,
            since,
            until,
            include_invalid,
        ),
    )
    return RecordsCount(count=count, time_from=since, time_to=until)


@router.get("/records", response_model=RecordsPage)
async def records(
    entity_id: list[uuid.UUID] | None = Query(None),
    device_id: list[uuid.UUID] | None = Query(None),
    time_from: datetime | None = Query(None, alias="from"),
    time_to: datetime | None = Query(None, alias="to"),
    include_invalid: bool = Query(False, description="Also rows marked invalid by curation"),
    limit: int = Query(MAX_PAGE, ge=1, le=MAX_PAGE),
    cursor: str | None = Query(None, description="From the previous page"),
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> RecordsPage:
    """One page of records of the selected entities and devices in the window, newest first.
    The page's moments come from a union of position and measurement times, keyset-paged on
    `(time, device)`; the rows are then filled from the positions, measurements and state history
    of the page's time span, read through the owner and time indexes."""
    entity_ids, device_ids, since, until = _selection(entity_id, device_id, time_from, time_to)
    selection = RecordSelection(
        context.where(Position.project_id, unassigned=True),
        entity_ids,
        device_ids,
        since,
        until,
        include_invalid,
    )
    keys = keys_statement(selection).subquery("k")
    statement = select(keys.c.device_id, keys.c.moment)
    if cursor is not None:
        cursor_time, cursor_device = _parse_cursor(cursor)
        statement = statement.where(
            or_(
                keys.c.moment < cursor_time,
                and_(keys.c.moment == cursor_time, keys.c.device_id < cursor_device),
            )
        )
    page = (
        await session.execute(
            statement.order_by(keys.c.moment.desc(), keys.c.device_id.desc()).limit(limit + 1)
        )
    ).all()
    more = len(page) > limit
    page = page[:limit]
    if not page:
        return RecordsPage(items=[], next_cursor=None, time_from=since, time_to=until)
    records = await fill(session, selection, [(row.device_id, row.moment) for row in page])
    items = [
        RecordRow(
            time=r.time,
            device_id=r.device_id,
            device_name=r.device_name,
            entity_id=r.entity_id,
            entity_name=r.entity_name,
            project_id=r.project_id,
            position=RecordPosition(
                id=r.position.id,
                lat=r.lat or 0.0,
                lon=r.lon or 0.0,
                altitude_m=r.position.altitude_m,
                speed_mps=r.position.speed_mps,
                heading_deg=r.position.heading_deg,
                accuracy_m=r.position.accuracy_m,
                satellites=r.position.satellites,
                valid=r.position.valid,
                curated_fields=list(r.position.curated_fields or []),
                source_event_id=r.position.source_event_id,
                source_event_ingested_at=r.position.source_event_ingested_at,
                trace_id=r.position.trace_id,
            )
            if r.position is not None
            else None,
            measurements=r.measurements,
            state=r.state,
            source_event_id=r.source_event_id,
            source_event_ingested_at=r.source_event_ingested_at,
            trace_id=r.trace_id,
        )
        for r in records
    ]
    last = page[-1]
    return RecordsPage(
        items=items,
        next_cursor=_cursor(last.moment, last.device_id) if more else None,
        time_from=since,
        time_to=until,
    )
