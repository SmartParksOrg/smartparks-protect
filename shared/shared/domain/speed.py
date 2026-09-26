"""Speed and course over ground (phase 37, decision D296). A receiver that reports how fast it
moves puts the reading on the position row (`speed_mps`, `heading_deg`): the OpenCollar with
active tracking on, a Traccar tracker, any driver that decodes them. The decoder also writes
them as measurements, `speed` in m/s and, while moving, the course as `heading` in degrees
from north, so the metrics table, the trends, the explorer, the exports and the rules see them
like any other reading. A course at a standstill is the receiver's noise and is not written.
Pure: no database access."""

from __future__ import annotations

from collections.abc import Iterable

from shared.device_drivers.base import DecodedMeasurement, DecodedPosition

SPEED_METRIC = "speed"
HEADING_METRIC = "heading"


def speed_measurements(positions: Iterable[DecodedPosition]) -> list[DecodedMeasurement]:
    """The `speed` and `heading` measurements of the positions that carry a speed, at the
    fix's own time and record type, so a repeat delivery folds into the same rows."""
    out: list[DecodedMeasurement] = []
    for position in positions:
        if position.speed_mps is None:
            continue
        out.append(
            DecodedMeasurement(
                time=position.time,
                metric_key=SPEED_METRIC,
                value=float(position.speed_mps),
                record_type=position.record_type,
            )
        )
        if position.heading_deg is not None and position.speed_mps > 0:
            out.append(
                DecodedMeasurement(
                    time=position.time,
                    metric_key=HEADING_METRIC,
                    value=float(position.heading_deg) % 360,
                    record_type=position.record_type,
                )
            )
    return out
