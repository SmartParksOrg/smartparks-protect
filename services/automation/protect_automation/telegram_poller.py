"""Links Telegram chats to notification targets. The bot is polled with `getUpdates`; a
`/start <code>` message links the chat to the target that issued the code (decision D43). The
update offset lives in Redis so a restart does not replay old messages."""

import asyncio
from typing import Any

import httpx
from sqlalchemy import select

from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import session_scope
from shared.logger import get_logger
from shared.models import NotificationTarget, Project
from shared.notifications import telegram
from shared.timeutil import utc_now

log = get_logger("automation.telegram")

OFFSET_KEY = "telegram:update_offset"
HELP = (
    "This is the Smart Parks Protect bot. To receive alerts here, create a Telegram target on "
    "the Notifications page and send the code it shows as: /start <code>"
)


async def handle_update(update: dict[str, Any]) -> str | None:
    """Returns the reply text for a message, None when there is nothing to say."""
    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None or not text.startswith("/start"):
        return None
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        return HELP
    async with session_scope() as session:
        target = await session.scalar(
            select(NotificationTarget).where(NotificationTarget.telegram_link_code == code)
        )
        if target is None or (
            target.telegram_link_expires_at is not None
            and target.telegram_link_expires_at < utc_now()
        ):
            return "That code is unknown or expired. Create a new one on the Notifications page."
        target.telegram_chat_id = str(chat_id)
        target.telegram_link_code = None
        target.telegram_link_expires_at = None
        target.updated_at = utc_now()
        project = await session.get(Project, target.project_id) if target.project_id else None
        await session.commit()
        where = f"project {project.name}" if project else "server alerts"
        log.info("telegram chat linked", target=target.name, chat_id=str(chat_id))
        return (
            f"Linked this chat to the target '{target.name}' for {where}. Alerts will arrive here."
        )


async def poll_forever(bus: RedisStreamsBus) -> None:
    settings = get_settings()
    if not settings.telegram_configured:
        log.info("telegram not configured, poller idle")
        return
    while not bus._stop.is_set():
        try:
            raw = await bus.redis.get(OFFSET_KEY)
            offset = int(raw) if raw else None
            updates = await telegram.get_updates(offset)
            for update in updates:
                reply = await handle_update(update)
                chat_id = ((update.get("message") or {}).get("chat") or {}).get("id")
                if reply and chat_id is not None:
                    await telegram.send_message(str(chat_id), reply)
                await bus.redis.set(OFFSET_KEY, str(int(update["update_id"]) + 1))
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, telegram.TelegramNotConfigured) as exc:
            log.warning("telegram poll failed", error=str(exc))
            await asyncio.sleep(10)
        except Exception:
            log.error("telegram poller crashed, continuing", exc_info=True)
            await asyncio.sleep(10)
