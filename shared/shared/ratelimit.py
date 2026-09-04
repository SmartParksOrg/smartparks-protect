"""Fixed-window rate limiting on Redis (decision D94): one INCR and EXPIRE per hit, so every
API replica shares the count. Redis being unreachable lets the request through with a warning:
the platform cannot serve without Redis anyway, and nginx keeps its own limits on deployed
servers (architecture 22)."""

import time
from dataclasses import dataclass

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("ratelimit")

PREFIX = "ratelimit"


@dataclass(frozen=True, slots=True)
class Verdict:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    def __init__(self, url: str | None = None) -> None:
        self._url = url or get_settings().redis_url
        self._redis: redis_async.Redis | None = None

    def _client(self) -> redis_async.Redis:
        if self._redis is None:
            self._redis = redis_async.from_url(
                self._url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
            )
        return self._redis

    async def hit(self, key: str, limit: int, window_seconds: int = 60) -> Verdict:
        """Count one hit on `key` in the current window and say whether it is within `limit`."""
        if limit <= 0:
            return Verdict(True, limit, 0, 0)
        window = int(time.time()) // window_seconds
        redis_key = f"{PREFIX}:{key}:{window}"
        try:
            pipe = self._client().pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds + 1)
            count, _ = await pipe.execute()
        except (RedisError, OSError) as exc:
            log.warning("rate limit store unavailable, letting the request through", error=str(exc))
            return Verdict(True, limit, limit, 0)
        count = int(count)
        retry_after = (window + 1) * window_seconds - int(time.time())
        return Verdict(count <= limit, limit, max(limit - count, 0), max(retry_after, 1))

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
