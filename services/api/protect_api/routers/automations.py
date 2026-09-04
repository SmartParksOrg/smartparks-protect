"""Automations, notification targets and action deliveries, for a project and at server level
(project null, server admins). The two scopes share the implementation; only the dependency
that authorises the caller differs."""

import secrets
import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission, require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.rules import (
    ActionDeliveryRead,
    AutomationCreate,
    AutomationRead,
    AutomationUpdate,
    NotificationCapabilities,
    NotificationTargetCreate,
    NotificationTargetRead,
    NotificationTargetUpdate,
    TestSendResult,
)
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import get_session
from shared.enums import ActionType, DeliveryStatus, NotificationChannel
from shared.models import (
    ActionDelivery,
    Alert,
    Automation,
    Event,
    NotificationTarget,
    Project,
    User,
)
from shared.notifications import telegram
from shared.notifications.dispatch import (
    PermanentFailure,
    Skipped,
    TransientFailure,
    deliver_to_target,
)
from shared.notifications.render import render_test
from shared.permissions import Permission
from shared.rules.events import event_messages
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}", tags=["automations"])
admin_router = APIRouter(
    prefix="/admin", tags=["automations"], dependencies=[Depends(require_server_admin)]
)

LINK_CODE_HOURS = 24


@lru_cache
def _bot_username_cache() -> dict[str, str | None]:
    return {}


async def bot_username() -> str | None:
    """The bot's username, fetched once per process; None when Telegram is not configured or
    unreachable (the link code still works when the user finds the bot by hand)."""
    if not get_settings().telegram_configured:
        return None
    cache = _bot_username_cache()
    if "username" not in cache:
        try:
            cache["username"] = str((await telegram.get_me()).get("username") or "") or None
        except Exception:
            return None
    return cache["username"]


def new_link_code() -> str:
    return secrets.token_hex(4).upper()


async def target_read(target: NotificationTarget) -> NotificationTargetRead:
    data = NotificationTargetRead.model_validate(target)
    data.linked = target.channel != NotificationChannel.TELEGRAM or bool(target.telegram_chat_id)
    if target.telegram_link_code:
        username = await bot_username()
        if username:
            data.link_url = f"https://t.me/{username}?start={target.telegram_link_code}"
    return data


def _scope_filter(model: Any, project_id: uuid.UUID | None) -> Any:
    return model.project_id == project_id if project_id is not None else model.project_id.is_(None)


class _Scoped(Protocol):
    project_id: uuid.UUID | None


async def _scoped[T: _Scoped](
    session: AsyncSession, model: type[T], id_: uuid.UUID, project_id: uuid.UUID | None, what: str
) -> T:
    obj = await get_or_404(session, model, id_, what)
    if obj.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return obj


async def _check_actions(
    session: AsyncSession, actions: list[dict[str, Any]], project_id: uuid.UUID | None
) -> None:
    for action in actions:
        kind = action.get("type")
        if kind == ActionType.NOTIFY:
            target_id = action.get("target_id")
            if not target_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "notify action needs a target_id"
                )
            target = await session.get(NotificationTarget, uuid.UUID(str(target_id)))
            if target is None or target.project_id != project_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"notification target {target_id} not found in this scope",
                )
        elif kind == ActionType.WEBHOOK:
            url = str(action.get("url") or "")
            if not url.startswith(("http://", "https://")):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "webhook action needs an http(s) url"
                )
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"action type {kind} arrives in a later phase",
            )


def _dump_actions(actions: list[Any]) -> list[dict[str, Any]]:
    return [a.model_dump(mode="json", exclude_none=True) for a in actions]


# Automations


