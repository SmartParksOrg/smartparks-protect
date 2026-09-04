"""Integration service: durable outbound deliveries (architecture 18). Consumes position,
event and measurement messages into delivery rows, runs the delivery loop on the retry
schedule, and executes backfill requests."""

import asyncio

from protect_integration.worker import (
    IntegrationCache,
    delivery_loop,
    handle_backfill,
    handle_message,
)
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.logger import get_logger
from shared.worker import Worker

log = get_logger("integration")


def build_worker() -> Worker:
    worker = Worker("integration")
    cache = IntegrationCache()

    async def on_object(message: Message) -> None:
        async with session_scope() as session:
            await handle_message(session, cache, message)

    async def on_backfill(message: Message) -> None:
        async with session_scope() as session:
            await handle_backfill(session, message.payload)

    worker.subscribe(Topic.POSITION_CREATED, on_object)
    worker.subscribe(Topic.EVENT_CREATED, on_object)
    worker.subscribe(Topic.MEASUREMENT_CREATED, on_object)
    worker.subscribe(Topic.INTEGRATION_BACKFILL_REQUESTED, on_backfill)
    worker.background(lambda: delivery_loop(worker.bus))
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
