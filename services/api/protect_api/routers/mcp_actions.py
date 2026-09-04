"""AI action endpoint and policy (architecture 27.4 and 27.6, decision D87).

An AI client's token may write only here. Every action is classified and the server-wide AI
action policy says per action whether it runs at once (`allowed`), needs the person's
confirmation through a second call (`confirmation`), needs the person's high-impact role as
well (`privileged`) or is off (`disabled`). The action then runs through the same frameworks
people use: manual events, alert acknowledgement, device control. Everything is audited with
the MCP actor and the client id.
"""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.deps import require_server_admin
from protect_api.oauth.middleware import mcp_access_var
from protect_api.routers.control import _control_permissions
from protect_api.routers.devices import _visible_device
from protect_api.routers.events import _scoped_alert, alert_read
from protect_api.routers.platform import create_manual_event
from protect_api.schemas.platform import (
    AiActionInfo,
    AiActionRead,
    AiActionRequest,
    AiPolicyRead,
    AiPolicyUpdate,
    EventCreate,
)
from shared.bus import RedisStreamsBus
from shared.control.commands import Actor, command_message, request_command
from shared.database import get_session
from shared.enums import ActorType, AlertStatus, Role
from shared.models import McpPendingAction, Project, ProjectMembership, ServerSetting, User
from shared.oauth import MCPAccessToken, Scope
from shared.permissions import Permission, permissions_for
from shared.rules.events import close_alert
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(prefix="/mcp", tags=["mcp"])
admin_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_server_admin)]
)

POLICY_KEY = "ai_action_policy"
MODES = ("allowed", "confirmation", "privileged", "disabled")
CONFIRMATION_LIFETIME = timedelta(minutes=10)
ACTIONS: dict[str, dict[str, Any]] = {
    "create_event": {
        "class": "safe_write",
        "scope": Scope.EVENTS_WRITE,
        "permission": Permission.EVENTS_WRITE,
    },
    "acknowledge_alert": {
        "class": "safe_write",
        "scope": Scope.ALERTS_WRITE,
        "permission": Permission.ALERTS_WRITE,
    },
    "request_device_status": {
        "class": "operational_control",
        "scope": Scope.DEVICES_CONTROL,
        "permission": Permission.DEVICES_CONTROL,
        "action_key": "REQUEST_STATUS",
    },
    "request_device_position": {
        "class": "operational_control",
        "scope": Scope.DEVICES_CONTROL,
        "permission": Permission.DEVICES_CONTROL,
        "action_key": "REQUEST_POSITION",
    },
}
DEFAULT_POLICY: dict[str, str] = {
    "create_event": "confirmation",
    "acknowledge_alert": "confirmation",
    "request_device_status": "confirmation",
    "request_device_position": "confirmation",
    "high_impact_control": "disabled",
}


async def load_policy(session: AsyncSession) -> tuple[dict[str, str], ServerSetting | None]:
    row = await session.get(ServerSetting, POLICY_KEY)
    policy = dict(DEFAULT_POLICY)
    if row is not None:
        policy.update({k: str(v) for k, v in (row.value or {}).items() if k in DEFAULT_POLICY})
    return policy, row


def _policy_read(policy: dict[str, str], row: ServerSetting | None) -> AiPolicyRead:
    return AiPolicyRead(
        policy=policy,
        actions=[
            AiActionInfo(
                action=name, action_class=spec["class"], scope=spec["scope"], mode=policy[name]
            )
            for name, spec in ACTIONS.items()
        ]
        + [
            AiActionInfo(
                action="high_impact_control",
                action_class="high_impact_control",
                scope="",
                mode=policy["high_impact_control"],
            )
        ],
        modes=list(MODES),
        updated_at=row.updated_at if row else None,
    )


@router.get("/policy", response_model=AiPolicyRead)
async def get_policy(
    _: User = Depends(current_active_user), session: AsyncSession = Depends(get_session)
) -> AiPolicyRead:
    policy, row = await load_policy(session)
    return _policy_read(policy, row)


@admin_router.get("/ai-policy", response_model=AiPolicyRead)
async def admin_get_policy(session: AsyncSession = Depends(get_session)) -> AiPolicyRead:
    policy, row = await load_policy(session)
    return _policy_read(policy, row)