async def list_automations_for(
    session: AsyncSession, project_id: uuid.UUID | None, page: Page
) -> PageResponse[AutomationRead]:
    rows, next_cursor = await paginate(
        session,
        Automation.id,
        select(Automation).where(_scope_filter(Automation, project_id)),
        page,
    )
    return PageResponse(
        items=[AutomationRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


async def create_automation_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, body: AutomationCreate
) -> Automation:
    actions = _dump_actions(body.actions)
    await _check_actions(session, actions, project_id)
    automation = Automation(
        project_id=project_id,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        event_types=body.event_types,
        min_severity=body.min_severity,
        require_alert=body.require_alert,
        entity_ids=[str(i) for i in body.entity_ids],
        rule_ids=[str(i) for i in body.rule_ids],
        actions=actions,
        max_event_age_seconds=body.max_event_age_seconds,
        created_by_user_id=user.id,
    )
    session.add(automation)
    await flush_or_409(session, "Automation")
    await record_audit(
        session,
        user=user,
        action="automation.created",
        object_type="automation",
        object_id=str(automation.id),
        project_id=project_id,
        details={"name": automation.name, "actions": len(actions)},
    )
    await session.commit()
    return automation


async def update_automation_for(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user: User,
    automation_id: uuid.UUID,
    body: AutomationUpdate,
) -> Automation:
    automation = await _scoped(session, Automation, automation_id, project_id, "Automation")
    changed: dict[str, Any] = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "actions" and body.actions is not None:
            value = _dump_actions(body.actions)
            await _check_actions(session, value, project_id)
        elif key in ("entity_ids", "rule_ids") and value is not None:
            value = [str(i) for i in value]
        elif key == "min_severity" and value is not None:
            value = str(value)
        if getattr(automation, key) != value:
            setattr(automation, key, value)
            changed[key] = value
    await flush_or_409(session, "Automation")
    await record_audit(
        session,
        user=user,
        action="automation.updated",
        object_type="automation",
        object_id=str(automation.id),
        project_id=project_id,
        details=changed,
    )
    await session.commit()
    return automation


async def delete_automation_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, automation_id: uuid.UUID
) -> None:
    automation = await _scoped(session, Automation, automation_id, project_id, "Automation")
    await record_audit(
        session,
        user=user,
        action="automation.deleted",
        object_type="automation",
        object_id=str(automation.id),
        project_id=project_id,
        details={"name": automation.name},
    )
    await session.delete(automation)
    await session.commit()


# Notification targets


async def list_targets_for(
    session: AsyncSession, project_id: uuid.UUID | None, page: Page
) -> PageResponse[NotificationTargetRead]:
    rows, next_cursor = await paginate(
        session,
        NotificationTarget.id,
        select(NotificationTarget).where(_scope_filter(NotificationTarget, project_id)),
        page,
    )
    return PageResponse(items=[await target_read(r) for r in rows], next_cursor=next_cursor)


async def create_target_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, body: NotificationTargetCreate
) -> NotificationTarget:
    if body.channel == NotificationChannel.EMAIL and not (body.address and "@" in body.address):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "email target needs an address")
    target = NotificationTarget(
        project_id=project_id,
        name=body.name,
        channel=body.channel,
        address=body.address if body.channel == NotificationChannel.EMAIL else None,
        enabled=body.enabled,
        created_by_user_id=user.id,
    )
    if body.channel == NotificationChannel.TELEGRAM:
        target.telegram_link_code = new_link_code()
        target.telegram_link_expires_at = utc_now() + timedelta(hours=LINK_CODE_HOURS)
    session.add(target)
    await flush_or_409(session, "Notification target")
    await record_audit(
        session,
        user=user,
        action="notification_target.created",
        object_type="notification_target",
        object_id=str(target.id),
        project_id=project_id,
        details={"name": target.name, "channel": target.channel},
    )
    await session.commit()
    return target


async def update_target_for(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    user: User,
    target_id: uuid.UUID,
    body: NotificationTargetUpdate,
) -> NotificationTarget:
    target = await _scoped(
        session, NotificationTarget, target_id, project_id, "Notification target"
    )
    changed: dict[str, Any] = {}
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "address" and target.channel != NotificationChannel.EMAIL:
            continue
        if getattr(target, key) != value:
            setattr(target, key, value)
            changed[key] = value
    await flush_or_409(session, "Notification target")
    await record_audit(
        session,
        user=user,
        action="notification_target.updated",
        object_type="notification_target",
        object_id=str(target.id),
        project_id=project_id,
        details=changed,
    )
    await session.commit()
    return target


async def delete_target_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, target_id: uuid.UUID
) -> None:
    target = await _scoped(
        session, NotificationTarget, target_id, project_id, "Notification target"
    )
    await record_audit(
        session,
        user=user,
        action="notification_target.deleted",
        object_type="notification_target",
        object_id=str(target.id),
        project_id=project_id,
        details={"name": target.name},
    )
    await session.delete(target)
    await session.commit()


