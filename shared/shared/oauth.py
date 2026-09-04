"""Scopes and access tokens for AI clients (architecture 27.5, decisions D68 to D71).

The API is the OAuth 2.1 authorization server and the MCP service is the resource server. An
access token is a JWT signed with `JWT_SECRET`, like a session token, but with the MCP server
URL as audience, the granted scopes and the client id as claims. The MCP service verifies it
locally and calls the API with the same bearer; the API accepts this audience only for reads
within the granted scopes (`protect_api.oauth.middleware`). Phase 9 exposes read scopes only.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt

from shared.config import get_settings

ALGORITHM = "HS256"
OFFLINE_ACCESS = "offline_access"


class Scope(StrEnum):
    PROJECTS_READ = "projects:read"
    ENTITIES_READ = "entities:read"
    DEVICES_READ = "devices:read"
    POSITIONS_READ = "positions:read"
    MEASUREMENTS_READ = "measurements:read"
    EVENTS_READ = "events:read"
    TRACES_READ = "traces:read"
    EVENTS_WRITE = "events:write"
    ALERTS_WRITE = "alerts:write"
    DEVICES_CONTROL = "devices:control"


WRITE_SCOPES: tuple[str, ...] = (Scope.EVENTS_WRITE, Scope.ALERTS_WRITE, Scope.DEVICES_CONTROL)
READ_SCOPES: tuple[str, ...] = tuple(s.value for s in Scope if s not in WRITE_SCOPES)
ALL_SCOPES: tuple[str, ...] = tuple(scope.value for scope in Scope)

SCOPE_DESCRIPTIONS: dict[str, str] = {
    Scope.PROJECTS_READ: "See which projects you belong to and their settings",
    Scope.ENTITIES_READ: "Read entities (animals, vehicles, gates, sensors) and their types",
    Scope.DEVICES_READ: "Read devices, their assignments and external identities",
    Scope.POSITIONS_READ: "Read positions, current state and tracks",
    Scope.MEASUREMENTS_READ: "Read measurements and aggregates",
    Scope.EVENTS_READ: "Read events and alerts",
    Scope.TRACES_READ: "Read processing traces and raw source events",
    Scope.EVENTS_WRITE: "Create events (reports) in your projects, subject to the AI action policy",
    Scope.ALERTS_WRITE: "Acknowledge alerts, subject to the AI action policy",
    Scope.DEVICES_CONTROL: "Ask a device for its status or position, subject to the AI action "
    "policy and your device control permission",
    OFFLINE_ACCESS: "Stay connected without signing in again (refresh token)",
}


def issuer_url() -> str:
    return get_settings().public_url.rstrip("/")


def mcp_resource_url() -> str:
    """Canonical URL of the MCP server, the audience of every access token (RFC 8707)."""
    settings = get_settings()
    if settings.mcp_public_url:
        return settings.mcp_public_url.rstrip("/")
    return f"{issuer_url()}/mcp"


@dataclass(frozen=True, slots=True)
class MCPAccessToken:
    user_id: uuid.UUID
    client_id: str
    scopes: list[str]
    issued_at: datetime
    expires_at: datetime
    jti: str
    resource: str


def mint_access_token(
    user_id: uuid.UUID, client_id: str, scopes: list[str], lifetime_seconds: int | None = None
) -> tuple[str, int]:
    """A signed access token and its lifetime in seconds."""
    settings = get_settings()
    lifetime = lifetime_seconds or settings.jwt_lifetime_seconds
    now = datetime.now(UTC).replace(microsecond=0)
    claims = {
        "iss": issuer_url(),
        "aud": mcp_resource_url(),
        "sub": str(user_id),
        "client_id": client_id,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": now + timedelta(seconds=lifetime),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM), lifetime


def decode_access_token(token: str) -> MCPAccessToken | None:
    """The claims of a valid MCP access token, or None for any other bearer (a session token
    has another audience and fails here on purpose)."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[ALGORITHM],
            audience=mcp_resource_url(),
            issuer=issuer_url(),
            options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    client_id = claims.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        return None
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError:
        return None
    scope = claims.get("scope", "")
    return MCPAccessToken(
        user_id=user_id,
        client_id=client_id,
        scopes=[s for s in str(scope).split(" ") if s],
        issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
        expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
        jti=str(claims["jti"]),
        resource=mcp_resource_url(),
    )
