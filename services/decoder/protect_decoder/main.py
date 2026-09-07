"""Decoder service: consumes `source_event.received`, writes canonical rows, publishes domain
events after the commit. Also the file processing worker of architecture 25.6: it turns an
uploaded log file or a browser sync into frames and decodes them through the same pipeline."""

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select, tuple_

from protect_decoder.logfiles import handle_log_file
from protect_decoder.pipeline import Outcome, process_source_event, publish_outcome
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.enums import ProcessingStatus
from shared.logger import get_logger
from shared.models import SourceEvent
from shared.worker import Worker

log = get_logger("decoder")

# Retained events of one identity are walked in pages of this many, oldest first.
WALK_PAGE = 200


def build_worker() -> Worker:
    worker = Worker("decoder")

    async def decode(source_event_id: int, ingested_at: datetime, *, reprocess: bool) -> Outcome:
        async with session_scope() as session:
            try:
                outcome = await process_source_event(
                    session, source_event_id, ingested_at, reprocess=reprocess
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
        return outcome

    async def handle(message: Message) -> None:
        payload = message.payload
        await decode(
            int(payload["source_event_id"]),
            datetime.fromisoformat(payload["ingested_at"]),
            reprocess=bool(payload.get("reprocess", False)),
        )

    async def on_identity_reprocess(message: Message) -> None:
        """Walk the retained events of an identity that got a device (decision D121): oldest
        first, in pages, each decoded and committed on its own, so a redelivery of the message
        carries on with what is left and a failing event (marked failed by the pipeline) does
        not stop the rest."""
        identity_id = uuid.UUID(message.payload["external_identity_id"])
        after: tuple[datetime, int] | None = None
        processed = failed = 0
        while True:
            async with session_scope() as session:
                statement = (
                    select(SourceEvent.ingested_at, SourceEvent.id)
                    .where(
                        SourceEvent.external_identity_id == identity_id,
                        SourceEvent.processing_status == ProcessingStatus.RECEIVED,
                        SourceEvent.device_id.is_not(None),
                    )
                    .order_by(SourceEvent.ingested_at, SourceEvent.id)
                    .limit(WALK_PAGE)
                )
                if after is not None:
                    statement = statement.where(
                        tuple_(SourceEvent.ingested_at, SourceEvent.id) > after
                    )
                page = (await session.execute(statement)).all()
            if not page:
                break
            for ingested_at, event_id in page:
                try:
                    await decode(event_id, ingested_at, reprocess=True)
                    processed += 1
                except Exception:
                    failed += 1
                    log.exception("retained event failed", source_event_id=event_id)
                after = (ingested_at, event_id)
        log.info(
            "identity reprocessed",
            external_identity_id=str(identity_id),
            processed=processed,
            failed=failed,
        )

    async def on_log_file(message: Message) -> None:
        await handle_log_file(worker.bus, message.payload)

    worker.subscribe(Topic.SOURCE_EVENT_RECEIVED, handle)
    worker.subscribe(Topic.LOG_FILE_UPLOADED, on_log_file)
    worker.subscribe(Topic.IDENTITY_REPROCESS_REQUESTED, on_identity_reprocess)
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
