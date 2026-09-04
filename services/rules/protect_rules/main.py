"""Rules service: evaluates enabled rules against `position.created`, `measurement.created`
and `device.state_changed`, runs schedule rules every minute, and runs the system checks."""

import asyncio

from protect_rules.engine import (
    RuleCache,
    Scheduler,
    handle_measurements,
    handle_position,
    handle_state,
)
from protect_rules.retention import apply_trace_retention
from protect_rules.system_checks import run_system_checks
from shared.bus import Message, Topic
from shared.config import get_settings
from shared.control.commands import expire_commands
from shared.database import session_scope
from shared.logger import get_logger
from shared.worker import Worker

log = get_logger("rules")

TICK_SECONDS = 60
RETENTION_SECONDS = 86_400


def build_worker() -> Worker:
    worker = Worker("rules")
    cache = RuleCache()
    scheduler = Scheduler(worker.bus, cache)

    async def on_position(message: Message) -> None:
        await handle_position(worker.bus, cache, message.payload)

    async def on_measurements(message: Message) -> None:
        await handle_measurements(worker.bus, cache, message.payload)

    async def on_state(message: Message) -> None:
        await handle_state(worker.bus, cache, message.payload)

    async def ticker() -> None:
        settings = get_settings()
        last_system_check = 0.0
        last_retention = float("-inf")  # the first tick applies retention at once
        loop = asyncio.get_running_loop()
        while not worker.bus._stop.is_set():
            try:
                await scheduler.tick()
                async with session_scope() as session:
                    expired = await expire_commands(session)
                    await session.commit()
                for topic, payload in expired:
                    await worker.bus.publish(topic, payload)
                now = loop.time()
                if now - last_system_check >= settings.system_check_interval_seconds:
                    last_system_check = now
                    await run_system_checks(worker.bus)
                if now - last_retention >= RETENTION_SECONDS:
                    last_retention = now
                    async with session_scope() as session:
                        await apply_trace_retention(session)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.error("scheduler tick failed", exc_info=True)
            await worker.bus.heartbeat("rules")
            await asyncio.sleep(TICK_SECONDS)

    worker.subscribe(Topic.POSITION_CREATED, on_position)
    worker.subscribe(Topic.MEASUREMENT_CREATED, on_measurements)
    worker.subscribe(Topic.DEVICE_STATE_CHANGED, on_state)
    worker.background(ticker)
    worker.cache = cache  # type: ignore[attr-defined]
    worker.scheduler = scheduler  # type: ignore[attr-defined]
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
