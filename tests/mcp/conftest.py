"""The MCP tests run the MCP ASGI app with the real API app behind it (in process, over
`httpx.ASGITransport`), against the test database."""

from tests.api.conftest import client, db  # noqa: F401  (fixtures re-exported for tests/mcp)
