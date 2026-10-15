"""File processing worker (architecture 25.6, decision D77).

One `log_file.uploaded` message per file. The worker reads the file from the log files bucket,
splits it into frames, stores every frame as a source event on the channel's built-in data
source (with the device known up front) and decodes it through the normal pipeline, in
batches of one transaction each so a large flash dump shows progress and survives a restart.
The row keeps the counts: frames in the file (`frames_total`, known from the split), frames
done so far (`frames_done`, written after every batch, the progress the pages show), malformed
frames, records found, new and known through another path, the log period and the firmware
version seen. A batch ends at `LOG_FILE_BATCH_SIZE` frames or after `BATCH_SECONDS`, whichever
comes first, so the progress moves every few seconds on a slow file and always counts frames whose
records are committed. A re-decode reprocesses the frames that exist instead of storing them
again.

The file has its own trace (root `log_file`); every frame has the compact trace the ingest
starts, as any other delivery.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_decoder.pipeline import Outcome, process_source_event, publish_outcome
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.connectivity.adapters.lp0_station.lorawan import FrameError, parse_uplink
from shared.connectivity.base import GatewayReceptionData, InboundMessage
from shared.database import session_scope
from shared.domain.lp0 import ensure_station_gateway, station_eui_from_name
from shared.enums import (
    AcquisitionChannel,
    ErrorCode,
    IngestionMethod,
    LogFileStatus,
    ProcessingStatus,
    TraceClass,
)
from shared.ingest import StoredEvent, store_inbound
from shared.logfiles import (
    ParsedFrame,
    ParsedLog,
    ParsedStationLog,
    StationFrame,
    channel_source,
    parse_log_text,
    parse_station_jsonl,
)
from shared.logger import get_logger
from shared.models import DataSource, Device, DeviceLogFile, SourceEvent
from shared.storage import get_object, sha256
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("decoder.logfiles")

INGESTION = {
    AcquisitionChannel.LOG_FILE: IngestionMethod.FILE_UPLOAD,
    AcquisitionChannel.WEBBLE: IngestionMethod.BROWSER_SYNC,
    AcquisitionChannel.LP0: IngestionMethod.FILE_UPLOAD,
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


def station_frame_message(row: DeviceLogFile, frame: StationFrame) -> InboundMessage:
    """One line of an offload station's file as a delivery (decisions D321, D322, D324): the
    tracker's LP0 address from the frame's clear header is the identity, the station is the
    gateway that received it, the line's reception metadata rides in the provider metadata,
    and the station's clock is the delivery time only when it is plausible. The frame is
    stored as it came; the pipeline unwraps it with the device's keys."""
    uplink = parse_uplink(frame.data)  # the header is in the clear; FrameError on garbage
    settings = get_settings()
    plausible = (
        frame.received_at is not None
        and frame.received_at >= settings.lp0_earliest_reception
        and frame.received_at <= row.uploaded_at
    )
    metadata: dict[str, Any] = {
        "log_file_id": str(row.id),
        "line": frame.line,
        "filename": row.original_filename,
        "station_eui": frame.station_eui,
        "dev_addr": uplink.dev_addr,
        "f_cnt": uplink.f_cnt,
        "f_port": uplink.f_port,
        "phy_sha256": sha256(frame.data),
        "frame_bytes": len(frame.data),
    }
    if frame.received_at is not None:
        metadata["received_at"] = frame.received_at.isoformat()
    for key, value in (
        ("rssi", frame.rssi),
        ("snr", frame.snr),
        ("frequency_hz", frame.frequency_hz),
        ("spreading_factor", frame.spreading_factor),
        ("data_rate", frame.data_rate),
        ("coding_rate", frame.coding_rate),
    ):
        if value is not None:
            metadata[key] = value
    if frame.rssi is not None:
        metadata["best_rssi"] = frame.rssi
    if frame.snr is not None:
        metadata["best_snr"] = frame.snr
    if frame.frame_format is not None:
        metadata["frame_format"] = frame.frame_format
    identity_attributes: dict[str, Any] = {}
    if frame.dev_eui is not None:
        # the station's word on who the tracker is (issue 772 lets it keep the EUI as
        # routing metadata): Needs attention shows it as the identity's name, a person links
        metadata["dev_eui"] = frame.dev_eui
        identity_attributes = {"dev_eui": frame.dev_eui, "name": frame.dev_eui}
    return InboundMessage(
        external_id=uplink.dev_addr,
        event_type="uplink",
        payload=frame.document,
        acquisition_channel=AcquisitionChannel.LP0,
        ingestion_method=IngestionMethod.FILE_UPLOAD,
        provider_metadata=metadata,
        identity_attributes=identity_attributes,
        network_received_at=frame.received_at if plausible else None,
        file_uploaded_at=row.uploaded_at,
        identity_type="dev_addr",
        gateway_receptions=[
            GatewayReceptionData(
                gateway_id=frame.station_eui.lower(),
                rssi=frame.rssi,
                snr=frame.snr,
                frequency_hz=frame.frequency_hz,
                attributes={
                    k: v
                    for k, v in (("data_rate", frame.data_rate), ("coding_rate", frame.coding_rate))
                    if v is not None
                },
            )
        ],
    )


