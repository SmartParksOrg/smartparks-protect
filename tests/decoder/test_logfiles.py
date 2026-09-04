"""Phase 11 exit criterion: one GNSS record delivered over LoRaWAN, uploaded in a raw log file
and synced over WebBLE is one position with three deliveries. Plus the file worker's counts,
malformed frames and re-decoding."""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from protect_decoder.logfiles import process_log_file
from protect_decoder.pipeline import process_source_event, publish_outcome
from shared.bus import RedisStreamsBus
from shared.enums import AcquisitionChannel, ErrorCode, LogFileStatus
from shared.ingest import commit_and_publish, store_inbound
from shared.logfiles import DuplicateLogFile, frames_to_text, store_log_file
from shared.models import DeviceLogFile, DeviceType, Position, SourceDelivery, SourceEvent
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio

# The wiki's port 29 example holds ten stored short positions of 21 bytes each; the first
# three are enough here.
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "opencollar"
FLASH = next(
    json.loads(line)["data_hex"]
    for line in (FIXTURES / "uplinks.jsonl").read_text().splitlines()
    if line.strip() and json.loads(line)["f_port"] == 29
)[: 3 * 21 * 2]
RECORD_2 = FLASH[21 * 2 : 2 * 21 * 2]
SHORT_13 = "930ef9636865aba50d1f8e090e031500"  # the same fix as a live port 13 uplink
FIX_TIME = datetime.fromtimestamp(0x656863F9, tz=UTC)


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _opencollar(db, world) -> None:
    device_type = await db.get(DeviceType, world.device.device_type_id)
    device_type.driver_key = "opencollar"
    await db.commit()


async def _lorawan(db, bus, world, port: int, hex_frame: str):
    payload = {"fPort": port, "data": base64.b64encode(bytes.fromhex(hex_frame)).decode()}
    stored = await store_inbound(
        db,
        world.source,
        inbound(world.external_id, payload, acquisition_channel=AcquisitionChannel.LORAWAN),
    )
    await commit_and_publish(db, bus, [stored])
    event = stored.source_event
    outcome = await process_source_event(db, event.id, event.ingested_at)
    await db.commit()
    await publish_outcome(bus, outcome)
    return outcome


async def _file(db, bus, world, frames: list[bytes], channel: AcquisitionChannel, name: str):
    row = await store_log_file(
        db,
        device=world.device,
        data=frames_to_text(frames).encode(),
        filename=name,
        channel=channel,
        user_id=None,
        ble_synced_at=datetime.now(UTC) if channel == AcquisitionChannel.WEBBLE else None,
    )
    await db.commit()
    await process_log_file(bus, row.id)
    await db.refresh(row)
    return row


async def test_one_record_over_three_paths_is_one_position_with_three_deliveries(db, bus, world):
    await _opencollar(db, world)
    device_id = world.device.id
    outcome = await _lorawan(db, bus, world, 13, SHORT_13)
    assert outcome.created["positions"] == 1

    upload = await _file(
        db, bus, world, [bytes.fromhex("1d" + FLASH)], AcquisitionChannel.LOG_FILE, "raw_logs.txt"
    )
    assert upload.status == LogFileStatus.COMPLETE, upload.error_message
    assert (upload.frames_total, upload.frames_failed) == (1, 0)
    assert (upload.records_found, upload.records_new, upload.records_duplicate) == (3, 2, 1)
    assert upload.period_start == datetime.fromtimestamp(0x6568633C, tz=UTC)
    assert upload.period_end == datetime.fromtimestamp(0x656864BA, tz=UTC)
    assert upload.decoder_version == "fw7.3.0" and upload.trace_id is not None

    sync = await _file(
        db, bus, world, [bytes.fromhex("1d" + RECORD_2)], AcquisitionChannel.WEBBLE, "sync.txt"
    )
    assert sync.status == LogFileStatus.COMPLETE
    assert (sync.records_found, sync.records_new, sync.records_duplicate) == (1, 0, 1)

    positions = (
        await db.scalars(
            select(Position).where(Position.device_id == device_id, Position.time == FIX_TIME)
        )
    ).all()
    assert len(positions) == 1
    deliveries = (
        await db.scalars(
            select(SourceDelivery)
            .where(
                SourceDelivery.canonical_type == "position",
                SourceDelivery.canonical_id == positions[0].id,
            )
            .order_by(SourceDelivery.id)
        )
    ).all()
    assert [d.acquisition_channel for d in deliveries] == ["lorawan", "log_file", "webble"]
    assert [d.first for d in deliveries] == [True, False, False]

    frames = (
        await db.scalars(
            select(SourceEvent).where(
                SourceEvent.provider_metadata["log_file_id"].astext == str(upload.id)
            )
        )
    ).all()
    assert len(frames) == 1
    frame = frames[0]
    assert frame.device_id == device_id and frame.data_source_id == upload.data_source_id
    assert frame.acquisition_channel == "log_file" and frame.ingestion_method == "file_upload"
    assert frame.file_uploaded_at is not None and frame.external_id == str(world.device.id)
    synced = (
        await db.scalars(
            select(SourceEvent).where(
                SourceEvent.provider_metadata["log_file_id"].astext == str(sync.id)
            )
        )
    ).all()
    assert synced[0].ble_synced_at is not None and synced[0].ingestion_method == "browser_sync"

    upload_id = upload.id
    with pytest.raises(DuplicateLogFile):
        await store_log_file(
            db,
            device=world.device,
            data=frames_to_text([bytes.fromhex("1d" + FLASH)]).encode(),
            filename="again.txt",
            channel=AcquisitionChannel.LOG_FILE,
            user_id=None,
        )
    await db.rollback()

    # decoding again recognises every record and creates nothing
    await process_log_file(bus, upload_id, reprocess=True)
    upload = await db.get(DeviceLogFile, upload_id)
    assert upload.status == LogFileStatus.COMPLETE
    assert (upload.records_found, upload.records_new, upload.records_duplicate) == (3, 0, 3)
    assert (
        await db.scalar(
            select(Position).where(Position.device_id == device_id, Position.time == FIX_TIME)
        )
    ) is not None


async def test_malformed_frames_are_counted_and_an_empty_file_fails(db, bus, world):
    await _opencollar(db, world)
    status = bytes.fromhex("04f40e0400a00095007f7f721444550000")
    text = "not base64!!\n" + frames_to_text([status, bytes.fromhex("04f40e0400")])
    row = await store_log_file(
        db,
        device=world.device,
        data=text.encode(),
        filename="mixed.txt",
        channel=AcquisitionChannel.LOG_FILE,
        user_id=None,
    )
    await db.commit()
    await process_log_file(bus, row.id)
    await db.refresh(row)
    assert row.status == LogFileStatus.COMPLETE
    assert row.frames_total == 3 and row.frames_failed == 2
    assert row.records_new > 0 and row.firmware_version == "4.4"

    empty = await store_log_file(
        db,
        device=world.device,
        data=b"# nothing here\n",
        filename="empty.txt",
        channel=AcquisitionChannel.LOG_FILE,
        user_id=None,
    )
    await db.commit()
    await process_log_file(bus, empty.id)
    await db.refresh(empty)
    assert empty.status == LogFileStatus.FAILED and empty.error_code == ErrorCode.FILE_PARSE_FAILED
