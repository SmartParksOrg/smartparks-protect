"""File processing worker (architecture 25.6, decision D77).

One `log_file.uploaded` message per file. The worker reads the file from the log files bucket,
splits it into frames, stores every frame as a source event on the channel's built-in data
source (with the device known up front) and decodes it through the normal pipeline, in
batches of one transaction each so a large flash dump shows progress and survives a restart.
The row keeps the counts: frames, malformed frames, records found, new and known through
another path, the log period and the firmware version seen. A re-decode reprocesses the frames
that exist instead of storing them again.

The file has its own trace (root `log_file`); every frame has the compact trace the ingest
starts, as any other delivery.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_decoder.pipeline import Outcome, process_source_event, publish_outcome
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.connectivity.base import InboundMessage
from shared.database import session_scope
from shared.enums import (
    AcquisitionChannel,
    ErrorCode,
    IngestionMethod,
    LogFileStatus,
    ProcessingStatus,
    TraceClass,
)
from shared.ingest import StoredEvent, store_inbound
from shared.logfiles import ParsedFrame, channel_source, parse_log_text
from shared.logger import get_logger
from shared.models import DataSource, DeviceLogFile, SourceEvent
from shared.storage import get_object
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("decoder.logfiles")

INGESTION = {
    AcquisitionChannel.LOG_FILE: IngestionMethod.FILE_UPLOAD,
    AcquisitionChannel.WEBBLE: IngestionMethod.BROWSER_SYNC,
}


def frame_message(row: DeviceLogFile, frame: ParsedFrame) -> InboundMessage:
    channel = AcquisitionChannel(row.acquisition_channel)
    return InboundMessage(
        external_id=str(row.device_id),
        event_type="uplink",
        payload={"data_hex": frame.data.hex(), "line": frame.line},
        acquisition_channel=channel,
        ingestion_method=INGESTION[channel],
        provider_metadata={
            "log_file_id": str(row.id),
            "line": frame.line,
            "filename": row.original_filename,
            "port": frame.data[0],
        },
        ble_synced_at=row.ble_synced_at,
        file_uploaded_at=row.uploaded_at if channel == AcquisitionChannel.LOG_FILE else None,
        identity_type="device_id",
        device_id=row.device_id,
    )


async def _existing_frames(session: AsyncSession, row: DeviceLogFile) -> list[SourceEvent]:
    rows = await session.scalars(
        select(SourceEvent)
        .where(
            SourceEvent.device_id == row.device_id,
            SourceEvent.data_source_id == row.data_source_id,
            SourceEvent.provider_metadata["log_file_id"].astext == str(row.id),
        )
        .order_by(SourceEvent.id)
    )
    return list(rows.all())


class Counters:
    def __init__(self) -> None:
        self.frames = 0
        self.failed = 0
        self.found = 0
        self.new = 0
        self.duplicate = 0
        self.earliest: datetime | None = None
        self.latest: datetime | None = None
        self.firmware: str | None = None
        self.decoder: str | None = None

    def add(self, outcome: Outcome | None) -> None:
        self.frames += 1
        if outcome is None:
            self.failed += 1
            return
        created = sum(outcome.created.values())
        self.found += created + outcome.duplicates
        self.new += created
        self.duplicate += outcome.duplicates
        if outcome.earliest and (self.earliest is None or outcome.earliest < self.earliest):
            self.earliest = outcome.earliest
        if outcome.latest and (self.latest is None or outcome.latest > self.latest):
            self.latest = outcome.latest
        if outcome.firmware_version:
            self.firmware = outcome.firmware_version
        if outcome.decoder_version:
            self.decoder = outcome.decoder_version

    def apply(self, row: DeviceLogFile) -> None:
        row.frames_total = self.frames
        row.frames_failed = self.failed
        row.records_found = self.found
        row.records_new = self.new
        row.records_duplicate = self.duplicate
        row.period_start = self.earliest
        row.period_end = self.latest
        if self.firmware:
            row.firmware_version = self.firmware
        if self.decoder:
            row.decoder_version = self.decoder


async def _decode_stored(
    session: AsyncSession, event: SourceEvent, *, reprocess: bool
) -> Outcome | None:
    """Decode one frame; a malformed frame is a failed source event, not a failed file."""
    try:
        return await process_source_event(session, event.id, event.ingested_at, reprocess=reprocess)
    except ApplicationError as error:
        log.info(
            "log file frame failed",
            source_event_id=event.id,
            error_code=error.code,
            message=str(error),
        )
        return None


async def process_log_file(
    bus: RedisStreamsBus, log_file_id: uuid.UUID, *, reprocess: bool = False
) -> None:
    settings = get_settings()
    batch_size = settings.log_file_batch_size
    async with session_scope() as session:
        row = await session.get(DeviceLogFile, log_file_id)
        if row is None:
            log.warning("log file not found", log_file_id=str(log_file_id))
            return
        source = await channel_source(session, AcquisitionChannel(row.acquisition_channel))
        tracer = Tracer(
            session,
            root_object_type="log_file",
            root_object_id=str(row.id),
            trace_class=TraceClass.ROUTINE,
            project_id=row.project_id,
            device_id=row.device_id,
            data_source_id=source.id,
        )
        await tracer.start()
        row.trace_id = tracer.trace_id
        row.status = LogFileStatus.PROCESSING
        row.error_code = None
        row.error_message = None
        await session.commit()
        trace_id = tracer.trace_id

    counters = Counters()
    try:
        if reprocess:
            await _reprocess(bus, log_file_id, source, trace_id, counters, batch_size)
        else:
            await _process_new(bus, log_file_id, source, trace_id, counters, batch_size)
    except ApplicationError as error:
        async with session_scope() as session:
            row = await session.get(DeviceLogFile, log_file_id)
            assert row is not None
            counters.apply(row)
            row.status = LogFileStatus.FAILED
            row.error_code = error.code
            row.error_message = str(error)
            row.processed_at = utc_now()
            tracer = await Tracer.resume(session, trace_id)
            async with tracer.step("logfiles", "file failed") as step:
                step.metadata.update(error=str(error))
            await tracer.finish()
            await session.commit()
        log.warning("log file failed", log_file_id=str(log_file_id), error=str(error))
        return

    async with session_scope() as session:
        row = await session.get(DeviceLogFile, log_file_id)
        assert row is not None
        counters.apply(row)
        row.status = LogFileStatus.COMPLETE
        row.processed_at = utc_now()
        tracer = await Tracer.resume(session, trace_id)
        async with tracer.step("logfiles", "file decoded") as step:
            step.metadata.update(
                frames=counters.frames,
                malformed=counters.failed,
                records=counters.found,
                new=counters.new,
                duplicates=counters.duplicate,
            )
            if counters.found and counters.new == 0:
                step.duplicate(of="records known through another path")
        await tracer.finish()
        await session.commit()
    log.info(
        "log file decoded",
        log_file_id=str(log_file_id),
        frames=counters.frames,
        new=counters.new,
        duplicates=counters.duplicate,
        malformed=counters.failed,
    )


async def _process_new(
    bus: RedisStreamsBus,
    log_file_id: uuid.UUID,
    source: DataSource,
    trace_id: uuid.UUID,
    counters: Counters,
    batch_size: int,
) -> None:
    async with session_scope() as session:
        row = await session.get(DeviceLogFile, log_file_id)
        assert row is not None
        data = await get_object(get_settings().minio_bucket_log_files, row.object_key)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApplicationError(
                code=ErrorCode.FILE_PARSE_FAILED,
                message=f"the file is not text: {exc}",
                component="logfiles",
                user_actionable=True,
            ) from exc
        parsed = parse_log_text(text)
        tracer = await Tracer.resume(session, trace_id)
        async with tracer.step("logfiles", "frames split") as step:
            step.metadata.update(
                lines=parsed.lines, frames=len(parsed.frames), unreadable=len(parsed.errors)
            )
            if parsed.errors:
                step.metadata["first_errors"] = [f"line {n}: {m}" for n, m in parsed.errors[:5]]
        if not parsed.frames:
            await session.commit()
            raise ApplicationError(
                code=ErrorCode.FILE_PARSE_FAILED,
                message="the file holds no frame (one base64 or hex frame per line expected)",
                component="logfiles",
                user_actionable=True,
            )
        counters.failed += len(parsed.errors)
        counters.frames += len(parsed.errors)
        row.frames_total = parsed.lines
        await session.commit()
        frames = parsed.frames
        # Frames already stored by an interrupted run are recognised by their line number.
        done = {
            int(e.provider_metadata.get("line", -1)) for e in await _existing_frames(session, row)
        }
        frames = [f for f in frames if f.line not in done]

    for start in range(0, len(frames), batch_size):
        batch = frames[start : start + batch_size]
        async with session_scope() as session:
            row = await session.get(DeviceLogFile, log_file_id)
            assert row is not None
            stored: list[StoredEvent] = []
            for frame in batch:
                stored.append(await store_inbound(session, source, frame_message(row, frame)))
            await session.flush()
            outcomes: list[Outcome] = []
            for item in stored:
                event = item.source_event
                if event.processing_status != ProcessingStatus.RECEIVED:
                    counters.add(None)
                    continue
                outcome = await _decode_stored(session, event, reprocess=False)
                counters.add(outcome)
                if outcome is not None:
                    outcomes.append(outcome)
            counters.apply(row)
            await session.commit()
        for outcome in outcomes:
            await publish_outcome(bus, outcome)


async def _reprocess(
    bus: RedisStreamsBus,
    log_file_id: uuid.UUID,
    source: DataSource,
    trace_id: uuid.UUID,
    counters: Counters,
    batch_size: int,
) -> None:
    async with session_scope() as session:
        row = await session.get(DeviceLogFile, log_file_id)
        assert row is not None
        events = await _existing_frames(session, row)
        keys = [(e.id, e.ingested_at) for e in events]
        tracer = await Tracer.resume(session, trace_id)
        async with tracer.step("logfiles", "frames reprocessed") as step:
            step.metadata.update(frames=len(keys))
        await session.commit()
    if not keys:
        raise ApplicationError(
            code=ErrorCode.FILE_PARSE_FAILED,
            message="no stored frames to decode again; upload the file once more",
            component="logfiles",
            user_actionable=True,
        )
    for start in range(0, len(keys), batch_size):
        batch = keys[start : start + batch_size]
        async with session_scope() as session:
            row = await session.get(DeviceLogFile, log_file_id)
            assert row is not None
            outcomes: list[Outcome] = []
            for event_id, ingested_at in batch:
                event = await session.get(SourceEvent, (event_id, ingested_at))
                if event is None:
                    counters.add(None)
                    continue
                outcome = await _decode_stored(session, event, reprocess=True)
                counters.add(outcome)
                if outcome is not None:
                    outcomes.append(outcome)
            counters.apply(row)
            await session.commit()
        for outcome in outcomes:
            await publish_outcome(bus, outcome)


async def handle_log_file(bus: RedisStreamsBus, payload: dict[str, Any]) -> None:
    await process_log_file(
        bus, uuid.UUID(str(payload["log_file_id"])), reprocess=bool(payload.get("reprocess"))
    )
