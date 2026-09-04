"""Deliver a rendered message to a notification target. Used by the automation service for
actions and by the API for test messages, so both fail the same way."""

from typing import Any

import httpx

from shared.enums import NotificationChannel
from shared.models import NotificationTarget
from shared.notifications import telegram
from shared.notifications.email import send_email
from shared.notifications.render import Rendered


class TransientFailure(Exception):
    """Worth a retry: SMTP or HTTP trouble that may pass."""


class PermanentFailure(Exception):
    """Retrying will not help: bad configuration, unlinked chat, rejected request."""


class Skipped(Exception):
    """Nothing was sent on purpose: target disabled, mail logged by the development guard."""


async def deliver_to_target(target: NotificationTarget, rendered: Rendered) -> dict[str, Any]:
    """Raises Skipped, TransientFailure or PermanentFailure; returns a response summary."""
    if not target.enabled:
        raise Skipped("target disabled")
    if target.channel == NotificationChannel.EMAIL:
        if not target.address:
            raise PermanentFailure("email target without address")
        try:
            sent = await send_email(target.address, rendered.subject, rendered.text, rendered.html)
        except Exception as exc:
            raise TransientFailure(f"smtp: {type(exc).__name__}: {exc}") from exc
        if not sent:
            raise Skipped("mail logged, not sent (mail not configured or recipient not allowed)")
        return {"channel": "email", "to": target.address}
    if target.channel == NotificationChannel.TELEGRAM:
        if not target.telegram_chat_id:
            raise PermanentFailure("telegram target not linked yet; send /start <code> to the bot")
        try:
            result = await telegram.send_message(target.telegram_chat_id, rendered.text)
        except telegram.TelegramNotConfigured as exc:
            raise PermanentFailure(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (400, 403, 404):
                raise PermanentFailure(str(exc)) from exc
            raise TransientFailure(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TransientFailure(f"telegram: {type(exc).__name__}: {exc}") from exc
        return {"channel": "telegram", "message_id": result.get("message_id")}
    raise PermanentFailure(f"unknown channel {target.channel}")
