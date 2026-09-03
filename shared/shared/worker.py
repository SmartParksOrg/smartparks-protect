"""Base for long-running workers: one consumer group per worker, heartbeat, clean shutdown."""

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from shared.bus import Handler, RedisStreamsBus
from shared.config import get_settings
from shared.logger import configure_logging, get_logger

log = get_logger("worker")


class Worker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.bus = RedisStreamsBus()
        self._subscriptions: list[tuple[str, Handler]] = []
        self._background: list[Callable[[], Awaitable[None]]] = []

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscriptions.append((topic, handler))

    def background(self, coroutine_factory: Callable[[], Awaitable[None]]) -> None:
        """A long-running task next to the subscriptions (connectors, schedulers)."""
        self._background.append(coroutine_factory)

    async def run(self) -> None:
        settings = get_settings()
        configure_logging(self.name, level=settings.log_level, log_format=settings.log_format)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.bus.stop)
        log.info("worker starting", worker=self.name, topics=[t for t, _ in self._subscriptions])
        tasks: list[asyncio.Task[Any]] = [
            asyncio.create_task(
                self.bus.consume(topic, group=self.name, consumer=self.name, handler=handler)
            )
            for topic, handler in self._subscriptions
        ]
        tasks += [asyncio.create_task(_await(factory())) for factory in self._background]
        if not tasks:
            tasks.append(asyncio.create_task(self._idle()))
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.bus.close()
            log.info("worker stopped", worker=self.name)

    async def _idle(self) -> None:
        while not self.bus._stop.is_set():
            await self.bus.heartbeat(self.name)
            await asyncio.sleep(30)


async def _await(awaitable: Awaitable[None]) -> None:
    await awaitable