async def _existing_frames(session: AsyncSession, row: DeviceLogFile) -> list[SourceEvent]:
    """The frames stored for this file. A station's card carries other devices' frames, so
    its rows are found by the file alone; a device's own file by the device as well."""
    statement = select(SourceEvent).where(
        SourceEvent.data_source_id == row.data_source_id,
        SourceEvent.provider_metadata["log_file_id"].astext == str(row.id),
    )
    if row.acquisition_channel != AcquisitionChannel.LP0:
        statement = statement.where(SourceEvent.device_id == row.device_id)
    rows = await session.scalars(statement.order_by(SourceEvent.id))
    return list(rows.all())


#: A batch also ends after this many seconds. At the dev server's two frames a second a batch of
#: 200 frames held the progress still for over a minute, which read as a stalled decode (Tim,
#: 2026-09-23); a commit every few seconds costs nothing beside the decoding itself.
BATCH_SECONDS = 3.0


@dataclass
class Pacer:
    """When a batch is full: at `size` frames, or once `BATCH_SECONDS` have passed with at least
    one frame done, so a batch always makes progress."""

    size: int
    count: int = 0
    started: float = field(default_factory=time.monotonic)

    def full(self) -> bool:
        if self.count >= self.size:
            return True
        return self.count > 0 and time.monotonic() - self.started >= BATCH_SECONDS


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
        # an offload station's card (phase 42): frames whose tracker is unknown, repeats of a
        # frame stored before, the failures by code, and the figures per tracker address
        self.retained = 0
        self.repeated = 0
        self.errors: dict[str, int] = {}
        self.trackers: dict[str, dict[str, Any]] = {}

    def tracker(self, address: str | None, device_id: uuid.UUID | None) -> dict[str, Any]:
        entry = self.trackers.setdefault(
            address or "?",
            {
                "device_id": None,
                "frames": 0,
                "repeats": 0,
                "retained": 0,
                "failed": 0,
                "without_keys": 0,
                "records_new": 0,
                "records_known": 0,
            },
        )
        if device_id is not None:
            entry["device_id"] = str(device_id)
        return entry

    def add(self, outcome: Outcome | None, *, error_code: str | None = None) -> None:
        self.frames += 1
        if outcome is None:
            self.failed += 1
            if error_code:
                self.errors[error_code] = self.errors.get(error_code, 0) + 1
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
        row.frames_done = self.frames
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
        if row.acquisition_channel == AcquisitionChannel.LP0:
            row.attributes = {
                **(row.attributes or {}),
                "frames_retained": self.retained,
                "frames_repeated": self.repeated,
                "errors": dict(self.errors),
                "trackers": self.trackers,
            }


async def _decode_stored(
    session: AsyncSession, event: SourceEvent, *, reprocess: bool
) -> tuple[Outcome | None, str | None]:
    """Decode one frame; a malformed frame is a failed source event, not a failed file. The
    outcome, or None with the error code."""
    try:
        outcome = await process_source_event(
            session, event.id, event.ingested_at, reprocess=reprocess
        )
    except ApplicationError as error:
        log.info(
            "log file frame failed",
            source_event_id=event.id,
            error_code=error.code,
            message=str(error),
        )
        return None, str(error.code)
    return outcome, None


