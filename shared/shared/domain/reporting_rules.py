"""What a device is expected to report and how often (decisions D225 to D227): the settings
Protect knows (decoded from the collar's own frames by the driver's catalogue, the type's and
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
}


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
LEARN_BIN_S = 30.0
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


def learn_interval(times_s: NDArray[np.float64]) -> Learned | None:
    """The dominant interval between consecutive messages: intervals longer than three times
    the median are silences and left out, the rest are rounded to half minutes and the most
    frequent value wins; None below five messages."""
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
