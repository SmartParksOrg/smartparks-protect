"""Application-level throttling (decision D94): the login window per client address, the
webhook window per data source, 429 with Retry-After, and the headers on allowed calls."""

import pytest

from protect_api import ratelimit
from shared.config import get_settings
from shared.ratelimit import RateLimiter

pytestmark = pytest.mark.asyncio


async def test_limiter_counts_per_window():
    limiter = RateLimiter()
    key = f"test:{id(limiter)}"
    verdicts = [await limiter.hit(key, 3, 60) for _ in range(4)]
    assert [v.allowed for v in verdicts] == [True, True, True, False]
    assert verdicts[0].remaining == 2 and verdicts[-1].retry_after >= 1
    assert (await limiter.hit(key, 0, 60)).allowed  # a zero limit means no limit
    await limiter.close()


async def test_login_is_throttled_per_address(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 2)
    headers = {"X-Real-IP": "203.0.113.7"}
    for expected in (2, 1, 0):
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "nobody@example.org", "password": "wrong"},
            headers=headers,
        )
        if expected:
            assert response.status_code == 400
            assert response.headers["x-ratelimit-remaining"] == str(expected - 1)
        else:
            assert response.status_code == 429
            assert int(response.headers["retry-after"]) >= 1
            assert "Too many requests" in response.json()["detail"]
    other = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@example.org", "password": "wrong"},
        headers={"X-Real-IP": "203.0.113.8"},
    )
    assert other.status_code == 400  # another address has its own window


def test_rules_cover_the_unauthenticated_surface():
    assert ratelimit.match("POST", "/api/v1/auth/login").name == "auth"
    assert ratelimit.match("POST", "/api/v1/oauth/token").name == "auth"
    assert ratelimit.match("POST", "/api/v1/auth/forgot-password").name == "auth"
    assert ratelimit.match("POST", "/api/v1/ingest/http/abc").name == "ingest"
    assert ratelimit.match("POST", "/api/v1/mcp/actions").name == "actions"
    assert ratelimit.match("GET", "/api/v1/auth/login") is None
    assert ratelimit.match("GET", "/api/v1/projects") is None
    scope = {"headers": [(b"x-real-ip", b"198.51.100.4")], "client": ("127.0.0.1", 1)}
    assert ratelimit.client_address(scope) == "198.51.100.4"
    assert ratelimit.client_address({"headers": [], "client": ("127.0.0.1", 1)}) == "127.0.0.1"
