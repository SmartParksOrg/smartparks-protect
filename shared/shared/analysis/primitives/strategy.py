"""The movement strategy from the net squared displacement (docs/ANALYTICS_PHASE2_PLAN.md,
section 4). Four shapes the NSD curve of a year can take, after Bunnefeld and others (2011):
a resident animal's curve levels off, a migrant's rises and comes back, a disperser's rises to
a new plateau and stays, a nomad's keeps rising. Each is a curve with a few parameters, fitted
by least squares to the NSD per day; the corrected Akaike information decides between them and
the margin to the runner-up says how clearly.

What it does not do is read a class from a short period: the shapes only tell apart over
months, so under `MIN_DAYS` the fit is not attempted and the caller says why. The migratory
model keeps one time scale for the way out and the way back where the reference has two, which
is one parameter fewer to fit on the sixty to three hundred points a year gives.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

#: A class needs a period long enough to show it.
MIN_DAYS = 60
#: Under this difference in AICc between the best and the second model, the class is "unclear".
CLEAR_MARGIN = 2.0
#: A departure has to happen inside the period, this many days from either end: a sigmoid
#: whose step sits before the first fix is a plateau, which is the resident's curve, and one
#: whose step sits after the last fix is a line, which is the nomad's. Without the bound the
#: dispersal curve can imitate both and no class is ever clear.
DEPARTURE_MARGIN_DAYS = 7.0

Model = Callable[[NDArray[np.float64], NDArray[np.float64]], NDArray[np.float64]]


def _nomadic(t: NDArray[np.float64], p: NDArray[np.float64]) -> NDArray[np.float64]:
    """A line through the origin: the animal keeps going."""
    return np.asarray(p[0] * t, dtype=np.float64)


def _resident(t: NDArray[np.float64], p: NDArray[np.float64]) -> NDArray[np.float64]:
    """An asymptote: the animal leaves where it started and stays within a range of it."""
    return np.asarray(p[0] * (1 - np.exp(-t / p[1])), dtype=np.float64)


def _dispersal(t: NDArray[np.float64], p: NDArray[np.float64]) -> NDArray[np.float64]:
    """One sigmoid: a departure around day theta, over about phi days, to a new plateau."""
    delta, theta, phi = p
    return np.asarray(delta / (1 + np.exp((theta - t) / phi)), dtype=np.float64)


def _migratory(t: NDArray[np.float64], p: NDArray[np.float64]) -> NDArray[np.float64]:
    """Two sigmoids: out around day theta, back around theta + 2 phi + rho, the same pace each
    way."""
    delta, theta, phi, rho = p
    out = delta / (1 + np.exp((theta - t) / phi))
    back = delta / (1 + np.exp((theta + 2 * phi + rho - t) / phi))
    return np.asarray(out - back, dtype=np.float64)


@dataclass(slots=True)
class Fit:
    """One model fitted: its parameters, its residual and its corrected Akaike information."""

    name: str
    parameters: NDArray[np.float64]
    rss: float
    aicc: float


@dataclass(slots=True)
class Strategy:
    """The class of a subject's year, or the reason there is none.

    `figures` are the parameters people read, in km and days: for a migrant the departure and
    return days and the distance between ranges, for a disperser the departure day and the
    distance, for a resident the typical distance from where it started, for a nomad the drift
    per day. `curve` is the winning model over the days of the period, for the chart."""

    strategy: str | None  # resident, migratory, dispersal, nomadic, unclear, or None
    reason: str | None
    margin: float | None
    figures: dict[str, float] = field(default_factory=dict)
    curve: list[list[float]] = field(default_factory=list)  # [day, km²]
    fits: list[Fit] = field(default_factory=list)


def daily_nsd(
    day: NDArray[np.float64], nsd: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The NSD per day of the period: the median of the fixes of each day, which takes the
    hour-to-hour wandering out of a curve that is about months."""
    if day.size == 0:
        return day, nsd
    whole = np.floor(day).astype(np.int64)
    days = np.unique(whole)
    medians = np.array([float(np.median(nsd[whole == d])) for d in days])
    return days.astype(np.float64) + 0.5, medians