@admin_router.put("/ai-policy", response_model=AiPolicyRead)
async def admin_set_policy(
    body: AiPolicyUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> AiPolicyRead:
    unknown = [k for k in body.policy if k not in DEFAULT_POLICY]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown actions: {', '.join(unknown)}"
        )
    bad = [f"{k}={v}" for k, v in body.policy.items() if v not in MODES]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown modes: {', '.join(bad)}"
        )
    if body.policy.get("high_impact_control") not in (None, "disabled"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "high-impact control stays disabled for AI clients in this version",
        )
    policy, row = await load_policy(session)
    policy.update(body.policy)
    if row is None:
        row = ServerSetting(key=POLICY_KEY, value=policy)
        session.add(row)
    else:
        row.value = policy
    row.updated_by_user_id = user.id
    row.updated_at = utc_now()
    await record_audit(
        session,
        user=user,
        action="ai_policy.updated",
        object_type="server_setting",
        object_id=POLICY_KEY,
        details=policy,
    )
    await session.commit()
    return _policy_read(policy, row)


# Actions


def _access() -> MCPAccessToken:
    access = mcp_access_var.get()
    if access is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This endpoint is for AI clients with an MCP access token; people use the ordinary "
            "endpoints",
        )
    return access


async def _project_permissions(
    session: AsyncSession, user: User, project_id: uuid.UUID
) -> frozenset[Permission]:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    role_value = await session.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.user_id == user.id, ProjectMembership.project_id == project_id
        )
    )
    role = Role(role_value) if role_value is not None else None
    if role is None and not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this project")
    return permissions_for(role, server_admin=user.is_superuser)


def _uuid(parameters: dict[str, Any], key: str) -> uuid.UUID:
    value = parameters.get(key)
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key} must be a UUID"
        ) from None


async def _summary(session: AsyncSession, action: str, parameters: dict[str, Any]) -> str:
    if action == "create_event":
        return (
            f'Create event {parameters.get("event_type")} "{parameters.get("title")}" in '
            f"project {parameters.get('project_id')}"
        )
    if action == "acknowledge_alert":
        return (
            f"Acknowledge alert {parameters.get('alert_id')} in project "
            f"{parameters.get('project_id')}"
        )
    return f"{action.replace('_', ' ')} for device {parameters.get('device_id')}"


async def execute_action(
    session: AsyncSession,
    bus: RedisStreamsBus,
    *,
    user: User,
    access: MCPAccessToken,
    action: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    spec = ACTIONS[action]
    if action == "create_event":
        project_id = _uuid(parameters, "project_id")
        permissions = await _project_permissions(session, user, project_id)
        if spec["permission"] not in permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Permission {spec['permission']} required"
            )
        body = EventCreate.model_validate(
            {k: v for k, v in parameters.items() if k != "project_id"}
        )
        created = await create_manual_event(
            session,
            bus,
            user=user,
            project_id=project_id,
            body=body,
            actor_type=ActorType.MCP,
            client_id=access.client_id,
        )
        return {
            "event_id": str(created.id),
            "title": created.title,
            "alert_id": str(created.alert_id) if created.alert_id else None,
        }
    if action == "acknowledge_alert":
        project_id = _uuid(parameters, "project_id")
        alert_id = _uuid(parameters, "alert_id")
        permissions = await _project_permissions(session, user, project_id)
        if spec["permission"] not in permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Permission {spec['permission']} required"
            )
        alert, event = await _scoped_alert(session, alert_id, project_id)
        note = str(parameters.get("note") or "") or None
        try:
            await close_alert(session, alert, AlertStatus.ACKNOWLEDGED, user_id=user.id, note=note)
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
        await record_audit(
            session,
            user=user,
            action="alert.acknowledged",
            object_type="alert",
            object_id=str(alert.id),
            project_id=project_id,
            details={"event_type": event.event_type, "note": note, "client_id": access.client_id},
            actor_type=ActorType.MCP,
        )
        await session.commit()
        read = alert_read(alert, event)
        return {"alert_id": str(alert.id), "status": read.status, "title": read.title}
    device_id = _uuid(parameters, "device_id")
    device = await _visible_device(session, user, device_id)
    _, permissions = await _control_permissions(session, user, device)
    if spec["permission"] not in permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {spec['permission']} required")
    try:
        command = await request_command(
            session,
            device=device,
            action_key=str(spec["action_key"]),
            parameters={},
            actor=Actor(kind="mcp", user_id=user.id, client=access.client_id),
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
            "action_key": command.action_key,
            "device_id": str(device.id),
            "status": command.status,
            "client_id": access.client_id,
        },
        actor_type=ActorType.MCP,
    )
    await session.commit()
    topic, payload = command_message(command)
    await bus.publish(topic, payload)
    return {
        "command_id": str(command.id),
        "action_key": command.action_key,
        "status": command.status,
        "route": command.route,
        "error_message": command.error_message,
    }


