"""Connection state per data source, kept in Redis by the ingest service and read by the API
(Server admin, Data sources, Status): whether a streaming channel (MQTT, websocket) is
connected, reconnecting, or stopped, with the last error. Webhook and API channels have no
process to watch; their state comes from the last message received and the last API answer."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("connectivity.state")
CONNECTOR_PREFIX = "connector:"
API_TEST_PREFIX = "datasource-api-test:"
STATE_TTL_SECONDS = 7 * 24 * 3600

_client: redis_async.Redis | None = None


def _redis() -> redis_async.Redis:
    global _client
    if _client is None:
        _client = redis_async.from_url(
            get_settings().redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
    return _client


async def _set(key: str, value: dict[str, Any]) -> None:
    try:
        await _redis().set(key, json.dumps(value), ex=STATE_TTL_SECONDS)
    except (RedisError, OSError) as exc:
        log.warning("connection state not stored", key=key, error=str(exc))


async def _get(key: str) -> dict[str, Any] | None:
    try:
        raw = await _redis().get(key)
    except (RedisError, OSError) as exc:
        log.warning("connection state not read", key=key, error=str(exc))
        return None
    if not raw:
        return None
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data


async def report_connector(
    source_id: uuid.UUID | str | None, status: str, detail: str | None = None
) -> None:
    """`connected`, `reconnecting`, `stopped` or `error` for the streaming channel of a source."""
    if source_id is None:
        return
    await _set(
        f"{CONNECTOR_PREFIX}{source_id}",
        {"status": status, "detail": detail, "at": datetime.now(UTC).isoformat()},
    )


async def read_connector(source_id: uuid.UUID | str) -> dict[str, Any] | None:
    return await _get(f"{CONNECTOR_PREFIX}{source_id}")


async def report_api_test(source_id: uuid.UUID | str, ok: bool, detail: str) -> None:
    await _set(
        f"{API_TEST_PREFIX}{source_id}",
        {"ok": ok, "detail": detail, "at": datetime.now(UTC).isoformat()},
    )


async def read_api_test(source_id: uuid.UUID | str) -> dict[str, Any] | None:
    return await _get(f"{API_TEST_PREFIX}{source_id}")
