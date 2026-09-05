"""Websocket feed base with reconnect."""

import asyncio
import uuid
from abc import ABC, abstractmethod

import websockets

from shared.connectivity.base import Emit
from shared.connectivity.state import report_connector
from shared.logger import get_logger

log = get_logger("transport.websocket")


class WebsocketConnector(ABC):
    def __init__(
        self, url: str, *, reconnect_seconds: float = 5.0, source_id: uuid.UUID | None = None
    ) -> None:
        self.url = url
        self.reconnect_seconds = reconnect_seconds
        self.source_id = source_id

    @abstractmethod
    async def on_frame(self, frame: str | bytes, emit: Emit) -> None: ...

    async def run(self, emit: Emit) -> None:
        while True:
            try:
                async with websockets.connect(self.url) as connection:
                    log.info("websocket connected", url=self.url)
                    await report_connector(self.source_id, "connected", "websocket connected")
                    async for frame in connection:
                        await self.on_frame(frame, emit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("websocket lost, reconnecting", url=self.url, error=str(exc))
                await report_connector(self.source_id, "reconnecting", str(exc))
                await asyncio.sleep(self.reconnect_seconds)
