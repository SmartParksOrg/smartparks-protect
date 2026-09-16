"""What a device is expected to report and how often (decisions D225 to D227): the settings
Protect knows (decoded from the device's own frames by the driver's catalogue, the type's and
the device's declared settings), the interval the data shows, and the resolution of the two
into one expectation with its source named. Core code: the analysis module and the device
page's Reporting card both read it, so they say the same thing."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

#: A gap longer than this many expected intervals is a silence.
SILENCE_FACTOR = 3
#: With no expected interval, silences are measured against the median interval seen, once
#: this many messages exist.
MIN_FOR_OBSERVED = 5

TLV_FORMATS = {
    "uint8": "<B",
    "uint16": "<H",
    "uint32": "<I",
    "int8": "<b",
    "int16": "<h",
    "int32": "<i",
    "bool": "<B",
}


def decode_setting_value(item: dict[str, Any], raw: bytes) -> Any:
    """One setting's bytes as a value the catalogue's type gives: an integer, a boolean, a
    string, or a hex string for a byte array; None when the bytes do not fit the type."""
    kind = str(item.get("type", ""))
    if kind == "string":
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if kind == "byte_array":
        return raw.hex()
    fmt = TLV_FORMATS.get(kind)
    if fmt is None or len(raw) != struct.calcsize(fmt):
        return None
    value = struct.unpack(fmt, raw)[0]
    return bool(value) if kind == "bool" else int(value)


def encode_setting_value(item: dict[str, Any], value: Any) -> bytes:
    """The bytes of a value for the catalogue's type, checked against its range; raises
    ValueError when the value does not fit."""
    kind = str(item.get("type", ""))
    length = int(item.get("length") or 0)
    if kind == "string":
        raw = str(value).encode("utf-8")
        if length and len(raw) > length:
            raise ValueError(f"at most {length} bytes")
        return raw.ljust(length, b"\x00") if length else raw
    if kind == "byte_array":
        raw = bytes.fromhex(str(value))
        if length and len(raw) != length:
            raise ValueError(f"{length} bytes as hex")
        return raw
    fmt = TLV_FORMATS.get(kind)
    if fmt is None:
        raise ValueError(f"unknown type {kind}")
    if kind == "bool":
        number = 1 if value in (True, 1, "1", "true", "True") else 0
    else:
        number = int(value)
        low, high = item.get("min"), item.get("max")
        if isinstance(low, int | float) and number < low:
            raise ValueError(f"at least {low}")
        if isinstance(high, int | float) and number > high:
            raise ValueError(f"at most {high}")
    return struct.pack(fmt, number)


def decode_tlv_values(
    tlv: dict[str, str], catalog: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every setting of a frame the catalogue names: `{name: {"id", "value", "raw_hex"}}`,
    whatever its type; an item the catalogue does not know is left out."""
    by_id = {int(item["id"]): item for item in catalog if "id" in item and "name" in item}
    out: dict[str, dict[str, Any]] = {}
    for key, value in tlv.items():
        try:
            item = by_id[int(str(key), 16)]
            raw = bytes.fromhex(str(value))
        except (KeyError, ValueError):
            continue
        decoded = decode_setting_value(item, raw)
        if decoded is None:
            continue
        out[str(item["name"])] = {"id": int(item["id"]), "value": decoded, "raw_hex": raw.hex()}
    return out


def decode_tlv_settings(tlv: dict[str, str], catalog: list[dict[str, Any]]) -> dict[str, int]:
    """The named integer settings out of a settings frame the driver stored as
    `{"0x01": "hex"}`, by the catalogue's id, name and type; unknown or odd items are left out."""
    by_id = {int(item["id"]): item for item in catalog if "id" in item and "name" in item}
    out: dict[str, int] = {}
    for key, value in tlv.items():
        try:
            item = by_id[int(str(key), 16)]
            raw = bytes.fromhex(str(value))
            fmt = TLV_FORMATS[str(item.get("type", ""))]
        except (KeyError, ValueError):
            continue
        if len(raw) != struct.calcsize(fmt):
            continue
        out[str(item["name"])] = int(struct.unpack(fmt, raw)[0])
    return out


def expected_intervals(settings: dict[str, Any]) -> dict[str, float | None]:
    """The seconds between fixes, statuses and satellite sessions a device's settings promise;
    None when unknown or switched off (zero). A fix comes from the LoRa GPS interval, else the
    u-blox send interval."""

    def seconds(*keys: str) -> float | None:
        for key in keys:
            value = settings.get(key)
            if isinstance(value, int | float) and value > 0:
                return float(value)
        return None

    return {
        "fix": seconds("lr_gps_interval", "ublox_send_interval"),
        "status": seconds("status_send_interval"),
        "satellite": seconds("satellite_send_interval"),
    }


def merged_settings(*layers: dict[str, Any] | None) -> dict[str, Any]:
    """Later layers win: the type's defaults, the device's attributes, the settings frames."""
    out: dict[str, Any] = {}
    for layer in layers:
        if isinstance(layer, dict):
            out.update({k: v for k, v in layer.items() if isinstance(v, int | float)})
    return out


