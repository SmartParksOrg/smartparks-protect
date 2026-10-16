"""Raw device log files and browser syncs (architecture 25.6, decision D77).

The file format is the one the public OpenCollar BLE app exports: one frame per line, base64
encoded, each frame beginning with the port byte (`[port][msg_id][len][data]`; on port 29 the
records follow). Hex lines are accepted too, blank lines and lines starting with `#` are
skipped. A browser sync is stored in the same format, so both paths share one row type, one
worker and one re-decode.
"""

import base64
import binascii
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    AcquisitionChannel.LP0: "lp0_station",
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
    if channel != AcquisitionChannel.LP0:
        # a station's card carries other devices' frames, addressed by their LP0 addresses;
        # the station itself is a gateway of the source, not an identity on it (D319)
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


# --- An offload station's SD card (phase 42, decisions D321 and D324) -----------------------

#: `STATIONEUI_timestamp[_NNN].jsonl` under `LOG_N/`, the station's files on its card.
STATION_MEMBER = re.compile(r"(?:^|/)([0-9A-Fa-f]{16}_\d+(?:_\d+)?\.jsonl)$")


@dataclass(slots=True)
class StationFrame:
    """One line of a station's file: the Semtech `rxpk` document the station writes, with the
    frame it stored (an ordinary LoRaWAN uplink under the tracker's keys) and the reception."""

    line: int
    station_eui: str
    data: bytes
    document: dict[str, Any]
    received_at: datetime | None = None
    rssi: float | None = None
    snr: float | None = None
    frequency_hz: int | None = None
    data_rate: str | None = None
    coding_rate: str | None = None
    #: The station's `lp0` object (LP0 v5, firmware issue 772): the protocol version, the
    #: tracker EUI the station learnt in discovery ("claimed source; backend must confirm
    #: registry mapping and MIC", says the firmware header), and the transport's session,
    #: window and slot. Absent on the files of earlier versions. Never trusted for more than
    #: naming and cross-checking: the identity is the address, the keys decide.
    lp0_version: int | None = None
    source_eui: str | None = None
    session: int | None = None
    window: int | None = None
    slot: int | None = None

    @property
    def spreading_factor(self) -> int | None:
        match = re.match(r"SF(\d+)", self.data_rate or "")
        return int(match.group(1)) if match else None


@dataclass(slots=True)
class ParsedStationLog:
    frames: list[StationFrame] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def lines(self) -> int:
        return len(self.frames) + len(self.errors)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_station_line(number: int, text: str) -> StationFrame:
    """One JSON line to a frame; raises `ValueError` with the reason."""
    try:
        document = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not JSON: {exc}") from None
    if not isinstance(document, dict) or not isinstance(document.get("rxpk"), dict):
        raise ValueError("no rxpk document")
    rxpk = document["rxpk"]
    station = str(document.get("gatewayEui") or "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{16}", station):
        raise ValueError("gatewayEui is not sixteen hex digits")
    try:
        data = base64.b64decode(str(rxpk.get("data") or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"data is not base64: {exc}") from None
    if len(data) < 12:
        raise ValueError("frame shorter than a LoRaWAN uplink")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError(f"frame longer than {MAX_FRAME_BYTES} bytes")
    received: datetime | None = None
    time_text = rxpk.get("time")
    if isinstance(time_text, str) and time_text:
        try:
            received = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
            received = received if received.tzinfo else received.replace(tzinfo=UTC)
        except ValueError:
            received = None
    if received is None and isinstance(rxpk.get("tmst"), int) and rxpk["tmst"] > 0:
        # the station writes Unix seconds in `tmst`, not a gateway's microsecond counter
        received = datetime.fromtimestamp(rxpk["tmst"], tz=UTC)
    frequency = _number(rxpk.get("freq"))
    lp0 = _lp0_metadata(document.get("lp0"))
    return StationFrame(
        line=number,
        station_eui=station,
        data=data,
        document=document,
        received_at=received,
        rssi=_number(rxpk.get("rssi")),
        snr=_number(rxpk.get("lsnr")),
        frequency_hz=round(frequency * 1_000_000) if frequency else None,
        data_rate=str(rxpk["datr"]) if rxpk.get("datr") else None,
        coding_rate=str(rxpk["codr"]) if rxpk.get("codr") else None,
        lp0_version=lp0["version"],
        source_eui=lp0["source_eui"],
        session=lp0["session"],
        window=lp0["window"],
        slot=lp0["slot"],
    )


def _lp0_metadata(value: Any) -> dict[str, Any]:
    """The `lp0` object of a v5 line as the firmware writes it (`version`, `source_eui`,
    `session`, `window`, `slot`, all present together); absent on earlier files. A present
    object that is not that shape is an error: the firmware never writes a partial one. An
    all-zero EUI is no EUI."""
    empty: dict[str, Any] = {
        "version": None,
        "source_eui": None,
        "session": None,
        "window": None,
        "slot": None,
    }
    if value is None:
        return empty
    if not isinstance(value, dict):
        raise ValueError("lp0 metadata is not an object")
    version = value.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError("lp0.version is not a whole number")
    eui = str(value.get("source_eui") or "").strip().upper()
    if eui and not re.fullmatch(r"[0-9A-F]{16}", eui):
        raise ValueError("lp0.source_eui is not sixteen hex digits")
    counters: dict[str, Any] = {}
    for key in ("session", "window", "slot"):
        number = value.get(key)
        if number is not None and (not isinstance(number, int) or isinstance(number, bool)):
            raise ValueError(f"lp0.{key} is not a whole number")
        counters[key] = number
    return {
        "version": version,
        "source_eui": eui if eui and set(eui) != {"0"} else None,
        **counters,
    }


def parse_station_jsonl(text: str) -> ParsedStationLog:
    """A station's file: one JSON document per line (the firmware writes a newline before each
    line, so a file starts with an empty one); an unreadable line is an error with its number."""
    result = ParsedStationLog()
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            result.frames.append(parse_station_line(number, line))
        except ValueError as exc:
            result.errors.append((number, str(exc)))
    return result


def looks_like_station_file(filename: str, data: bytes) -> bool:
    """A card's file by its name, or by its first non-empty line being a JSON document."""
    if filename.lower().endswith(".jsonl"):
        return True
    head = data[:4096].lstrip()
    return head.startswith(b"{")


@dataclass(slots=True)
class CardMember:
    name: str
    folder: str
    data: bytes


@dataclass(slots=True)
class UnpackedCard:
    members: list[CardMember] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def unpack_card_zip(data: bytes, *, member_max_bytes: int) -> UnpackedCard:
    """The `*.jsonl` members of a zip of a card's folders, each with the folder it sat in;
    other members are skipped by name. A member over the per-file limit is skipped too.
    Raises `ValueError` when the bytes are not a zip."""
    result = UnpackedCard()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a zip file: {exc}") from None
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not STATION_MEMBER.search(name):
                result.skipped.append(name)
                continue
            if info.file_size > member_max_bytes:
                result.skipped.append(f"{name} (over {member_max_bytes} bytes)")
                continue
            parts = name.split("/")
            folder = parts[-2] if len(parts) > 1 else ""
            result.members.append(
                CardMember(name=parts[-1], folder=folder, data=archive.read(info))
            )
    return result