async def new_link_code_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, target_id: uuid.UUID
) -> NotificationTarget:
    target = await _scoped(
        session, NotificationTarget, target_id, project_id, "Notification target"
    )
    if target.channel != NotificationChannel.TELEGRAM:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only Telegram targets link with a code")
    target.telegram_link_code = new_link_code()
    target.telegram_link_expires_at = utc_now() + timedelta(hours=LINK_CODE_HOURS)
    target.telegram_chat_id = None
    await session.commit()
    return target


async def test_target_for(
    session: AsyncSession, project_id: uuid.UUID | None, user: User, target_id: uuid.UUID
) -> TestSendResult:
    target = await _scoped(
        session, NotificationTarget, target_id, project_id, "Notification target"
    )
    project = await session.get(Project, project_id) if project_id else None
    rendered = render_test(target.name, project.name if project else None)
    await record_audit(
        session,
        user=user,
        action="notification_target.tested",
        object_type="notification_target",
        object_id=str(target.id),
        project_id=project_id,
    )
    await session.commit()
    try:
        await deliver_to_target(target, rendered)
    except Skipped as reason:
        return TestSendResult(status="skipped", detail=str(reason))
    except (PermanentFailure, TransientFailure) as failure:
        return TestSendResult(status="failed", detail=str(failure))
    return TestSendResult(status="sent")


# Deliveries


