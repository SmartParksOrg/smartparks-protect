"""Actions for an event (architecture 16): one `ActionDelivery` per automation action per
event, idempotent under bus re-delivery. Transient failures (SMTP, HTTP 5xx, timeouts) raise a
retryable error after the successful actions are committed, so the bus re-delivers and only
the failed actions run again. Stale events (older than the automation's freshness bound) are
skipped and recorded, never acted on (architecture 25.8)."""

import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.control.commands import Actor, command_message, request_command
from shared.enums import ActionType, DeliveryStatus, ErrorCode, Severity
from shared.logger import get_logger
from shared.models import (
    ActionDelivery,
    Alert,
    Automation,
    Command,
    Device,
    Entity,
    Event,
    NotificationTarget,
    Project,
)
from shared.notifications.dispatch import (
    PermanentFailure,
    Skipped,
    TransientFailure,
    deliver_to_target,
)
from shared.notifications.render import EventMessage, render_event
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("automation")

SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


def matches(automation: Automation, event: Event, alert_id: str | None) -> bool:
    if automation.event_types and event.event_type not in automation.event_types:
        return False
    if SEVERITY_RANK.get(Severity(event.severity), 0) < SEVERITY_RANK.get(
        Severity(automation.min_severity), 0
    ):
        return False
    if automation.require_alert and alert_id is None:
        return False
    if automation.entity_ids and (
        event.entity_id is None or str(event.entity_id) not in automation.entity_ids
    ):
        return False
    return not (
        automation.rule_ids and str(event.context.get("rule_id")) not in automation.rule_ids
    )


async def build_message(session: AsyncSession, event: Event, alert: Alert | None) -> EventMessage:
    project = await session.get(Project, event.project_id) if event.project_id else None
    entity = await session.get(Entity, event.entity_id) if event.entity_id else None
    device = await session.get(Device, event.device_id) if event.device_id else None
    return EventMessage(
        event_id=str(event.id),
        event_type=event.event_type,
        severity=event.severity,
        title=event.title,
        time=event.time.isoformat(timespec="seconds"),
        description=event.description,
        project_id=str(event.project_id) if event.project_id else None,
        project_name=project.name if project else None,
        entity_name=entity.name if entity else None,
        device_name=device.name if device else None,
        alert=alert is not None and alert.status == "open",
        context={k: v for k, v in event.context.items() if k != "values"},
    )


