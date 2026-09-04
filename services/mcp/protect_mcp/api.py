"""The MCP server's only way to data: the Smart Parks Protect API, called with the client's own
bearer so RBAC, scopes and audit apply unchanged (architecture 27.1). Each request names the
tool in `X-Protect-MCP-Tool`, which the API writes to the audit log."""

from typing import Any

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError

from shared.config import get_settings

TOOL_HEADER = "X-Protect-MCP-Tool"
REQUEST_ID_HEADER = "X-Request-ID"


class ProtectApi:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=get_settings().api_internal_url, timeout=30.0
        )

    async def get(self, path: str, *, tool: str, params: dict[str, Any] | None = None) -> Any:
        """GET `path` under `/api/v1` as the authenticated client. Non-2xx answers become tool
        errors that carry the API's message and request id, so a user can find the trace."""
        access = get_access_token()
        if access is None:
            raise ToolError("Not authenticated")
        query = {k: v for k, v in (params or {}).items() if v is not None and v != []}
        response = await self._client.get(
            f"/api/v1{path}",
            params=query,
            headers={"Authorization": f"Bearer {access.token}", TOOL_HEADER: tool},
        )
        if response.status_code >= 400:
            raise ToolError(_describe(response))
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()


def _describe(response: httpx.Response) -> str:
    request_id = response.headers.get(REQUEST_ID_HEADER, "unknown")
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, list):
        detail = "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict))
    status = response.status_code
    if status == 403:
        hint = " (no access, or the scope was not granted)"
    elif status == 404:
        hint = " (check the id and the project)"
    else:
        hint = ""
    return f"API answered {status}{hint}: {detail}. Request id {request_id}."