async def list_deliveries_for(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    page: Page,
    delivery_status: str | None,
) -> PageResponse[ActionDeliveryRead]:
    statement = select(ActionDelivery).where(_scope_filter(ActionDelivery, project_id))
    if delivery_status:
        statement = statement.where(ActionDelivery.status == delivery_status)
    if page.cursor:
        try:
            before = utc_now().fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(ActionDelivery.created_at < before)
    rows = list(
        (
            await session.scalars(
                statement.order_by(ActionDelivery.created_at.desc()).limit(page.limit + 1)
            )
        ).all()
    )
    items = [ActionDeliveryRead.model_validate(d) for d in rows[: page.limit]]
    next_cursor = items[-1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(items=items, next_cursor=next_cursor)


async def retry_delivery_for(
    session: AsyncSession,
    bus: RedisStreamsBus,
    project_id: uuid.UUID | None,
    user: User,
    delivery_id: uuid.UUID,
) -> ActionDeliveryRead:
    """Queue the delivery again and republish the event; the automation service skips the
    deliveries that already succeeded."""
    delivery = await _scoped(session, ActionDelivery, delivery_id, project_id, "Delivery")
    if delivery.status == DeliveryStatus.SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery already sent")
    event = await get_or_404(session, Event, delivery.event_id, "Event")
    alert = await session.get(Alert, delivery.alert_id) if delivery.alert_id else None
    delivery.status = DeliveryStatus.QUEUED
    delivery.error_code = None
    delivery.error_message = None
    await record_audit(
        session,
        user=user,
        action="delivery.retried",
        object_type="action_delivery",
        object_id=str(delivery.id),
        project_id=project_id,
    )
    await session.commit()
    for topic, payload in event_messages(event, alert)[:1]:
        await bus.publish(topic, payload)
    return ActionDeliveryRead.model_validate(delivery)


def capabilities_read(username: str | None) -> NotificationCapabilities:
    settings = get_settings()
    return NotificationCapabilities(
        mail_configured=settings.mail_configured,
        telegram_configured=settings.telegram_configured,
        telegram_bot_username=username,
    )


# Project routes


@router.get("/notifications/capabilities", response_model=NotificationCapabilities)
async def project_capabilities(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
) -> NotificationCapabilities:
    return capabilities_read(await bot_username())


@router.get("/automations", response_model=PageResponse[AutomationRead])
async def list_automations(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[AutomationRead]:
    return await list_automations_for(session, context.project.id, page)


@router.post("/automations", response_model=AutomationRead, status_code=status.HTTP_201_CREATED)
async def create_automation(
    body: AutomationCreate,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> Automation:
    return await create_automation_for(session, context.project.id, context.user, body)


@router.patch("/automations/{automation_id}", response_model=AutomationRead)
async def update_automation(
    automation_id: uuid.UUID,
    body: AutomationUpdate,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> Automation:
    return await update_automation_for(
        session, context.project.id, context.user, automation_id, body
    )


@router.delete("/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    automation_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await delete_automation_for(session, context.project.id, context.user, automation_id)


@router.get("/notification-targets", response_model=PageResponse[NotificationTargetRead])
async def list_targets(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[NotificationTargetRead]:
    return await list_targets_for(session, context.project.id, page)


@router.post(
    "/notification-targets",
    response_model=NotificationTargetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_target(
    body: NotificationTargetCreate,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(
        await create_target_for(session, context.project.id, context.user, body)
    )


@router.patch("/notification-targets/{target_id}", response_model=NotificationTargetRead)
async def update_target(
    target_id: uuid.UUID,
    body: NotificationTargetUpdate,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(
        await update_target_for(session, context.project.id, context.user, target_id, body)
    )


@router.delete("/notification-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    target_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await delete_target_for(session, context.project.id, context.user, target_id)


@router.post("/notification-targets/{target_id}/link-code", response_model=NotificationTargetRead)
async def target_link_code(
    target_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(
        await new_link_code_for(session, context.project.id, context.user, target_id)
    )


@router.post("/notification-targets/{target_id}/test", response_model=TestSendResult)
async def test_target(
    target_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> TestSendResult:
    return await test_target_for(session, context.project.id, context.user, target_id)


@router.get("/deliveries", response_model=PageResponse[ActionDeliveryRead])
async def list_deliveries(
    page: Page = Depends(page),
    delivery_status: str | None = Query(None, alias="status"),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[ActionDeliveryRead]:
    return await list_deliveries_for(session, context.project.id, page, delivery_status)


@router.post("/deliveries/{delivery_id}/retry", response_model=ActionDeliveryRead)
async def retry_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.AUTOMATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ActionDeliveryRead:
    return await retry_delivery_for(session, bus, context.project.id, context.user, delivery_id)


# Server routes (system events, project null)


@admin_router.get("/notifications/capabilities", response_model=NotificationCapabilities)
async def admin_capabilities() -> NotificationCapabilities:
    return capabilities_read(await bot_username())


@admin_router.get("/automations", response_model=PageResponse[AutomationRead])
async def admin_list_automations(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[AutomationRead]:
    return await list_automations_for(session, None, page)


@admin_router.post(
    "/automations", response_model=AutomationRead, status_code=status.HTTP_201_CREATED
)
async def admin_create_automation(
    body: AutomationCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Automation:
    return await create_automation_for(session, None, user, body)


@admin_router.patch("/automations/{automation_id}", response_model=AutomationRead)
async def admin_update_automation(
    automation_id: uuid.UUID,
    body: AutomationUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Automation:
    return await update_automation_for(session, None, user, automation_id, body)


@admin_router.delete("/automations/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_automation(
    automation_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    await delete_automation_for(session, None, user, automation_id)


@admin_router.get("/notification-targets", response_model=PageResponse[NotificationTargetRead])
async def admin_list_targets(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[NotificationTargetRead]:
    return await list_targets_for(session, None, page)


@admin_router.post(
    "/notification-targets",
    response_model=NotificationTargetRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_target(
    body: NotificationTargetCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(await create_target_for(session, None, user, body))


@admin_router.patch("/notification-targets/{target_id}", response_model=NotificationTargetRead)
async def admin_update_target(
    target_id: uuid.UUID,
    body: NotificationTargetUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(await update_target_for(session, None, user, target_id, body))


@admin_router.delete("/notification-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_target(
    target_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    await delete_target_for(session, None, user, target_id)


@admin_router.post(
    "/notification-targets/{target_id}/link-code", response_model=NotificationTargetRead
)
async def admin_target_link_code(
    target_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> NotificationTargetRead:
    return await target_read(await new_link_code_for(session, None, user, target_id))


@admin_router.post("/notification-targets/{target_id}/test", response_model=TestSendResult)
async def admin_test_target(
    target_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> TestSendResult:
    return await test_target_for(session, None, user, target_id)


@admin_router.get("/deliveries", response_model=PageResponse[ActionDeliveryRead])
async def admin_list_deliveries(
    page: Page = Depends(page),
    delivery_status: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[ActionDeliveryRead]:
    return await list_deliveries_for(session, None, page, delivery_status)


@admin_router.post("/deliveries/{delivery_id}/retry", response_model=ActionDeliveryRead)
async def admin_retry_delivery(
    delivery_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> ActionDeliveryRead:
    return await retry_delivery_for(session, bus, None, user, delivery_id)
