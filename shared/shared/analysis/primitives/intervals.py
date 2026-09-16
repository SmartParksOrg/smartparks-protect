"""How regularly a device reports (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md, section 4.2):
the interval its settings promise against the intervals seen, the reports that did not come
and the silences. The settings come from what Protect knows of the device: its own attributes,
its type's defaults, the settings frames it sent (TLVs the driver's catalogue names). Pure."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

#: A gap longer than this many expected intervals is a silence.
SILENCE_FACTOR = 3
#: With no expected interval, silences are measured against the median interval seen, once
#: this many messages exist.
MIN_FOR_OBSERVED = 5

from shared.domain.reporting_rules import (  # noqa: E402
    DISAGREE_SHARE,
    LEARN_BIN_S,
    LEARN_MIN_MESSAGES,
    LEARN_MIN_SHARE,
    LEARN_TOLERANCE,
    SENSIBLE_INTERVALS_S,
    TLV_FORMATS,
    Expected,
    Learned,
    decode_tlv_settings,
    expected_intervals,
    learn_interval,
    merged_settings,
    resolve_expected,
    snap_interval,
)


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


__all__ = [
    "DISAGREE_SHARE",
    "LEARN_BIN_S",
    "LEARN_MIN_MESSAGES",
    "LEARN_MIN_SHARE",
    "LEARN_TOLERANCE",
    "MIN_FOR_OBSERVED",
    "SENSIBLE_INTERVALS_S",
    "SILENCE_FACTOR",
    "TLV_FORMATS",
    "Expected",
    "IntervalReport",
    "Learned",
    "decode_tlv_settings",
    "expected_intervals",
    "interval_report",
    "learn_interval",
    "merged_settings",
    "resolve_expected",
    "snap_interval",
]