def _count(
    counters: Counters, event: SourceEvent, outcome: Outcome | None, code: str | None
) -> None:
    """One frame into the file's counters and, on a station's card, its tracker's."""
    counters.add(outcome, error_code=code)
    if event.acquisition_channel != AcquisitionChannel.LP0:
        return
    entry = counters.tracker(event.external_id, event.device_id)
    entry["frames"] += 1
    if outcome is None:
        entry["failed"] += 1
        if code == ErrorCode.CREDENTIALS_MISSING:
            entry["without_keys"] += 1
    else:
        entry["records_new"] += sum(outcome.created.values())
        entry["records_known"] += outcome.duplicates


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
        row.frames_done = 0
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
        station = row.acquisition_channel == AcquisitionChannel.LP0
        parsed: ParsedLog | ParsedStationLog = (
            parse_station_jsonl(text) if station else parse_log_text(text)
        )
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
                message=(
                    "the file holds no frame (one JSON line per frame expected)"
                    if station
                    else "the file holds no frame (one base64 or hex frame per line expected)"
                ),
                component="logfiles",
                user_actionable=True,
            )
        if station:
            # the station is a gateway of the source, linked to the device whose card this is
            # (decision D319); the file is named after its EUI, as every line is
            first = parsed.frames[0]
            eui = station_eui_from_name(row.original_filename) or (
                first.station_eui if isinstance(first, StationFrame) else ""
            )
            device = await session.get(Device, row.device_id)
            gateway = await ensure_station_gateway(session, source, eui, device, utc_now())
            row.attributes = {**(row.attributes or {}), "station_eui": eui}
            async with tracer.step(
                "logfiles", "station gateway", output_ref=f"gateway:{gateway.id}"
            ) as step:
                step.metadata.update(station_eui=eui, device=str(row.device_id))
        counters.failed += len(parsed.errors)
        counters.frames += len(parsed.errors)
        row.frames_total = parsed.lines
        counters.apply(row)
        await session.commit()
        frames: Sequence[ParsedFrame | StationFrame] = parsed.frames
        # Frames already stored by an interrupted run are recognised by their line number and
        # count as done, so the progress reaches the end.
        done = {
            int(e.provider_metadata.get("line", -1)) for e in await _existing_frames(session, row)
        }
        frames = [f for f in frames if f.line not in done]
        counters.frames += len(done)

    position = 0
    while position < len(frames):
        pacer = Pacer(batch_size)
        async with session_scope() as session:
            row = await session.get(DeviceLogFile, log_file_id)
            assert row is not None
            outcomes: list[Outcome] = []
            while position < len(frames) and not pacer.full():
                frame = frames[position]
                position += 1
                pacer.count += 1
                if isinstance(frame, StationFrame):
                    try:
                        message = station_frame_message(row, frame)
                    except FrameError as exc:
                        counters.add(None, error_code=ErrorCode.PAYLOAD_DECODE_FAILED)
                        log.info("station frame unreadable", line=frame.line, reason=str(exc))
                        continue
                else:
                    message = frame_message(row, frame)
                item: StoredEvent = await store_inbound(session, source, message)
                await session.flush()
                event = item.source_event
                if event.processing_status == ProcessingStatus.UNASSIGNED:
                    # a tracker nobody named yet: the frame waits on Needs attention (D320)
                    counters.frames += 1
                    counters.retained += 1
                    counters.tracker(event.external_id, None)["retained"] += 1
                    continue
                if event.processing_status == ProcessingStatus.DUPLICATE:
                    counters.frames += 1
                    counters.repeated += 1
                    counters.tracker(event.external_id, event.device_id)["repeats"] += 1
                    continue
                if event.processing_status != ProcessingStatus.RECEIVED:
                    counters.add(None)
                    continue
                outcome, code = await _decode_stored(session, event, reprocess=False)
                _count(counters, event, outcome, code)
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
        row.frames_total = len(keys)
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
    position = 0
    while position < len(keys):
        pacer = Pacer(batch_size)
        async with session_scope() as session:
            row = await session.get(DeviceLogFile, log_file_id)
            assert row is not None
            outcomes: list[Outcome] = []
            while position < len(keys) and not pacer.full():
                event_id, ingested_at = keys[position]
                position += 1
                pacer.count += 1
                event = await session.get(SourceEvent, (event_id, ingested_at))
                if event is None:
                    counters.add(None)
                    continue
                if (
                    event.processing_status == ProcessingStatus.DUPLICATE
                    and (event.provider_metadata or {}).get("duplicate_of") is not None
                ):
                    # a repeat of another frame stays one (decision D321)
                    counters.frames += 1
                    counters.repeated += 1
                    counters.tracker(event.external_id, event.device_id)["repeats"] += 1
                    continue
                outcome, code = await _decode_stored(session, event, reprocess=True)
                if outcome is not None and outcome.status == ProcessingStatus.UNASSIGNED:
                    counters.frames += 1
                    counters.retained += 1
                    counters.tracker(event.external_id, None)["retained"] += 1
                    continue
                _count(counters, event, outcome, code)
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
