"""Access tokens of AI clients on the API: read-only within the granted scopes, one audit row
per request with the tool that made it (architecture 27.6, 27.7 and 27.11).

The middleware runs before FastAPI-Users sees the bearer. A token with the MCP audience that
fails the policy gets a 403 with a `WWW-Authenticate` challenge; one that passes is stored in
`mcp_access_var`, which the JWT strategy requires before it accepts that audience.
"""

import json
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from protect_api.oauth.scopes import authorize_request
from shared.database import session_scope
from shared.enums import ActorType
from shared.logger import request_id_var
from shared.models import AuditLog
from shared.oauth import MCPAccessToken, decode_access_token

mcp_access_var: ContextVar[MCPAccessToken | None] = ContextVar("mcp_access", default=None)

TOOL_HEADER = b"x-protect-mcp-tool"
_PROJECT_PATH = re.compile(r"^/api/v1/projects/([0-9a-f-]{36})(/|$)")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return str(bytes(value).decode("latin-1"))
    return None


class MCPAccessMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authorization = _header(scope, b"authorization") or ""
        access = None
        if authorization.lower().startswith("bearer "):
            access = decode_access_token(authorization[7:])
        if access is None:
            await self.app(scope, receive, send)
            return
        method = str(scope["method"])
        path = str(scope["path"])
        allowed, missing = authorize_request(method, path, access.scopes)
        if not allowed:
            await _refuse(send, method, path, missing)
            return
        status_code = 0

        async def capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        token = mcp_access_var.set(access)
        try:
            await self.app(scope, receive, capture)
        finally:
            mcp_access_var.reset(token)
        await _audit(access, scope, method, path, status_code)


async def _refuse(send: Send, method: str, path: str, missing: str | None) -> None:
    if missing:
        detail = f"Scope {missing} is required for {method} {path}"
        challenge = f'Bearer error="insufficient_scope", scope="{missing}"'
    else:
        detail = f"{method} {path} is not available to AI clients"
        challenge = 'Bearer error="insufficient_scope"'
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", challenge.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _audit(
    access: MCPAccessToken, scope: Scope, method: str, path: str, status_code: int
) -> None:
    match = _PROJECT_PATH.match(path)
    project_id = uuid.UUID(match.group(1)) if match else None
    query = scope.get("query_string", b"").decode("latin-1")
    async with session_scope() as session:
        session.add(
            AuditLog(
                actor_type=ActorType.MCP,
                user_id=access.user_id,
                project_id=project_id,
                action="mcp.request",
                object_type="api",
                object_id=path[:128],
                details={
                    "method": method,
                    "path": path,
                    "query": query[:1000],
                    "status": status_code,
                    "client_id": access.client_id,
                    "tool": _header(scope, TOOL_HEADER),
                    "scopes": access.scopes,
                },
                request_id=request_id_var.get(),
            )
        )
        await session.commit()
