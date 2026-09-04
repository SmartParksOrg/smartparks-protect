"""Live updates over WebSocket (architecture 11 and 13.7).

One background reader per API process tails the domain streams with plain `XREAD` from the
moment the API started (no consumer group: every API instance sees everything and fans out to
its own clients). Clients connect to `/api/v1/ws/projects/{project_id}?token=...` and receive
compact JSON messages for positions, device state changes and events of that project.

Browsers cannot set headers on a WebSocket, so the JWT travels as a query parameter and is
checked the same way as a bearer token.
"""

import asyncio
import contextlib
import json
import uuid
from collections import defaultdict
from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from protect_api.auth.users import get_jwt_strategy, get_user_manager
from protect_api.bus import get_bus
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.logger import get_logger
from shared.models import ProjectMembership, User

log = get_logger("api.realtime")

router = APIRouter(tags=["realtime"])

LIVE_TOPICS = (
    Topic.POSITION_CREATED,
    Topic.DEVICE_STATE_CHANGED,
    Topic.EVENT_CREATED,
    Topic.ALERT_CREATED,
    Topic.COMMAND_UPDATED,
)


class Broadcaster:
    def __init__(self) -> None:
        self.clients: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self.device_projects: dict[str, str | None] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def add(self, project_id: uuid.UUID, socket: WebSocket) -> None:
        self.clients[project_id].add(socket)

    def remove(self, project_id: uuid.UUID, socket: WebSocket) -> None:
        self.clients[project_id].discard(socket)

    @property
    def connected(self) -> int:
        return sum(len(s) for s in self.clients.values())

    async def _reader(self) -> None:
        bus = get_bus()
        positions = dict.fromkeys(LIVE_TOPICS, "$")
        while True:
            try:
                if not self.connected:
                    await asyncio.sleep(0.5)
                    # keep only new messages while nobody listens
                    positions = dict.fromkeys(LIVE_TOPICS, "$")
                    continue
                response = cast(
                    "list[tuple[str, list[tuple[str, dict[str, str]]]]]",
                    await bus.redis.xread(cast("dict[Any, Any]", positions), count=100, block=1000),
                )
                for topic, entries in response:
                    for message_id, fields in entries:
                        positions[topic] = message_id
                        await self._dispatch(Message.from_fields(topic, message_id, fields))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.error("realtime reader failed, retrying", exc_info=True)
                await asyncio.sleep(2)

    async def _dispatch(self, message: Message) -> None:
        project_id = message.payload.get("project_id")
        if project_id is None:
            return
        try:
            key = uuid.UUID(str(project_id))
        except ValueError:
            return
        sockets = self.clients.get(key)
        if not sockets:
            return
        text = json.dumps(
            {
                "topic": message.topic,
                "published_at": message.published_at.isoformat(),
                **message.payload,
            },
            default=str,
        )
        for socket in list(sockets):
            try:
                await socket.send_text(text)
            except Exception:
                sockets.discard(socket)


broadcaster = Broadcaster()


async def _authenticate(token: str) -> User | None:
    from protect_api.auth.users import get_user_db
    from shared.database import get_session_factory

    async with get_session_factory()() as session:
        user_db_gen = get_user_db(session)
        user_db = await user_db_gen.__anext__()
        manager_gen = get_user_manager(user_db)
        manager = await manager_gen.__anext__()
        user = await get_jwt_strategy().read_token(token, manager)
        return user if user is not None and user.is_active else None


async def _allowed(user: User, project_id: uuid.UUID) -> bool:
    if user.is_superuser:
        return True
    async with session_scope() as session:
        role = await session.scalar(
            select(ProjectMembership.role).where(
                ProjectMembership.user_id == user.id, ProjectMembership.project_id == project_id
            )
        )
    return role is not None


@router.websocket("/ws/projects/{project_id}")
async def project_stream(socket: WebSocket, project_id: uuid.UUID, token: str) -> None:
    user = await _authenticate(token)
    if user is None:
        await socket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return
    if not await _allowed(user, project_id):
        await socket.close(code=status.WS_1008_POLICY_VIOLATION, reason="no access to project")
        return
    await socket.accept()
    broadcaster.add(project_id, socket)
    broadcaster.start()
    await socket.send_text(json.dumps({"topic": "connected", "project_id": str(project_id)}))
    try:
        while True:
            # clients may send pings; anything else is ignored
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.remove(project_id, socket)


def payload_for_client(message: Message) -> dict[str, Any]:
    return {"topic": message.topic, **message.payload}
