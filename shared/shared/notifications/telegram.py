"""Telegram Bot API client (decision D43: one bot per installation). Chats register with a
code: the automation service polls the bot, a `/start <code>` links the chat to the target that
issued the code."""

from typing import Any

import httpx

from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("notifications.telegram")

API = "https://api.telegram.org"


class TelegramNotConfigured(RuntimeError):
    pass


def _url(method: str) -> str:
    token = get_settings().telegram_bot_token
    if not token:
        raise TelegramNotConfigured("TELEGRAM_BOT_TOKEN is not set")
    return f"{API}/bot{token}/{method}"


async def _call(method: str, http_timeout: float = 15.0, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        response = await client.post(_url(method), json=params)
    data = response.json()
    if not response.is_success or not data.get("ok"):
        raise httpx.HTTPStatusError(
            f"telegram {method} failed: {data.get('description', response.text)}",
            request=response.request,
            response=response,
        )
    return data["result"]


async def get_me() -> dict[str, Any]:
    result: dict[str, Any] = await _call("getMe")
    return result


async def send_message(chat_id: str, text: str) -> dict[str, Any]:
    result: dict[str, Any] = await _call(
        "sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True
    )
    return result


async def get_updates(offset: int | None, timeout_seconds: int = 25) -> list[dict[str, Any]]:
    """Long poll. The HTTP timeout is longer than the server-side wait on purpose."""
    params: dict[str, Any] = {"timeout": timeout_seconds, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    http_timeout = float(timeout_seconds + 10)
    result: list[dict[str, Any]] = await _call("getUpdates", http_timeout=http_timeout, **params)
    return result
