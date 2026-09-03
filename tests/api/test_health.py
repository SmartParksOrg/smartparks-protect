import pytest
from httpx import ASGITransport, AsyncClient

from protect_api.main import app
from shared.version import __version__

pytestmark = pytest.mark.asyncio


async def test_version_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/version")
    assert response.status_code == 200
    assert response.json()["version"] == __version__
    assert "X-Request-ID" in response.headers


async def test_inbound_request_id_is_kept():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/version", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.integration
async def test_health_reports_all_dependencies_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")
    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis", "minio"}
    assert all(check["status"] == "ok" for check in body["checks"].values())