@router.post("/actions", response_model=AiActionRead)
async def propose_action(
    body: AiActionRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> AiActionRead:
    """Run a write on behalf of the person, or hold it for confirmation (decision D87)."""
    access = _access()
    spec = ACTIONS[body.action]
    if spec["scope"] not in access.scopes:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Scope {spec['scope']} was not granted to this client"
        )
    policy, _ = await load_policy(session)
    mode = policy[body.action]
    if mode == "disabled":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{body.action} is disabled for AI clients by the server's AI action policy",
        )
    summary = await _summary(session, body.action, body.parameters)
    if mode == "allowed":
        result = await execute_action(
            session, bus, user=user, access=access, action=body.action, parameters=body.parameters
        )
        return AiActionRead(
            id=None, action=body.action, status="executed", summary=summary, result=result
        )
    if mode == "privileged" and not user.is_superuser:
        project_id = body.parameters.get("project_id")
        permissions = (
            await _project_permissions(session, user, uuid.UUID(str(project_id)))
            if project_id
            else frozenset()
        )
        if Permission.DEVICES_CONTROL_HIGH_IMPACT not in permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This action needs a project admin under the AI action policy",
            )
    pending = McpPendingAction(
        user_id=user.id,
        client_id=access.client_id,
        action=body.action,
        parameters=body.parameters,
        summary=summary,
        expires_at=utc_now() + CONFIRMATION_LIFETIME,
    )
    session.add(pending)
    await record_audit(
        session,
        user=user,
        action="ai_action.proposed",
        object_type="mcp_action",
        object_id=None,
        details={"action": body.action, "client_id": access.client_id, "summary": summary},
        actor_type=ActorType.MCP,
    )
    await session.commit()
    return AiActionRead(
        id=pending.id,
        action=body.action,
        status="confirmation_required",
        summary=summary,
        expires_at=pending.expires_at,
    )


@router.get("/actions/{action_id}", response_model=AiActionRead)
async def get_action(
    action_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> AiActionRead:
    pending = await session.get(McpPendingAction, action_id)
    if pending is None or pending.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending action not found")
    state = (
        "executed"
        if pending.executed_at
        else ("expired" if pending.expires_at < utc_now() else "confirmation_required")
    )
    return AiActionRead(
        id=pending.id,
        action=pending.action,
        status=state,
        summary=pending.summary,
        expires_at=pending.expires_at,
        result=pending.result,
    )


@router.post("/actions/{action_id}/confirm", response_model=AiActionRead)
async def confirm_action(
    action_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> AiActionRead:
    """The second call of the confirmation flow: the same person and client execute what was
    proposed, within ten minutes."""
    access = _access()
    pending = await session.get(McpPendingAction, action_id)
    if pending is None or pending.user_id != user.id or pending.client_id != access.client_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Pending action not found for this person and client"
        )
    if pending.executed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This action was executed already")
    if pending.expires_at < utc_now():
        raise HTTPException(status.HTTP_409_CONFLICT, "This proposal expired; propose it again")
    policy, _ = await load_policy(session)
    if policy[pending.action] == "disabled":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The action was disabled by the AI action policy meanwhile"
        )
    result = await execute_action(
        session,
        bus,
        user=user,
        access=access,
        action=pending.action,
        parameters=dict(pending.parameters),
    )
    pending.executed_at = utc_now()
    pending.result = result
    await record_audit(
        session,
        user=user,
        action="ai_action.confirmed",
        object_type="mcp_action",
        object_id=str(pending.id),
        details={"action": pending.action, "client_id": access.client_id},
        actor_type=ActorType.MCP,
    )
    await session.commit()
    return AiActionRead(
        id=pending.id,
        action=pending.action,
        status="executed",
        summary=pending.summary,
        result=result,
    )
