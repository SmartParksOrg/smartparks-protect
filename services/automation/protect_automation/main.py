"""Automation service: consumes `event.created`, runs the matching automations' actions and
delivers notifications; polls the Telegram bot for chat registrations."""

import asyncio
from typing import Any

from protect_automation.actions import handle_event, retry_error
from protect_automation.telegram_poller import poll_forever
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.logger import get_logger
from shared.worker import Worker

log = get_logger("automation")


def build_worker() -> Worker:
    worker = Worker("automation")

    async def on_event(message: Message) -> None:
        outgoing: list[tuple[str, dict[str, Any]]] = []
        async with session_scope() as session:
            retry = await handle_event(session, message.payload, outgoing)
        for topic, payload in outgoing:
            await worker.bus.publish(topic, payload)
        if retry:
            raise retry_error(str(message.payload.get("event_id")))

    worker.subscribe(Topic.EVENT_CREATED, on_event)
    worker.background(lambda: poll_forever(worker.bus))
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
