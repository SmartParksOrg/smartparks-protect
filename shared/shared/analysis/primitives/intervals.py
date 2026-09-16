"""How regularly a device reports (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, section 4.2):
the interval its settings promise against the intervals seen, the reports that did not come
and the silences. The settings come from what Protect knows of the device: its own attributes,
its type's defaults, the settings frames it sent (TLVs the driver's catalogue names). Pure."""

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


@dataclass(slots=True)
class IntervalReport:
    """One message kind over a window."""

    messages: int
    expected_s: float | None
    observed_median_s: float | None
    observed_p90_s: float | None
    expected_count: int | None
    missed_share: float | None
    silences: int
    longest_silence_s: float | None
    #: Seconds since the epoch when the longest silence ended; None when it ran to the end.
    longest_silence_end: float | None


def interval_report(
    times_s: NDArray[np.float64],
    window_from_s: float,
    window_to_s: float,
    expected_s: float | None,
) -> IntervalReport:
    """Intervals between messages in time order, the messages the interval promised against
    the ones seen, and the silences (gaps longer than three intervals, the window's edges
    included, so a device silent since the middle of the period shows it)."""
    n = int(times_s.size)
    gaps = np.diff(times_s) if n > 1 else np.zeros(0, dtype=np.float64)
    median = float(np.median(gaps)) if gaps.size else None
    p90 = float(np.percentile(gaps, 90)) if gaps.size else None
    window_s = max(0.0, window_to_s - window_from_s)
    expected_count = int(window_s // expected_s) if expected_s else None
    missed = (
        round(max(0.0, 1 - n / expected_count), 4)
        if expected_count and expected_count > 0
        else None
    )
    yardstick = expected_s if expected_s else (median if n >= MIN_FOR_OBSERVED else None)
    silences = 0
    longest: float | None = None
    longest_end: float | None = None
    if yardstick:
        edges = (
            np.concatenate(([window_from_s], times_s, [window_to_s]))
            if n
            else np.asarray([window_from_s, window_to_s])
        )
        all_gaps = np.diff(edges)
        for i, gap in enumerate(all_gaps):
            if gap > SILENCE_FACTOR * yardstick:
                silences += 1
                if longest is None or gap > longest:
                    longest = float(gap)
                    longest_end = float(edges[i + 1]) if i + 1 < len(edges) - 1 else None
    return IntervalReport(
        messages=n,
        expected_s=expected_s,
        observed_median_s=round(median, 1) if median is not None else None,
        observed_p90_s=round(p90, 1) if p90 is not None else None,
        expected_count=expected_count,
        missed_share=missed,
        silences=silences,
        longest_silence_s=longest,
        longest_silence_end=longest_end,
    )