def _nelder_mead(
    f: Callable[[NDArray[np.float64]], float],
    start: NDArray[np.float64],
    step: NDArray[np.float64],
    iterations: int = 600,
) -> tuple[NDArray[np.float64], float]:
    """A plain downhill simplex, enough for three or four well-scaled parameters."""
    n = start.size
    simplex = [start.astype(np.float64)]
    for i in range(n):
        point = start.astype(np.float64).copy()
        point[i] += step[i]
        simplex.append(point)
    values = [f(p) for p in simplex]
    for _ in range(iterations):
        order = np.argsort(values)
        simplex = [simplex[i] for i in order]
        values = [values[i] for i in order]
        if abs(values[-1] - values[0]) <= 1e-9 * (abs(values[0]) + 1e-12):
            break
        centre = np.mean(simplex[:-1], axis=0)
        reflected = centre + (centre - simplex[-1])
        fr = f(reflected)
        if fr < values[0]:
            expanded = centre + 2 * (centre - simplex[-1])
            fe = f(expanded)
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
            continue
        if fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
            continue
        contracted = centre + 0.5 * (simplex[-1] - centre)
        fc = f(contracted)
        if fc < values[-1]:
            simplex[-1], values[-1] = contracted, fc
            continue
        simplex = [simplex[0]] + [simplex[0] + 0.5 * (p - simplex[0]) for p in simplex[1:]]
        values = [values[0]] + [f(p) for p in simplex[1:]]
    best = int(np.argmin(values))
    return simplex[best], float(values[best])


def _aicc(rss: float, n: int, k: int) -> float:
    """The corrected Akaike information of a least squares fit with k parameters and one for
    the residual variance."""
    k = k + 1
    if n - k - 1 <= 0:
        return float("inf")
    return n * math.log(max(rss, 1e-12) / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)


Valid = Callable[[NDArray[np.float64]], bool]


def _fit(
    name: str,
    model: Model,
    t: NDArray[np.float64],
    y: NDArray[np.float64],
    starts: list[NDArray[np.float64]],
    scale: NDArray[np.float64],
    positive: NDArray[np.bool_],
    valid: Valid | None = None,
) -> Fit:
    """Least squares from several starting points, the parameters that must stay positive
    fitted on a log scale, keeping the best; `valid` refuses parameters the model's meaning
    excludes, such as a departure outside the period."""

    def unpack(q: NDArray[np.float64]) -> NDArray[np.float64]:
        p = q.copy()
        p[positive] = np.exp(q[positive])
        return p

    def loss(q: NDArray[np.float64]) -> float:
        p = unpack(q)
        if valid is not None and not valid(p):
            return float("inf")
        with np.errstate(over="ignore", invalid="ignore"):
            r = y - model(t, p)
        value = float(np.sum(r * r))
        return value if math.isfinite(value) else float("inf")

    best: tuple[NDArray[np.float64], float] | None = None
    for start in starts:
        q0 = start.astype(np.float64).copy()
        q0[positive] = np.log(np.maximum(q0[positive], 1e-9))
        step = scale.copy()
        step[positive] = 0.5  # a log step: half an e-fold
        q, value = _nelder_mead(loss, q0, step)
        if best is None or value < best[1]:
            best = (unpack(q), value)
    assert best is not None
    return Fit(name, best[0], best[1], _aicc(best[1], len(t), len(scale)))


