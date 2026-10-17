"""Protect Go signed in from the Offload page (decision D333). A signed-in person's browser asks
for a one-time code; the `protect-go://connect` link carries it to the installed app, which
exchanges it for a token of its own that lasts weeks, so nobody types the server address or the
password on the laptop. The code lives in Redis for two minutes under its SHA-256, is read once
(`GETDEL`), and both ends are audited. The exchange is throttled with the login (`ratelimit`)."""

import hashlib
import secrets
import uuid

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.schemas import TokenResponse
from protect_api.auth.users import PasswordChangeAwareJWTStrategy, current_active_user
from shared.config import get_settings
from shared.database import get_session
from shared.models import User
from shared.oauth import mcp_resource_url

router = APIRouter()

PREFIX = "go-handoff"


class HandoffCode(BaseModel):
    code: str
    expires_in: int


class HandoffExchange(BaseModel):
    code: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def _key(code: str) -> str:
    return f"{PREFIX}:{hashlib.sha256(code.encode()).hexdigest()}"


def _redis() -> redis_async.Redis:
    return redis_async.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
    )


def go_token_strategy() -> PasswordChangeAwareJWTStrategy:
    """The token Protect Go keeps: the same strategy and audience as a login, a longer life,
    still cut short by a password change (the strategy checks `iat`)."""
    settings = get_settings()
    return PasswordChangeAwareJWTStrategy(
        secret=settings.jwt_secret,
        lifetime_seconds=settings.go_token_lifetime_days * 86400,
        token_audience=["fastapi-users:auth", mcp_resource_url()],
    )


@router.post("/go-handoff", response_model=HandoffCode)
async def issue_handoff_code(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> HandoffCode:
    """A one-time code for the signed-in person, for the `protect-go://connect` link."""
    settings = get_settings()
    code = secrets.token_urlsafe(32)
    client = _redis()
    try:
        await client.set(_key(code), str(user.id), ex=settings.go_handoff_ttl_seconds, nx=True)
    finally:
        await client.aclose()
    await record_audit(
        session, user=user, action="go_handoff.issue", object_type="user", object_id=str(user.id)
    )
    await session.commit()
    return HandoffCode(code=code, expires_in=settings.go_handoff_ttl_seconds)


@router.post("/go-handoff/exchange", response_model=TokenResponse)
async def exchange_handoff_code(
    body: HandoffExchange,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """The code for Protect Go's token; a code is good once, for two minutes, for the account it
    was issued to while that account is active."""
    client = _redis()
    try:
        owner = await client.getdel(_key(body.code))
    finally:
        await client.aclose()
    if not owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or used code")
    user = await session.get(User, uuid.UUID(str(owner)))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or used code")
    token = await go_token_strategy().write_token(user)
    await record_audit(
        session,
        user=user,
        action="go_handoff.exchange",
        object_type="user",
        object_id=str(user.id),
        details={"client": request.client.host if request.client else None},
    )
    await session.commit()
    return TokenResponse(access_token=token)
