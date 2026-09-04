"""Device control (architecture 17): the actions a device offers, commands and their
lifecycle, the platform's downlink queue. Manual and automated commands share
`shared.control.commands.request_command`; this router adds the permission and confirmation
checks a person needs."""

import base64
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.crud import get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page
from protect_api.routers.devices import _visible_device
from protect_api.schemas.control import (
    ActionAvailability,
    BrowserResult,
    CommandCreate,
    CommandDetail,
    CommandExecutionRead,
    CommandRead,
    QueueItem,
    QueueState,
    RouteOptionRead,
)
from shared.bus import RedisStreamsBus
from shared.control.actions import ConfirmationPolicy, actions_of
from shared.control.commands import (
    FINAL,
    Actor,
    _record,
    available_actions,
    candidate_routes,
    command_message,
    driver_for,
    request_command,
    select_route,
)
from shared.database import get_session
from shared.domain.assignments import resolve_attribution
from shared.enums import CommandStatus, ErrorCode, Role
from shared.ingest import builtin_source, ensure_channel_identity
from shared.models import Command, CommandExecution, Device, ProjectMembership, User
from shared.permissions import Permission, permissions_for
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(tags=["control"])


async def _control_permissions(
    session: AsyncSession, user: User, device: Device
) -> tuple[uuid.UUID | None, frozenset[Permission]]:
    """The caller's permissions in the device's current project. A device without a project
    can only be controlled by a server admin."""
    attribution = await resolve_attribution(session, device.id, utc_now())
    if user.is_superuser:
        return attribution.project_id, permissions_for(None, server_admin=True)
    if attribution.project_id is None:
        return None, frozenset()
    role_value = await session.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.project_id == attribution.project_id,
        )
    )
    role = Role(role_value) if role_value else None
    return attribution.project_id, permissions_for(role, server_admin=False)


@router.get("/devices/{device_id}/actions", response_model=list[ActionAvailability])
async def list_actions(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[ActionAvailability]:
    """What the device can do now: each action with why it is unavailable, so the UI explains
    instead of hiding (architecture 17.3)."""
    device = await _visible_device(session, user, device_id)
    _, permissions = await _control_permissions(session, user, device)
    result = []
    for availability in await available_actions(session, device):
        described = availability.action.describe()
        result.append(
            ActionAvailability(
                **described,
                available=availability.available,
                reason=availability.reason,
                permitted=availability.action.permission in permissions,
            )
        )
    return result


@router.get("/devices/{device_id}/routes", response_model=list[RouteOptionRead])
async def list_routes(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[RouteOptionRead]:
    """Every way a command could reach the device, most recently seen first (decision D79).
    The browser route appears once the device was connected over WebBLE in this application."""
    device = await _visible_device(session, user, device_id)
    return [
        RouteOptionRead(**{k: getattr(option, k) for k in RouteOptionRead.model_fields})
        for option in await candidate_routes(session, device)
    ]


@router.post("/devices/{device_id}/routes/webble", response_model=RouteOptionRead)
async def connect_webble_route(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> RouteOptionRead:
    """The browser reports that the device is connected over Web Bluetooth: the device gets
    its identity on the built-in WebBLE source, which makes the route selectable."""
    device = await _visible_device(session, user, device_id)
    _, permissions = await _control_permissions(session, user, device)
    if Permission.DEVICES_CONTROL not in permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Permission {Permission.DEVICES_CONTROL} required"
        )
    source = await builtin_source(session, "webble")
    identity = await ensure_channel_identity(session, source, device.id)
    identity.last_seen_at = utc_now()
    await session.commit()
    for option in await candidate_routes(session, device):
        if option.data_source_id == source.id:
            return RouteOptionRead(**{k: getattr(option, k) for k in RouteOptionRead.model_fields})
    raise HTTPException(status.HTTP_409_CONFLICT, "The WebBLE source is disabled")


@router.post(
    "/devices/{device_id}/commands", response_model=CommandRead, status_code=status.HTTP_201_CREATED
)
async def create_command(
    device_id: uuid.UUID,
    body: CommandCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> Command:
    """Issue a command. The response carries the lifecycle so far; a command the platform
    refused is returned as failed with the reason, and stays in the history."""
    device = await _visible_device(session, user, device_id)
    _, permissions = await _control_permissions(session, user, device)
    _, driver = await driver_for(session, device)
    action = actions_of(driver).get(body.action_key)
    if action is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No action {body.action_key} for this device"
        )
    if action.permission not in permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {action.permission} required")
    if action.confirmation != ConfirmationPolicy.NONE and not body.confirmed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Action {action.key} needs explicit confirmation"
        )
    try:
        command = await request_command(
            session,
            device=device,
            action_key=action.key,
            parameters=body.parameters,
            actor=Actor(kind="user", user_id=user.id),
            route_source_id=body.route_data_source_id,
        )
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await record_audit(
        session,
        user=user,
        action="command.created",
        object_type="command",
        object_id=str(command.id),
        project_id=command.project_id,
        details={
            "action_key": action.key,
            "device_id": str(device.id),
            "status": command.status,
            "route": command.route,
            "data_source_id": str(command.data_source_id) if command.data_source_id else None,
        },
    )
    await session.commit()
    topic, payload = command_message(command)
    await bus.publish(topic, payload)
    return command


@router.post("/commands/{command_id}/browser-result", response_model=CommandRead)
async def browser_result(
    command_id: uuid.UUID,
    body: BrowserResult,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> Command:
    """The browser executed (or could not execute) a WebBLE command (decision D79). The
    device's own answer arrives through the synced frames and the action's interpreter."""
    command = await get_or_404(session, Command, command_id, "Command")
    device = await _visible_device(session, user, command.device_id)
    _, permissions = await _control_permissions(session, user, device)
    if Permission.DEVICES_CONTROL not in permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Permission {Permission.DEVICES_CONTROL} required"
        )
    if command.route != "webble":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only WebBLE commands are executed by a browser"
        )
    if command.status in FINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The command is already {command.status}")
    now = utc_now()
    if body.status == "transmitted":
        command.transmitted_at = command.transmitted_at or now
        moved = await _record(
            session,
            command,
            CommandStatus.TRANSMITTED,
            "browser",
            {**body.detail, "user_id": str(user.id)},
        )
    else:
        command.error_code = ErrorCode.COMMAND_REJECTED
        command.error_message = body.error_message or "the browser could not write the command"
        moved = await _record(
            session,
            command,
            CommandStatus.FAILED,
            "browser",
            {**body.detail, "user_id": str(user.id)},
        )
    await record_audit(
        session,
        user=user,
        action="command.browser_result",
        object_type="command",
        object_id=str(command.id),
        project_id=command.project_id,
        details={"status": body.status, "device_id": str(device.id)},
    )
    await session.commit()
    if moved:
        topic, payload = command_message(command)
        await bus.publish(topic, payload)
    return command