def classify(
    days: NDArray[np.float64], nsd_km2: NDArray[np.float64], period_days: float
) -> Strategy:
    """The strategy of one subject over one period from its NSD by day.

    `days` are days since the start of the period, `nsd_km2` the net squared displacement
    from the first fix. The four models are fitted, the lowest AICc wins, and a margin under
    `CLEAR_MARGIN` to the runner-up reads "unclear" rather than a class the data does not
    support."""
    if period_days < MIN_DAYS:
        return Strategy(
            None,
            f"the period is shorter than {MIN_DAYS} days, which is too short to show a "
            "movement strategy",
            None,
        )
    t, y = daily_nsd(days, nsd_km2)
    if t.size < 20:
        return Strategy(None, "fewer than twenty days with fixes, too few to fit a curve", None)
    top = float(np.max(y))
    if top <= 0:
        return Strategy("resident", None, None, {"range_km": 0.0}, [[float(d), 0.0] for d in t])
    span = float(t[-1] - t[0])
    half_way = float(
        np.clip(
            t[int(np.argmax(y >= top / 2))], DEPARTURE_MARGIN_DAYS, span - DEPARTURE_MARGIN_DAYS
        )
    )
    first, last = float(t[0]) + DEPARTURE_MARGIN_DAYS, float(t[-1]) - DEPARTURE_MARGIN_DAYS

    def departs_inside(p: NDArray[np.float64]) -> bool:
        return first <= float(p[1]) <= last

    def returns_inside(p: NDArray[np.float64]) -> bool:
        back = float(p[1] + 2 * p[2] + p[3])
        return departs_inside(p) and back <= last and p[3] >= 0

    fits = [
        _fit(
            "nomadic",
            _nomadic,
            t,
            y,
            [np.array([top / max(span, 1.0)])],
            np.array([top / max(span, 1.0)]),
            np.array([True]),
        ),
        _fit(
            "resident",
            _resident,
            t,
            y,
            [np.array([top, 5.0]), np.array([float(np.median(y)), 20.0])],
            np.array([top, 5.0]),
            np.array([True, True]),
        ),
        _fit(
            "dispersal",
            _dispersal,
            t,
            y,
            [np.array([top, half_way, 5.0]), np.array([top, span / 2, 15.0])],
            np.array([top, span / 10, 5.0]),
            np.array([True, False, True]),
            departs_inside,
        ),
        _fit(
            "migratory",
            _migratory,
            t,
            y,
            [
                np.array([top, half_way, 5.0, max(span / 4, 1.0)]),
                np.array([top, span / 4, 10.0, max(span / 3, 1.0)]),
            ],
            np.array([top, span / 10, 5.0, span / 10]),
            np.array([True, False, True, True]),
            returns_inside,
        ),
    ]
    ranked = sorted(fits, key=lambda f: f.aicc)
    best, second = ranked[0], ranked[1]
    margin = second.aicc - best.aicc
    model = {
        "nomadic": _nomadic,
        "resident": _resident,
        "dispersal": _dispersal,
        "migratory": _migratory,
    }
    curve = [
        [float(d), round(float(v), 4)]
        for d, v in zip(t, model[best.name](t, best.parameters), strict=True)
    ]
    strategy = best.name if margin >= CLEAR_MARGIN else "unclear"
    return Strategy(strategy, None, round(margin, 2), _figures(best), curve, fits)


def _figures(fit: Fit) -> dict[str, float]:
    p = fit.parameters
    if fit.name == "nomadic":
        return {"drift_km2_per_day": round(float(p[0]), 4)}
    if fit.name == "resident":
        return {"range_km": round(math.sqrt(max(float(p[0]), 0.0)), 3)}
    if fit.name == "dispersal":
        return {
            "distance_km": round(math.sqrt(max(float(p[0]), 0.0)), 3),
            "departure_day": round(float(p[1]), 1),
        }
    delta, theta, phi, rho = (float(v) for v in p)
    return {
        "distance_km": round(math.sqrt(max(delta, 0.0)), 3),
        "departure_day": round(theta, 1),
        "return_day": round(theta + 2 * phi + rho, 1),
    }
