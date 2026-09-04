"""Application-level throttling of the calls an unauthenticated party can make (decision D94):
login, password reset, registration and OAuth token exchange per client address, webhook posts
per data source, AI actions per client address. Holds without nginx; nginx keeps its own,
usually stricter, limits on deployed servers. Answers 429 with `Retry-After`."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared.config import Settings, get_settings
from shared.ratelimit import RateLimiter


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    methods: frozenset[str]
    pattern: re.Pattern[str]
    limit: Callable[[Settings], int]
    per: str  # "client" or "path"


RULES: tuple[Rule, ...] = (
    Rule(
        "auth",
        frozenset({"POST"}),
        re.compile(r"^/api/v1/(auth/(login|register|forgot-password|reset-password)|oauth/token)$"),
        lambda s: s.rate_limit_auth_per_minute,
        "client",
    ),
    Rule(
        "ingest",
        frozenset({"POST", "PUT"}),
        re.compile(r"^/api/v1/ingest/"),
        lambda s: s.rate_limit_ingest_per_minute,
        "path",
    ),
    Rule(
        "actions",
        frozenset({"POST"}),
        re.compile(r"^/api/v1/mcp/actions"),
        lambda s: s.rate_limit_actions_per_minute,
        "client",
    ),
)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return str(value.decode("latin-1"))
    return None


def client_address(scope: Scope) -> str:
    """The address nginx reports in `X-Real-IP` (set from its own view of the peer, so a client
    cannot forge it), else the socket peer."""
    real_ip = _header(scope, b"x-real-ip")
    if real_ip:
        return real_ip.strip()
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def match(method: str, path: str) -> Rule | None:
    for rule in RULES:
        if method in rule.methods and rule.pattern.match(path):
            return rule
    return None


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limiter: RateLimiter | None = None) -> None:
        self.app = app
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        if scope["type"] != "http" or not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        method, path = str(scope["method"]), str(scope["path"])
        rule = match(method, path)
        if rule is None:
            await self.app(scope, receive, send)
            return
        subject = path if rule.per == "path" else client_address(scope)
        verdict = await self.limiter.hit(f"{rule.name}:{subject}", rule.limit(settings))
        if not verdict.allowed:
            body = json.dumps(
                {"detail": f"Too many requests; try again in {verdict.retry_after} seconds"}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", str(verdict.retry_after).encode()),
                        (b"x-ratelimit-limit", str(verdict.limit).encode()),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-ratelimit-limit", str(verdict.limit).encode()))
                headers.append((b"x-ratelimit-remaining", str(verdict.remaining).encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, with_headers)
