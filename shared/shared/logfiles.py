"""Raw device log files and browser syncs (architecture 25.6, decision D77).

The file format is the one the public OpenCollar BLE app exports: one frame per line, base64
encoded, each frame beginning with the port byte (`[port][msg_id][len][data]`; on port 29 the
records follow). Hex lines are accepted too, blank lines and lines starting with `#` are
skipped. A browser sync is stored in the same format, so both paths share one row type, one
worker and one re-decode.
"""

import base64
import binascii
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import Topic
from shared.config import get_settings
from shared.domain.assignments import resolve_attribution
from shared.enums import AcquisitionChannel, ErrorCode, LogFileStatus
from shared.ingest import builtin_source, ensure_channel_identity
from shared.models import DataSource, Device, DeviceLogFile
from shared.storage import put_object, sha256
from shared.timeutil import utc_now
from shared.trace import ApplicationError

HEX_LINE = re.compile(r"^[0-9a-fA-F]+$")
MAX_FRAME_BYTES = 4096
CHANNEL_ADAPTERS = {
    AcquisitionChannel.LOG_FILE: "log_file",
    AcquisitionChannel.WEBBLE: "webble",
}


@dataclass(slots=True)
class ParsedFrame:
    line: int
    data: bytes


@dataclass(slots=True)
class ParsedLog:
    frames: list[ParsedFrame] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def lines(self) -> int:
        return len(self.frames) + len(self.errors)


def decode_line(text: str) -> bytes:
    """Base64 (the BLE app's format) or hex; raises ValueError."""
    if HEX_LINE.match(text) and len(text) % 2 == 0:
        return bytes.fromhex(text)
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"neither base64 nor hex: {exc}") from exc


def parse_log_text(text: str) -> ParsedLog:
    result = ParsedLog()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            data = decode_line(line)
        except ValueError as exc:
            result.errors.append((number, str(exc)))
            continue
        if len(data) < 2:
            result.errors.append((number, "frame shorter than a port byte and a message"))
        elif len(data) > MAX_FRAME_BYTES:
            result.errors.append((number, f"frame longer than {MAX_FRAME_BYTES} bytes"))
        else:
            result.frames.append(ParsedFrame(line=number, data=data))
    return result


def frames_to_text(frames: list[bytes]) -> str:
    return "\n".join(base64.b64encode(frame).decode() for frame in frames) + (
        "\n" if frames else ""
    )


class DuplicateLogFile(Exception):
    def __init__(self, existing: DeviceLogFile) -> None:
        super().__init__(f"the same file was uploaded before as {existing.id}")
        self.existing = existing


async def store_log_file(
    session: AsyncSession,
    *,
    device: Device,
    data: bytes,
    filename: str,
    channel: AcquisitionChannel,
    user_id: uuid.UUID | None,
    ble_synced_at: datetime | None = None,
    attributes: dict[str, Any] | None = None,
) -> DeviceLogFile:
    """Store the file in the log files bucket and create its row (status queued). The caller
    commits and publishes `log_file_message`. The same bytes for the same device are refused
    (exact-file duplicate detection, architecture 25.6)."""
    settings = get_settings()
    if len(data) > settings.log_file_max_bytes:
        raise ApplicationError(
            code=ErrorCode.FILE_PARSE_FAILED,
            message=f"file of {len(data)} bytes exceeds the limit of {settings.log_file_max_bytes}",
            component="logfiles",
            user_actionable=True,
        )
    digest = sha256(data)
    existing = await session.scalar(
        select(DeviceLogFile).where(
            DeviceLogFile.device_id == device.id, DeviceLogFile.sha256 == digest
        )
    )
    if existing is not None:
        raise DuplicateLogFile(existing)
    now = utc_now()
    source = await builtin_source(session, CHANNEL_ADAPTERS[channel])
    await ensure_channel_identity(session, source, device.id)
    attribution = await resolve_attribution(session, device.id, now)
    key = f"{device.id}/{now:%Y/%m}/{digest}.txt"
    await put_object(settings.minio_bucket_log_files, key, data, "text/plain")
    row = DeviceLogFile(
        device_id=device.id,
        project_id=attribution.project_id,
        data_source_id=source.id,
        acquisition_channel=channel,
        original_filename=filename[:255],
        sha256=digest,
        size_bytes=len(data),
        object_key=key,
        uploaded_by_user_id=user_id,
        uploaded_at=now,
        ble_synced_at=ble_synced_at,
        status=LogFileStatus.QUEUED,
        attributes=dict(attributes or {}),
    )
    session.add(row)
    await session.flush()
    return row


def log_file_message(row: DeviceLogFile, *, reprocess: bool = False) -> tuple[str, dict[str, Any]]:
    return (
        Topic.LOG_FILE_UPLOADED,
        {
            "log_file_id": str(row.id),
            "device_id": str(row.device_id),
            "acquisition_channel": row.acquisition_channel,
            "reprocess": reprocess,
        },
    )


async def channel_source(session: AsyncSession, channel: AcquisitionChannel) -> DataSource:
    return await builtin_source(session, CHANNEL_ADAPTERS[channel])
