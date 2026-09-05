"""Ingest service: runs the event connector of every enabled data source whose adapter has one
(MQTT, polling, websocket). Push sources arrive through the API. Data sources are re-read every
minute so a new or changed source starts without a restart. Every received message becomes a
source event and a bus message.
"""

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select

from shared.bus import RedisStreamsBus
from shared.connectivity.base import InboundMessage
from shared.connectivity.channels import channel_enabled, stream_channel_key
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.state import report_connector
from shared.database import session_scope
from shared.ingest import commit_and_publish, data_source_context, store_inbound
from shared.logger import get_logger
from shared.models import DataSource
from shared.worker import Worker

log = get_logger("ingest")

RELOAD_SECONDS = 60
RESTART_SECONDS = 10


class ConnectorRunner:
    def __init__(self, bus: RedisStreamsBus) -> None:
        self.bus = bus
        self.tasks: dict[uuid.UUID, tuple[datetime, asyncio.Task[None]]] = {}

    async def run(self) -> None:
        try:
            while True:
                await self.reconcile()
                await self.bus.heartbeat("ingest")
                await asyncio.sleep(RELOAD_SECONDS)
        finally:
            for _, task in self.tasks.values():
                task.cancel()

    async def reconcile(self) -> None:
        async with session_scope() as session:
            sources = (
                await session.scalars(select(DataSource).where(DataSource.enabled.is_(True)))
            ).all()
            wanted: dict[uuid.UUID, DataSource] = {}
            for source in sources:
                adapter = ADAPTERS.get(source.adapter_key)
                if adapter is None:
                    log.warning(
                        "data source has unknown adapter",
                        data_source=source.name,
                        adapter=source.adapter_key,
                    )
                    continue
                if not channel_enabled(source.channels, stream_channel_key(source.adapter_key)):
                    continue  # the source's streaming channel is switched off
                if adapter.event_connector(data_source_context(source)) is not None:
                    wanted[source.id] = source
            session.expunge_all()
        for source_id, (updated_at, task) in list(self.tasks.items()):
            current = wanted.get(source_id)
            if current is None or current.updated_at != updated_at or task.done():
                task.cancel()
                del self.tasks[source_id]
                log.info("connector stopped", data_source_id=str(source_id))
        for source_id, source in wanted.items():
            if source_id not in self.tasks:
                self.tasks[source_id] = (
                    source.updated_at,
                    asyncio.create_task(self.run_connector(source)),
                )
                log.info("connector started", data_source=source.name, adapter=source.adapter_key)

    async def run_connector(self, source: DataSource) -> None:
        adapter = ADAPTERS[source.adapter_key]
        context = data_source_context(source)

        async def emit(message: InboundMessage) -> None:
            async with session_scope() as session:
                stored = await store_inbound(session, source, message)
                await commit_and_publish(session, self.bus, [stored])

        while True:
            connector = adapter.event_connector(context)
            assert connector is not None
            try:
                await report_connector(source.id, "starting", None)
                await connector.run(emit)
                log.warning(
                    "connector ended, restarting", data_source=source.name, delay=RESTART_SECONDS
                )
                await report_connector(source.id, "reconnecting", "connector ended")
            except asyncio.CancelledError:
                await report_connector(source.id, "stopped", "connector stopped")
                raise
            except Exception as exc:
                log.error("connector crashed, restarting", data_source=source.name, exc_info=True)
                await report_connector(source.id, "error", f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(RESTART_SECONDS)


def main() -> None:
    worker = Worker("ingest")
    runner = ConnectorRunner(worker.bus)
    worker.background(runner.run)
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()
