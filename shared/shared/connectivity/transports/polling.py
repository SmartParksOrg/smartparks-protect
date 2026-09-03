"""Polling base: call `poll()` every interval, keep a cursor, one failure never stops the loop."""

import asyncio
from abc import ABC, abstractmethod

from shared.connectivity.base import Emit
from shared.logger import get_logger

log = get_logger("transport.polling")


class PollingConnector(ABC):
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds

    @abstractmethod
    async def poll(self, emit: Emit) -> None:
        """Fetch what is new since the last cursor and emit it."""

    async def run(self, emit: Emit) -> None:
        while True:
            try:
                await self.poll(emit)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.error("poll failed", connector=type(self).__name__, exc_info=True)
            await asyncio.sleep(self.interval_seconds)