#: Learning an interval from the data (decision D225): the dominant interval between messages,
#: silences left out, trusted when this share of the intervals sits within the tolerance of it.
LEARN_BIN_S = 60.0
#: The intervals a person would set (Tim, 2026-09-16): the learned bin snaps to the nearest
#: of these when it lies within `SNAP_TOLERANCE` of it or within one bin, so a device fixing
#: every hour reads 3600 s, not 3570 because the fix time carries the time to fix.
SENSIBLE_INTERVALS_S = (
    60,
    120,
    180,
    240,
    300,
    600,
    900,
    1200,
    1800,
    2700,
    3600,
    5400,
    7200,
    10800,
    14400,
    21600,
    28800,
    43200,
    86400,
)
SNAP_TOLERANCE = 0.05
LEARN_TOLERANCE = 0.2
LEARN_MIN_SHARE = 0.6
LEARN_MIN_MESSAGES = 5
#: A declared interval this far from the learned one is stale (decision D227).
DISAGREE_SHARE = 0.3


@dataclass(slots=True)
class Learned:
    """The interval the data shows: the dominant one, how regular the messages are around it
    (the share of intervals within the tolerance), and how many intervals were judged."""

    seconds: float
    regular_share: float
    intervals: int

    @property
    def confident(self) -> bool:
        return self.regular_share >= LEARN_MIN_SHARE and self.intervals >= LEARN_MIN_MESSAGES - 1


def snap_interval(seconds: float) -> float:
    """The nearest of `SENSIBLE_INTERVALS_S` when it lies within `SNAP_TOLERANCE` or one bin
    of the value; the value itself otherwise (a device set to 22 minutes keeps 22)."""
    nearest = min(SENSIBLE_INTERVALS_S, key=lambda s: abs(s - seconds))
    if abs(nearest - seconds) <= max(SNAP_TOLERANCE * nearest, LEARN_BIN_S):
        return float(nearest)
    return seconds


def learn_interval(times_s: NDArray[np.float64]) -> Learned | None:
    """The dominant interval between consecutive messages: intervals longer than three times
    the median are silences and left out, the rest are rounded to whole minutes and the most
    frequent value wins, snapped to the nearest sensible interval (`snap_interval`); None below
    five messages."""
    if times_s.size < LEARN_MIN_MESSAGES:
        return None
    gaps = np.diff(np.sort(times_s))
    gaps = gaps[gaps > 0]
    if gaps.size == 0:
        return None
    median = float(np.median(gaps))
    kept = gaps[gaps <= SILENCE_FACTOR * median]
    if kept.size == 0:
        return None
    bins = np.round(kept / LEARN_BIN_S) * LEARN_BIN_S
    values, counts = np.unique(bins, return_counts=True)
    dominant = float(values[int(np.argmax(counts))])
    if dominant <= 0:
        dominant = float(np.median(kept))
    dominant = snap_interval(dominant)
    regular = float(np.mean(np.abs(kept - dominant) <= LEARN_TOLERANCE * dominant))
    return Learned(seconds=dominant, regular_share=round(regular, 3), intervals=int(kept.size))


@dataclass(slots=True)
class Expected:
    """The interval a device is expected to keep, and where that expectation comes from:
    `override` (a person set it on the device), `settings_frame` (the device reported it),
    `command` (Protect set it and the device acknowledged), `type_default` (the type's or the
    device's declared settings), `learned` (the data), or `unknown`."""

    seconds: float | None
    source: str
    learned: Learned | None = None
    #: The declared interval the learned one replaced (decision D227), when they disagree.
    declared_seconds: float | None = None
    declared_source: str | None = None

    @property
    def disagrees(self) -> bool:
        return self.declared_seconds is not None and self.source == "learned"


def resolve_expected(declared: tuple[float, str] | None, times_s: NDArray[np.float64]) -> Expected:
    """The expected interval from a declared one and the data (decisions D225 to D227): a
    person's override always holds; another declared interval holds unless the data plainly
    disagrees (a confident learned interval
    more than 30 percent away), then the learned one counts and the declared one is kept
    beside it as stale; without a declared interval a confident learned one serves; otherwise
    the interval is unknown, with what the data showed for the reader."""
    learned = learn_interval(times_s)
    if declared is not None and declared[0] > 0:
        seconds, source = declared
        if source == "override":
            # a person's word comes first, whatever the data shows (decision D226)
            return Expected(seconds=seconds, source=source, learned=learned)
        if (
            learned is not None
            and learned.confident
            and abs(learned.seconds - seconds) / seconds > DISAGREE_SHARE
        ):
            return Expected(
                seconds=learned.seconds,
                source="learned",
                learned=learned,
                declared_seconds=seconds,
                declared_source=source,
            )
        return Expected(seconds=seconds, source=source, learned=learned)
    if learned is not None and learned.confident:
        return Expected(seconds=learned.seconds, source="learned", learned=learned)
    return Expected(seconds=None, source="unknown", learned=learned)
