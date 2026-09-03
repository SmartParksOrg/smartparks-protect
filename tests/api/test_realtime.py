"""WebSocket live updates: a position created on the bus reaches a connected project client."""

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from protect_api.main import app
from shared.bus import RedisStreamsBus, Topic
from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_project_client_receives_positions_of_its_project(client, db, bus):
    import httpx

    project = await create_project(db)
    other = await create_project(db)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    async with (
        httpx.AsyncClient(
            transport=ASGIWebSocketTransport(app), base_url="http://test"
        ) as ws_client,
        aconnect_ws(
            f"http://test/api/v1/ws/projects/{project.id}?token={viewer.token}", ws_client
        ) as ws,
    ):
        hello = json.loads(await ws.receive_text())
        assert hello["topic"] == "connected"
        await asyncio.sleep(0.3)  # the reader task starts tailing from now
        await bus.publish(
            Topic.POSITION_CREATED,
            {"position_id": 1, "project_id": str(other.id), "device_id": str(uuid.uuid4())},
        )
        await bus.publish(
            Topic.POSITION_CREATED,
            {"position_id": 2, "project_id": str(project.id), "device_id": str(uuid.uuid4())},
        )
        received = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=5))
        assert received["topic"] == Topic.POSITION_CREATED and received["position_id"] == 2


async def test_rejects_bad_token_and_foreign_project(client, db):
    import httpx
    from httpx_ws import WebSocketDisconnect

    project = await create_project(db)
    outsider = await actor(client, db)
    async with httpx.AsyncClient(
        transport=ASGIWebSocketTransport(app), base_url="http://test"
    ) as ws_client:
        with pytest.raises((WebSocketDisconnect, Exception)):
            async with aconnect_ws(
                f"http://test/api/v1/ws/projects/{project.id}?token=nope", ws_client
            ) as ws:
                await ws.receive_text()
        with pytest.raises((WebSocketDisconnect, Exception)):
            async with aconnect_ws(
                f"http://test/api/v1/ws/projects/{project.id}?token={outsider.token}", ws_client
            ) as ws:
                await ws.receive_text()
