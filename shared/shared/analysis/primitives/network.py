"""The network figures of one device over a period (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
section 4.4): uplinks lost by the frame counter, the gateways that heard the device and the
best one's share, the signal at the best gateway per uplink, and the satellite sessions'
counter. Pure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


def counter_gaps(counters: Iterable[int]) -> tuple[int, int]:
    """Over a counter that should advance by one per message: the messages skipped (lost) and
    the counter's total advance. A counter that goes back (a reset, a rejoin) starts a new
    run and is neither."""
    lost = advance = 0
    previous: int | None = None
    for current in counters:
        if previous is not None and current > previous:
            advance += current - previous
            lost += current - previous - 1
        previous = current
    return lost, advance


def lost_share(counters: Iterable[int]) -> float | None:
    lost, advance = counter_gaps(counters)
    return round(lost / advance, 4) if advance > 0 else None


@dataclass(slots=True)
class GatewayShare:
    gateway_id: str
    uplinks: int
    share: float
    rssi_median: float | None
    snr_median: float | None


@dataclass(slots=True)
class Receptions:
    """Receptions folded per uplink: the best RSSI and SNR of each, and the gateways."""

    uplinks: int
    gateways: list[GatewayShare] = field(default_factory=list)
    best_rssi: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    best_snr: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))
    #: Seconds since the epoch per uplink, in the order of `best_rssi`.
    times_s: NDArray[np.float64] = field(default_factory=lambda: np.zeros(0))

    @property
    def best(self) -> GatewayShare | None:
        return self.gateways[0] if self.gateways else None


def fold_receptions(
    rows: Iterable[tuple[str, int, float | None, float | None, float]],
) -> Receptions:
    """Rows of `(gateway_id, source_event_id, rssi, snr, seconds)` into per-uplink figures and
    per-gateway shares, the gateway with the most uplinks first."""
    per_uplink: dict[int, tuple[float, float, float]] = {}
    per_gateway: dict[str, tuple[set[int], list[float], list[float]]] = {}
    for gateway_id, event_id, rssi, snr, seconds in rows:
        r = float(rssi) if rssi is not None else np.nan
        s = float(snr) if snr is not None else np.nan
        current = per_uplink.get(event_id)
        if current is None or (not np.isnan(r) and (np.isnan(current[0]) or r > current[0])):
            per_uplink[event_id] = (r, s, float(seconds))
        events, rssis, snrs = per_gateway.setdefault(gateway_id, (set(), [], []))
        events.add(event_id)
        if not np.isnan(r):
            rssis.append(r)
        if not np.isnan(s):
            snrs.append(s)
    uplinks = len(per_uplink)
    gateways = [
        GatewayShare(
            gateway_id=gateway_id,
            uplinks=len(events),
            share=round(len(events) / uplinks, 4) if uplinks else 0.0,
            rssi_median=round(float(np.median(rssis)), 1) if rssis else None,
            snr_median=round(float(np.median(snrs)), 1) if snrs else None,
        )
        for gateway_id, (events, rssis, snrs) in per_gateway.items()
    ]
    gateways.sort(key=lambda g: (-g.uplinks, g.gateway_id))
    ordered = sorted(per_uplink.values(), key=lambda v: v[2])
    return Receptions(
        uplinks=uplinks,
        gateways=gateways,
        best_rssi=np.asarray([v[0] for v in ordered], dtype=np.float64),
        best_snr=np.asarray([v[1] for v in ordered], dtype=np.float64),
        times_s=np.asarray([v[2] for v in ordered], dtype=np.float64),
    )
