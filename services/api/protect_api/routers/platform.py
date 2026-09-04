"""Phase 13: manual events, project icons and dashboards (decisions D84, D86)."""

import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import ProjectContext, get_project_context, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.routers.events import event_read
from protect_api.schemas.platform import (
    DashboardCreate,
    DashboardRead,
    DashboardUpdate,
    EventCreate,
    ProjectIconCreate,
    ProjectIconRead,
)
from protect_api.schemas.rules import EventRead
from shared.bus import RedisStreamsBus
from shared.database import get_session
from shared.enums import ActorType
from shared.models import Dashboard, Device, Entity, ProjectIcon, SavedView, User
from shared.permissions import Permission
from shared.rules.events import NewEvent, create_event, event_messages
from shared.timeutil import require_aware, utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["platform"])

SVG_NS = "{http://www.w3.org/2000/svg}"
FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "embed", "object", "image", "animate", "set"}
MAX_SVG_BYTES = 65536


# Manual events


async def create_manual_event(
    session: AsyncSession,
    bus: RedisStreamsBus,
    *,
    user: User,
    project_id: uuid.UUID,
    body: EventCreate,
    actor_type: ActorType = ActorType.USER,
    client_id: str | None = None,
) -> EventRead:
    """A report becomes an event through the same path rules use (architecture 16); the
    entity and device must belong to the project."""
    entity = await session.get(Entity, body.entity_id) if body.entity_id else None
    if body.entity_id and (entity is None or entity.project_id != project_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found in this project")
    if body.device_id and await session.get(Device, body.device_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give latitude and longitude together"
        )
    context = {**body.context, "reported_by": str(user.id), "actor": actor_type.value}
    if client_id:
        context["client_id"] = client_id
    event, alert = await create_event(
        session,
        NewEvent(
            time=require_aware(body.time) if body.time else utc_now(),
            event_type=body.event_type,
            severity=body.severity,
            title=body.title,
            project_id=project_id,
            entity_id=body.entity_id,
            device_id=body.device_id,
            description=body.description,
            point=(body.latitude, body.longitude)
            if body.latitude is not None and body.longitude is not None
            else None,
            context=context,
            create_alert=body.create_alert,
        ),
    )
    await record_audit(
        session,
        user=user,
        action="event.created",
        object_type="event",
        object_id=str(event.id),
        project_id=project_id,
        details={"event_type": event.event_type, "title": event.title, "alert": alert is not None},
        actor_type=actor_type,
    )
    await session.commit()
    for topic, payload in event_messages(event, alert):
        await bus.publish(topic, payload)
    return event_read(event, alert)


@router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def report_event(
    body: EventCreate,
    context: ProjectContext = Depends(require_permission(Permission.EVENTS_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> EventRead:
    """Report an event by hand: a sighting, an incident, a note with a place and a time."""
    return await create_manual_event(
        session, bus, user=context.user, project_id=context.project.id, body=body
    )


# Project icons (architecture 24.6)


def validate_svg(text: str) -> str:
    """A small, self-contained SVG: no scripts, no external references, no event handlers."""
    if len(text.encode("utf-8")) > MAX_SVG_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "SVG larger than 64 KB")
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered or "<?xml-stylesheet" in lowered:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "SVG must not declare entities")
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"SVG is not well formed: {exc}"
        ) from None
    if root.tag not in (f"{SVG_NS}svg", "svg"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The root element must be <svg>")
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag in FORBIDDEN_TAGS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"<{tag}> is not allowed in an icon"
            )
        for name, value in element.attrib.items():
            local = name.split("}")[-1].lower()
            if local.startswith("on"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"{local} handlers are not allowed"
                )
            if local == "href" and not str(value).startswith("#"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "external references are not allowed"
                )
            if local == "style" and "url(" in str(value).lower():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "style URLs are not allowed"
                )
        if tag == "style" and "url(" in (element.text or "").lower():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "style URLs are not allowed")
    return text.strip()


def icon_key_for(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60]
    if not slug or not slug[0].isalpha():
        slug = f"icon_{slug}" if slug else "icon"
    return f"project.{slug}"


@router.get("/icons", response_model=list[ProjectIconRead])
async def list_icons(
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectIcon]:
    rows = await session.scalars(
        select(ProjectIcon)
        .where(ProjectIcon.project_id == context.project.id)
        .order_by(ProjectIcon.label)
    )
    return list(rows)