@router.get("/devices/{device_id}/commands", response_model=list[CommandRead])
async def list_device_commands(
    device_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[Command]:
    device = await _visible_device(session, user, device_id)
    rows = await session.scalars(
        select(Command)
        .where(Command.device_id == device.id)
        .order_by(Command.created_at.desc())
        .limit(limit)
    )
    return list(rows)


@router.get("/commands/{command_id}", response_model=CommandDetail)
async def get_command(
    command_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> CommandDetail:
    command = await get_or_404(session, Command, command_id, "Command")
    await _visible_device(session, user, command.device_id)
    executions = await session.scalars(
        select(CommandExecution)
        .where(CommandExecution.command_id == command.id)
        .order_by(CommandExecution.time, CommandExecution.id)
        .limit(100)
    )
    return CommandDetail(
        command=CommandRead.model_validate(command),
        executions=[CommandExecutionRead.model_validate(e) for e in executions],
    )


@router.get("/projects/{project_id}/commands", response_model=PageResponse[CommandRead])
async def list_project_commands(
    page: Page = Depends(page),
    command_status: str | None = Query(None, alias="status"),
    device_id: uuid.UUID | None = None,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[CommandRead]:
    """Newest first; the cursor is the created time of the last item."""
    statement = select(Command).where(Command.project_id == context.project.id)
    if command_status:
        statement = statement.where(Command.status == command_status)
    if device_id is not None:
        statement = statement.where(Command.device_id == device_id)
    if page.cursor:
        try:
            before = utc_now().fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(Command.created_at < before)
    rows = list(
        (
            await session.scalars(
                statement.order_by(Command.created_at.desc()).limit(page.limit + 1)
            )
        ).all()
    )
    items = [CommandRead.model_validate(c) for c in rows[: page.limit]]
    next_cursor = items[-1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)


@router.get("/devices/{device_id}/downlink-queue", response_model=QueueState)
async def downlink_queue(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> QueueState:
    """The platform's queue for the device, when the adapter can read it."""
    device = await _visible_device(session, user, device_id)
    route, _ = await select_route(session, device)
    reader = getattr(route.connector, "queue", None) if route else None
    if route is None or reader is None:
        return QueueState(data_source_id=None, external_id=None, supported=False, items=[])
    try:
        raw = await reader(route.identity.external_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{route.source.name}: {exc}") from exc
    items = []
    for item in raw:
        data = item.get("data")
        items.append(
            QueueItem(
                id=item.get("id"),
                f_port=item.get("fPort"),
                confirmed=item.get("confirmed"),
                is_pending=item.get("isPending"),
                f_cnt_down=item.get("fCntDown"),
                data_hex=base64.b64decode(data).hex() if isinstance(data, str) else None,
            )
        )
    return QueueState(
        data_source_id=route.source.id,
        external_id=route.identity.external_id,
        supported=True,
        items=items,
    )


@router.delete("/devices/{device_id}/downlink-queue", status_code=status.HTTP_204_NO_CONTENT)
async def flush_downlink_queue(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Drop every queued downlink on the platform. High impact: pending commands never reach
    the device and expire."""
    device = await _visible_device(session, user, device_id)
    project_id, permissions = await _control_permissions(session, user, device)
    if Permission.DEVICES_CONTROL_HIGH_IMPACT not in permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Permission devices:control_high_impact required"
        )
    route, reason = await select_route(session, device)
    flusher = getattr(route.connector, "flush", None) if route else None
    if route is None or flusher is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, reason or "the platform has no queue to flush"
        )
    try:
        await flusher(route.identity.external_id)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{route.source.name}: {exc}") from exc
    await record_audit(
        session,
        user=user,
        action="command.queue_flushed",
        object_type="device",
        object_id=str(device.id),
        project_id=project_id,
        details={"data_source_id": str(route.source.id)},
    )
    await session.commit()
