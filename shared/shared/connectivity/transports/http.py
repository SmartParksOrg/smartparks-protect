"""Helpers for HTTP push sources: bearer token check and body validation."""

import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import unquote

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


def raw_query_params(query: str) -> dict[str, str]:
    """The query string as the platform sent it, percent-decoded but with `+` kept: a signed
    push (ThingPark's Token over `Time=...+02:00`) must be verified on the original text, and
    the usual parsers turn `+` into a space. The last value wins for a repeated key."""
    params: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        params[unquote(key)] = unquote(value)
    return params


def require_object(body: Any, adapter: str) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="webhook body must be a JSON object",
            component=f"adapter.{adapter}",
            user_actionable=True,
        )
    return body


def webhook_authenticated(
    headers: dict[str, str],
    query: dict[str, str],
    token_hash: str | None,
    *,
    token_in_query: bool,
) -> bool:
    """The bearer header matches, or, for adapters whose platform may carry the token in the
    URL (D78, D127), `?token=` matches; a stale header next to a right URL token still passes,
    since ChirpStack keeps sending an old `Authorization` header to every URL of an application
    after a rotation (decision D127)."""
    header = bearer_token(headers)
    if header is not None and token_matches(header, token_hash):
        return True
    if not token_in_query:
        return False
    in_query = query.get("token")
    return in_query is not None and token_matches(in_query, token_hash)
