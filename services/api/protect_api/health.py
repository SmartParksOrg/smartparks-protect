"""Health endpoint.

`GET /api/health` checks the three infrastructure dependencies and reports each one. It returns 200
when all are reachable and 503 otherwise. This is the one place where exceptions are caught and
reported instead of raised, because the purpose of the endpoint is to describe failures.
"""

import asyncio
import time
from typing import Literal

import httpx
import redis.asyncio as redis_async
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from shared.config import get_settings
from shared.database import get_engine
from shared.version import __version__

router = APIRouter(prefix="/api", tags=["health"])

CHECK_TIMEOUT_SECONDS = 3.0


class DependencyStatus(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: int
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, DependencyStatus]


async def _check_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client = redis_async.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_minio() -> None:
    url = f"{get_settings().minio_url}/minio/health/live"
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()


async def _run_check(name: str, check: asyncio.Future[None]) -> tuple[str, DependencyStatus]:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check, timeout=CHECK_TIMEOUT_SECONDS)
        result = DependencyStatus(status="ok", latency_ms=_elapsed_ms(started))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        result = DependencyStatus(status="error", latency_ms=_elapsed_ms(started), error=error)
    return name, result


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    results = await asyncio.gather(
        _run_check("database", asyncio.ensure_future(_check_database())),
        _run_check("redis", asyncio.ensure_future(_check_redis())),
        _run_check("minio", asyncio.ensure_future(_check_minio())),
    )
    checks = dict(results)
    healthy = all(check.status == "ok" for check in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded", version=__version__, checks=checks
    )
