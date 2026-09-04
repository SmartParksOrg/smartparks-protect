"""Decoder service: consumes `source_event.received`, writes canonical rows, publishes domain
events after the commit. Also the file processing worker of architecture 25.6: it turns an
uploaded log file or a browser sync into frames and decodes them through the same pipeline."""

import asyncio
from datetime import datetime

from protect_decoder.logfiles import handle_log_file
from protect_decoder.pipeline import process_source_event, publish_outcome
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.logger import get_logger
from shared.worker import Worker

log = get_logger("decoder")


def build_worker() -> Worker:
    worker = Worker("decoder")

    async def handle(message: Message) -> None:
        payload = message.payload
        async with session_scope() as session:
            try:
                outcome = await process_source_event(
                    session,
                    int(payload["source_event_id"]),
                    datetime.fromisoformat(payload["ingested_at"]),
                    reprocess=bool(payload.get("reprocess", False)),
                )
            except Exception:
                await (
                    session.commit()
                )  # keep the failed status and the trace, then let the bus decide
                raise
            await session.commit()
        await publish_outcome(worker.bus, outcome)
        log.info(
            "source event processed",
            source_event_id=outcome.source_event_id,
            status=outcome.status,
            created=outcome.created,
            duplicates=outcome.duplicates,
        )

    async def on_log_file(message: Message) -> None:
        await handle_log_file(worker.bus, message.payload)

    worker.subscribe(Topic.SOURCE_EVENT_RECEIVED, handle)
    worker.subscribe(Topic.LOG_FILE_UPLOADED, on_log_file)
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
