"""Websocket feed base with reconnect."""

import asyncio
from abc import ABC, abstractmethod

import websockets

from shared.connectivity.base import Emit
from shared.logger import get_logger

log = get_logger("transport.websocket")


class WebsocketConnector(ABC):
    def __init__(self, url: str, *, reconnect_seconds: float = 5.0) -> None:
        self.url = url
        self.reconnect_seconds = reconnect_seconds

    @abstractmethod
    async def on_frame(self, frame: str | bytes, emit: Emit) -> None: ...

    async def run(self, emit: Emit) -> None:
        while True:
            try:
                async with websockets.connect(self.url) as connection:
                    log.info("websocket connected", url=self.url)
                    async for frame in connection:
                        await self.on_frame(frame, emit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("websocket lost, reconnecting", url=self.url, error=str(exc))
                await asyncio.sleep(self.reconnect_seconds)
