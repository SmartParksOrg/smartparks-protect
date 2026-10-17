"""An offload station's SD card, read without a server (phase 42, decisions D321, D324 and D327;
phase 43 P1, decision D331).

The station writes `LOG_N/STATIONEUI_timestamp[_NNN].jsonl`: one Semtech `rxpk` JSON document per
line with the frame it stored, an ordinary LoRaWAN 1.0 uplink under the tracker's keys, and the
reception; since LP0 v5 an `lp0` object beside it. This module parses those files and unpacks a
card's zip. It imports nothing that needs a database, a broker or Protect's settings, so Smart
Parks Protect Go reads a card with it on a laptop exactly as the file worker does on the
server; `shared/logfiles.py` holds the storing half.
"""

import base64
import binascii
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: The longest frame a file may carry; a raw log file line shares the limit.
MAX_FRAME_BYTES = 4096
#: `STATIONEUI_timestamp[_NNN].jsonl`, a station's file by its name alone.
STATION_FILE = re.compile(r"^([0-9A-Fa-f]{16})_(\d+)(?:_(\d+))?\.jsonl$")
#: The same under `LOG_N/`, as a member of a card's zip.
STATION_MEMBER = re.compile(r"(?:^|/)([0-9A-Fa-f]{16}_\d+(?:_\d+)?\.jsonl)$")


def station_eui_from_name(filename: str) -> str | None:
    """The station EUI a card's file is named after, upper case, or None for another name."""
    match = STATION_FILE.match(filename.replace("\\", "/").rsplit("/", 1)[-1])
    return match.group(1).upper() if match else None


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
