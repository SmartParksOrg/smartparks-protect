"""Helpers for HTTP push sources: bearer token check and body validation."""

import hashlib
import hmac
import secrets
from typing import Any

from shared.enums import ErrorCode
from shared.trace import ApplicationError


def new_webhook_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, token_hash: str | None) -> bool:
    if token_hash is None:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)


def bearer_token(headers: dict[str, str]) -> str | None:
    value = headers.get("authorization") or headers.get("Authorization") or ""
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


def require_object(body: Any, adapter: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="webhook body must be a JSON object",
            component=f"adapter.{adapter}",
            user_actionable=True,
        )
    return body