def webhook_payload(message: EventMessage, event: Event, alert: Alert | None) -> dict[str, Any]:
    return {
        "event": {
            "id": str(event.id),
            "type": event.event_type,
            "severity": event.severity,
            "title": event.title,
            "description": event.description,
            "time": event.time.isoformat(),
            "project_id": message.project_id,
            "entity_id": str(event.entity_id) if event.entity_id else None,
            "device_id": str(event.device_id) if event.device_id else None,
            "context": event.context,
        },
        "alert": {"id": str(alert.id), "status": alert.status} if alert else None,
        "project": message.project_name,
        "entity": message.entity_name,
        "device": message.device_name,
        "link": message.link,
    }


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def post_webhook(action: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    url = action.get("url")
    if not url or not str(url).startswith(("http://", "https://")):
        raise PermanentFailure("webhook action without a valid url")
    body = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "smartparks-protect"}
    secret = action.get("secret")
    if secret:
        headers["X-Protect-Signature"] = sign(str(secret), body)
    try:
        async with httpx.AsyncClient(timeout=get_settings().webhook_timeout_seconds) as client:
            response = await client.post(str(url), content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise TransientFailure(f"webhook: {type(exc).__name__}: {exc}") from exc
    summary = {"status": response.status_code, "body": response.text[:500]}
    if response.status_code >= 500:
        raise TransientFailure(f"webhook answered {response.status_code}")
    if response.status_code >= 400:
        raise PermanentFailure(f"webhook answered {response.status_code}: {response.text[:200]}")
    return summary


async def run_action(
    session: AsyncSession,
    automation: Automation,
    action: dict[str, Any],
    event: Event,
    alert: Alert | None,
    message: EventMessage,
) -> dict[str, Any]:
    kind = action.get("type")
    if kind == ActionType.NOTIFY:
        target_id = action.get("target_id")
        target = (
            await session.get(NotificationTarget, uuid.UUID(str(target_id))) if target_id else None
        )
        if target is None:
            raise PermanentFailure("notification target not found")
        if target.project_id != automation.project_id:
            raise PermanentFailure("notification target belongs to another project")
        return await deliver_to_target(target, render_event(message))
    if kind == ActionType.WEBHOOK:
        return await post_webhook(action, webhook_payload(message, event, alert))
    if kind == ActionType.COMMAND:
        if event.device_id is None:
            raise PermanentFailure("the event has no device to command")
        device = await session.get(Device, event.device_id)
        if device is None:
            raise PermanentFailure("the event's device no longer exists")
        try:
            command = await request_command(
                session,
                device=device,
                action_key=str(action.get("action_key") or ""),
                parameters=dict(action.get("parameters") or {}),
                actor=Actor(kind="automation", automation_id=automation.id, event_id=event.id),
            )
        except ApplicationError as error:
            raise PermanentFailure(str(error)) from error
        if command.status == "failed":
            if command.error_code == ErrorCode.CONNECTIVITY_UNAVAILABLE:
                raise TransientFailure(command.error_message or "platform unavailable")
            raise PermanentFailure(command.error_message or "command failed")
        return {"command_id": str(command.id), "status": command.status}
    if kind == ActionType.INTEGRATION:
        raise PermanentFailure(f"action type {kind} arrives in a later phase")
    raise PermanentFailure(f"unknown action type {kind!r}")


async def handle_event(
    session: AsyncSession,
    payload: dict[str, Any],
    messages: list[tuple[str, dict[str, Any]]] | None = None,
) -> bool:
    """Run every matching automation for the event. Returns True when a transient failure
    needs a retry. Commits before returning."""
    event_id = uuid.UUID(str(payload["event_id"]))
    event = await session.get(Event, event_id)
    if event is None:
        log.warning("event vanished before automations ran", event_id=str(event_id))
        return False
    alert_id = payload.get("alert_id")
    alert = await session.get(Alert, uuid.UUID(str(alert_id))) if alert_id else None
    statement = select(Automation).where(Automation.enabled.is_(True))
    statement = (
        statement.where(Automation.project_id == event.project_id)
        if event.project_id is not None
        else statement.where(Automation.project_id.is_(None))
    )
    automations = [
        a for a in (await session.scalars(statement)).all() if matches(a, event, alert_id)
    ]
    if not automations:
        return False
    message = await build_message(session, event, alert)
    age = (utc_now() - event.time).total_seconds()
    tracer = Tracer(
        session,
        root_object_type="event",
        root_object_id=str(event.id),
        compact=True,
        project_id=event.project_id,
        device_id=event.device_id,
    )
    await tracer.start()
    retry = False
    for automation in automations:
        for index, action in enumerate(automation.actions):
            delivery = await _delivery(session, event, alert, automation, index, action)
            if delivery.status in (DeliveryStatus.SENT, DeliveryStatus.SKIPPED):
                continue
            delivery.trace_id = tracer.trace_id
            async with tracer.step(
                "automation",
                f"{automation.name}: {action.get('type')}",
                input_ref=f"automation:{automation.id}",
                output_ref=f"delivery:{delivery.id}",
            ) as step:
                if age > automation.max_event_age_seconds:
                    delivery.status = DeliveryStatus.SKIPPED
                    delivery.error_message = (
                        f"event is {int(age)} s old, automation accepts "
                        f"{automation.max_event_age_seconds} s"
                    )
                    step.skip("stale event")
                    continue
                delivery.attempts += 1
                delivery.last_attempt_at = utc_now()
                try:
                    response = await run_action(session, automation, action, event, alert, message)
                except Skipped as reason:
                    delivery.status = DeliveryStatus.SKIPPED
                    delivery.error_message = str(reason)
                    step.skip(str(reason))
                except PermanentFailure as failure:
                    delivery.status = DeliveryStatus.FAILED
                    delivery.error_code = ErrorCode.ACTION_FAILED
                    delivery.error_message = str(failure)[:2000]
                    step.metadata["error"] = str(failure)[:500]
                    log.warning("action failed", automation=automation.name, error=str(failure))
                except TransientFailure as failure:
                    delivery.status = DeliveryStatus.FAILED
                    delivery.error_code = ErrorCode.ACTION_FAILED
                    delivery.error_message = str(failure)[:2000]
                    step.metadata["error"] = str(failure)[:500]
                    step.metadata["retry"] = True
                    retry = True
                    log.warning(
                        "action failed, will retry", automation=automation.name, error=str(failure)
                    )
                else:
                    delivery.status = DeliveryStatus.SENT
                    delivery.delivered_at = utc_now()
                    delivery.error_code = None
                    delivery.error_message = None
                    delivery.response = response
                    if messages is not None and response.get("command_id"):
                        command = await session.get(Command, uuid.UUID(str(response["command_id"])))
                        if command is not None:
                            messages.append(command_message(command))
    await tracer.finish()
    await session.commit()
    return retry


async def _delivery(
    session: AsyncSession,
    event: Event,
    alert: Alert | None,
    automation: Automation,
    index: int,
    action: dict[str, Any],
) -> ActionDelivery:
    existing = await session.scalar(
        select(ActionDelivery).where(
            ActionDelivery.event_id == event.id,
            ActionDelivery.automation_id == automation.id,
            ActionDelivery.action_index == index,
        )
    )
    if existing is not None:
        return existing
    target_id = action.get("target_id")
    delivery = ActionDelivery(
        event_id=event.id,
        alert_id=alert.id if alert else None,
        automation_id=automation.id,
        project_id=event.project_id,
        action_index=index,
        action_type=str(action.get("type") or "notify"),
        target_id=uuid.UUID(str(target_id)) if target_id else None,
        status=DeliveryStatus.QUEUED,
    )
    session.add(delivery)
    await session.flush()
    return delivery


def retry_error(event_id: str) -> ApplicationError:
    return ApplicationError(
        code=ErrorCode.ACTION_FAILED,
        message=f"one or more actions for event {event_id} failed transiently",
        component="automation",
        retryable=True,
    )


__all__ = [
    "PermanentFailure",
    "Skipped",
    "TransientFailure",
    "deliver_to_target",
    "handle_event",
    "matches",
    "post_webhook",
    "retry_error",
    "sign",
]
