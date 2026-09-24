"""Decoder service: consumes `source_event.received`, writes canonical rows, publishes domain
events after the commit. Also the file processing worker of architecture 25.6: it turns an
uploaded log file or a browser sync into frames and decodes them through the same pipeline."""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import tuple_

from protect_decoder.logfiles import handle_log_file
from protect_decoder.pipeline import Outcome, process_source_event, publish_outcome
from shared import reprocessing
from shared.bus import Message, Topic
from shared.database import session_scope
from shared.ingest import (
    ReceptionRef,
    link_event_receptions,
    retained_events,
    unlinked_receptions,
)
from shared.logger import get_logger
from shared.models import ExternalIdentity, SourceEvent
from shared.worker import Worker

log = get_logger("decoder")

# Retained events of one identity are walked in pages of this many, oldest first.
WALK_PAGE = 200


def build_worker() -> Worker:
    worker = Worker("decoder")

    async def decode(
        source_event_id: int,
        ingested_at: datetime,
        *,
        reprocess: bool,
        device_id: uuid.UUID | None = None,
        receptions: Sequence[ReceptionRef] = (),
    ) -> Outcome:
        async with session_scope() as session:
            try:
                if device_id is not None and receptions:
                    await link_event_receptions(session, device_id, receptions)
                outcome = await process_source_event(
                    session, source_event_id, ingested_at, reprocess=reprocess, device_id=device_id
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
        first, in pages, each given the device and decoded and committed on its own, with the
        receptions of the page linked as it goes, so a redelivery of the message carries on
        with what is left and a failing event (marked failed by the pipeline) does not stop
        the rest. Nothing is marked up front: a statement over an identity's whole history
        decompresses every compressed batch of its source, and TimescaleDB stops a
        transaction at 100,000 tuples (the 500 of 2026-09-24). The keyset moves past a
        failed event, so one that fails again is not walked twice."""
        identity_id = uuid.UUID(message.payload["external_identity_id"])
        async with session_scope() as session:
            identity = await session.get(ExternalIdentity, identity_id)
            if identity is None or identity.device_id is None:
                log.warning(
                    "identity to reprocess has no device", external_identity_id=str(identity_id)
                )
                await reprocessing.end_walk(worker.bus.redis, identity_id)
                return
            device_id = identity.device_id
            session.expunge(identity)
        after: tuple[datetime, int] | None = None
        processed = failed = 0
        while True:
            async with session_scope() as session:
                statement = retained_events(identity).limit(WALK_PAGE)
                if after is not None:
                    statement = statement.where(
                        tuple_(SourceEvent.ingested_at, SourceEvent.id) > after
                    )
                page = [
                    (int(event_id), ingested_at)
                    for event_id, ingested_at in (await session.execute(statement)).all()
                ]
                receptions = await unlinked_receptions(session, page)
            if not page:
                break
            for event_id, ingested_at in page:
                try:
                    await decode(
                        event_id,
                        ingested_at,
                        reprocess=True,
                        device_id=device_id,
                        receptions=receptions.get((event_id, ingested_at), ()),
                    )
                    processed += 1
                except Exception:
                    failed += 1
                    log.exception("retained event failed", source_event_id=event_id)
                after = (ingested_at, event_id)
            await reprocessing.advance_walk(worker.bus.redis, identity_id, processed + failed)
        await reprocessing.end_walk(worker.bus.redis, identity_id)
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
