"""Automations: matching, email through the development guard, Telegram, signed webhooks,
freshness, idempotent re-delivery and the worker wiring."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from protect_automation import actions
from protect_automation.actions import handle_event, matches
from protect_automation.main import build_worker
from protect_automation.telegram_poller import handle_update
from shared.bus import Topic
from shared.enums import DeliveryStatus
from shared.models import ActionDelivery, Automation, Event, NotificationTarget
from shared.notifications import dispatch, telegram
from tests.automation.conftest import create_automation

pytestmark = pytest.mark.asyncio


def payload(world, alert=True):
    return {
        "event_id": str(world.event.id),
        "project_id": str(world.project.id),
        "alert_id": str(world.alert.id) if alert else None,
    }


async def _deliveries(db, event):
    return (
        await db.scalars(
            select(ActionDelivery)
            .where(ActionDelivery.event_id == event.id)
            .order_by(ActionDelivery.action_index)
        )
    ).all()


async def test_matching_filters():
    event = Event(event_type="BATTERY_LOW", severity="warning", context={"rule_id": "r1"})
    assert matches(
        Automation(
            event_types=[], min_severity="info", require_alert=False, entity_ids=[], rule_ids=[]
        ),
        event,
        None,
    )
    assert not matches(
        Automation(
            event_types=["GEOFENCE_EXIT"],
            min_severity="info",
            require_alert=False,
            entity_ids=[],
            rule_ids=[],
        ),
        event,
        None,
    )
    assert not matches(
        Automation(
            event_types=[], min_severity="critical", require_alert=False, entity_ids=[], rule_ids=[]
        ),
        event,
        None,
    )
    assert not matches(
        Automation(
            event_types=[], min_severity="info", require_alert=True, entity_ids=[], rule_ids=[]
        ),
        event,
        None,
    )
    assert matches(
        Automation(
            event_types=[], min_severity="info", require_alert=True, entity_ids=[], rule_ids=["r1"]
        ),
        event,
        "a1",
    )
    assert not matches(
        Automation(
            event_types=[], min_severity="info", require_alert=False, entity_ids=[], rule_ids=["r2"]
        ),
        event,
        None,
    )


async def test_email_is_logged_not_sent_in_development(db, world):
    """Mail is not configured in tests, so the guard logs and the delivery is skipped, not
    failed: nothing is wrong with the automation."""
    await create_automation(
        db, world.project, [{"type": "notify", "target_id": str(world.email.id)}]
    )
    retry = await handle_event(db, payload(world))
    assert retry is False
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.SKIPPED and "logged" in delivery.error_message
    assert delivery.attempts == 1 and delivery.trace_id is not None


async def test_telegram_sent_and_idempotent(db, world, monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_send(chat_id: str, text: str):
        sent.append((chat_id, text))
        return {"message_id": 7}

    monkeypatch.setattr(telegram, "send_message", fake_send)
    await create_automation(
        db, world.project, [{"type": "notify", "target_id": str(world.telegram.id)}]
    )
    assert await handle_event(db, payload(world)) is False
    assert len(sent) == 1 and sent[0][0] == "12345"
    assert "Rhino 14 battery at 3.1 V" in sent[0][1] and "rules/events?event=" in sent[0][1]
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.SENT and delivery.response == {
        "channel": "telegram",
        "message_id": 7,
    }
    # re-delivery of the bus message sends nothing twice
    assert await handle_event(db, payload(world)) is False
    assert len(sent) == 1


async def test_unlinked_telegram_target_fails_permanently(db, world):
    target = NotificationTarget(project_id=world.project.id, name="Not linked", channel="telegram")
    db.add(target)
    await db.commit()
    await create_automation(db, world.project, [{"type": "notify", "target_id": str(target.id)}])
    assert await handle_event(db, payload(world)) is False
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.FAILED and "not linked" in delivery.error_message


async def test_webhook_is_signed_and_transient_failures_retry(db, world, monkeypatch):
    calls: list[httpx.Request] = []
    status_codes = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(status_codes), json={"ok": True})

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(actions.httpx, "AsyncClient", client_factory)
    await create_automation(
        db,
        world.project,
        [{"type": "webhook", "url": "https://hooks.example.org/protect", "secret": "s3cret"}],
    )
    assert await handle_event(db, payload(world)) is True  # 503: retry wanted
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.FAILED and delivery.attempts == 1
    assert await handle_event(db, payload(world)) is False  # 200 on the retry
    await db.refresh(delivery)
    assert delivery.status == DeliveryStatus.SENT and delivery.attempts == 2
    assert delivery.response["status"] == 200
    request = calls[-1]
    body = json.loads(request.content)
    assert body["event"]["type"] == "BATTERY_LOW" and body["alert"]["id"] == str(world.alert.id)
    expected = "sha256=" + hmac.new(b"s3cret", request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-Protect-Signature"] == expected


async def test_stale_events_are_skipped(db, world):
    world.event.time = datetime.now(UTC) - timedelta(days=2)
    await db.commit()
    await create_automation(
        db,
        world.project,
        [{"type": "notify", "target_id": str(world.email.id)}],
        max_event_age_seconds=3600,
    )
    assert await handle_event(db, payload(world)) is False
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.SKIPPED and "old" in delivery.error_message
    assert delivery.attempts == 0


async def test_reserved_actions_fail_permanently(db, world):
    await create_automation(db, world.project, [{"type": "integration", "integration_id": "x"}])
    assert await handle_event(db, payload(world)) is False
    (delivery,) = await _deliveries(db, world.event)
    assert delivery.status == DeliveryStatus.FAILED and "later phase" in delivery.error_message


async def test_telegram_start_links_the_chat(db, world):
    target = NotificationTarget(
        project_id=world.project.id,
        name="Field team",
        channel="telegram",
        telegram_link_code="ABCD1234",
        telegram_link_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(target)
    await db.commit()
    reply = await handle_update(
        {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/start ABCD1234"}}
    )
    assert reply is not None and "Field team" in reply
    await db.refresh(target)
    assert target.telegram_chat_id == "999" and target.telegram_link_code is None
    assert "unknown or expired" in (
        await handle_update({"update_id": 2, "message": {"chat": {"id": 1}, "text": "/start NOPE"}})
        or ""
    )
    assert (
        await handle_update({"update_id": 3, "message": {"chat": {"id": 1}, "text": "hello"}})
        is None
    )


async def test_dispatch_skips_disabled_targets():
    target = NotificationTarget(name="x", channel="email", address="a@b.c", enabled=False)
    from shared.notifications.render import Rendered

    with pytest.raises(dispatch.Skipped):
        await dispatch.deliver_to_target(target, Rendered("s", "t", "h"))


async def test_worker_subscribes_to_events():
    worker = build_worker()
    assert [t for t, _ in worker._subscriptions] == [Topic.EVENT_CREATED]