@router.post("/icons", response_model=ProjectIconRead, status_code=status.HTTP_201_CREATED)
async def upload_icon(
    body: ProjectIconCreate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectIcon:
    """Upload an SVG icon for this project under `project.<slug>`; usable as an icon key on
    entity types, device types and entities. Replaces an icon with the same key."""
    svg = validate_svg(body.svg)
    key = body.key or icon_key_for(body.label)
    existing = await session.scalar(
        select(ProjectIcon).where(
            ProjectIcon.project_id == context.project.id, ProjectIcon.key == key
        )
    )
    icon = existing or ProjectIcon(
        project_id=context.project.id, key=key, created_by_user_id=context.user.id
    )
    icon.label = body.label
    icon.svg = svg
    icon.sha256 = hashlib.sha256(svg.encode()).hexdigest()
    session.add(icon)
    await flush_or_409(session, "Icon")
    await record_audit(
        session,
        user=context.user,
        action="project_icon.uploaded" if existing is None else "project_icon.replaced",
        object_type="project_icon",
        object_id=str(icon.id),
        project_id=context.project.id,
        details={"key": key, "label": body.label, "bytes": len(svg)},
    )
    await session.commit()
    return icon


@router.delete("/icons/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_icon(
    key: str,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    icon = await session.scalar(
        select(ProjectIcon).where(
            ProjectIcon.project_id == context.project.id, ProjectIcon.key == key
        )
    )
    if icon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Icon not found")
    await session.delete(icon)
    await record_audit(
        session,
        user=context.user,
        action="project_icon.deleted",
        object_type="project_icon",
        object_id=str(icon.id),
        project_id=context.project.id,
        details={"key": key},
    )
    await session.commit()


# Dashboards (decision D86)


async def _validate_tiles(
    session: AsyncSession, project_id: uuid.UUID, tiles: list[Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tile in tiles:
        if tile.id in seen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"tile id {tile.id} repeats")
        seen.add(tile.id)
        if tile.kind == "saved_view":
            if tile.saved_view_id is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "a saved view tile needs saved_view_id"
                )
            view = await session.get(SavedView, tile.saved_view_id)
            if view is None or view.project_id != project_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"saved view {tile.saved_view_id} is not in this project",
                )
        result.append(tile.model_dump(mode="json"))
    return result


@router.get("/dashboards", response_model=PageResponse[DashboardRead])
async def list_dashboards(
    page: Page = Depends(page),
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[DashboardRead]:
    rows, next_cursor = await paginate(
        session,
        Dashboard.name,
        select(Dashboard).where(Dashboard.project_id == context.project.id),
        page,
    )
    return PageResponse(
        items=[DashboardRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post("/dashboards", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    body: DashboardCreate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> Dashboard:
    dashboard = Dashboard(
        project_id=context.project.id,
        name=body.name,
        description=body.description,
        tiles=await _validate_tiles(session, context.project.id, body.tiles),
        created_by_user_id=context.user.id,
    )
    session.add(dashboard)
    await flush_or_409(session, "Dashboard")
    await record_audit(
        session,
        user=context.user,
        action="dashboard.created",
        object_type="dashboard",
        object_id=str(dashboard.id),
        project_id=context.project.id,
        details={"name": body.name, "tiles": len(body.tiles)},
    )
    await session.commit()
    return dashboard


async def _project_dashboard(
    session: AsyncSession, context: ProjectContext, dashboard_id: uuid.UUID
) -> Dashboard:
    dashboard = await get_or_404(session, Dashboard, dashboard_id, "Dashboard")
    if dashboard.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard not found")
    return dashboard


@router.get("/dashboards/{dashboard_id}", response_model=DashboardRead)
async def get_dashboard(
    dashboard_id: uuid.UUID,
    context: ProjectContext = Depends(get_project_context),
    session: AsyncSession = Depends(get_session),
) -> Dashboard:
    return await _project_dashboard(session, context, dashboard_id)


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    body: DashboardUpdate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> Dashboard:
    dashboard = await _project_dashboard(session, context, dashboard_id)
    changed = apply_patch(dashboard, body, exclude={"tiles"})
    if body.tiles is not None:
        dashboard.tiles = await _validate_tiles(session, context.project.id, body.tiles)
        changed["tiles"] = len(body.tiles)
    await flush_or_409(session, "Dashboard")
    await record_audit(
        session,
        user=context.user,
        action="dashboard.updated",
        object_type="dashboard",
        object_id=str(dashboard.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return dashboard


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    dashboard = await _project_dashboard(session, context, dashboard_id)
    await session.delete(dashboard)
    await record_audit(
        session,
        user=context.user,
        action="dashboard.deleted",
        object_type="dashboard",
        object_id=str(dashboard.id),
        project_id=context.project.id,
        details={"name": dashboard.name},
    )
    await session.commit()
