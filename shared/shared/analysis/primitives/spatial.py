"""A local metric grid over a trajectory, residence time and visits per cell (plan, section
8.2). Containment in polygons and clustering run in PostGIS and live with the modules."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from shared.analysis.primitives.trajectory import Trajectory

M_PER_DEG_LAT = 111_320.0


@dataclass(slots=True)
class LocalGrid:
    """Square cells of `cell_m` metres on a plane tangent at the mean latitude: good enough
    for the tens of kilometres a park spans."""

    origin_lat: float
    origin_lon: float
    cell_m: float
    m_per_deg_lon: float = field(init=False)

    def __post_init__(self) -> None:
        self.m_per_deg_lon = M_PER_DEG_LAT * max(0.05, math.cos(math.radians(self.origin_lat)))

    @classmethod
    def around(cls, trajectory: Trajectory, cell_m: float) -> LocalGrid:
        return cls(
            float(np.mean(trajectory.lat)) if len(trajectory) else 0.0,
            float(np.mean(trajectory.lon)) if len(trajectory) else 0.0,
            cell_m,
        )

    def cells_of(
        self, lat: NDArray[np.float64], lon: NDArray[np.float64]
    ) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        ix = np.floor((lon - self.origin_lon) * self.m_per_deg_lon / self.cell_m).astype(np.int64)
        iy = np.floor((lat - self.origin_lat) * M_PER_DEG_LAT / self.cell_m).astype(np.int64)
        return ix, iy

    def polygon(self, ix: int, iy: int) -> list[list[float]]:
        """The cell as a closed ring of (lon, lat), for a GeoJSON polygon."""
        x0 = self.origin_lon + ix * self.cell_m / self.m_per_deg_lon
        x1 = self.origin_lon + (ix + 1) * self.cell_m / self.m_per_deg_lon
        y0 = self.origin_lat + iy * self.cell_m / M_PER_DEG_LAT
        y1 = self.origin_lat + (iy + 1) * self.cell_m / M_PER_DEG_LAT
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


@dataclass(slots=True)
class CellUse:
    ix: int
    iy: int
    seconds: float = 0.0
    visits: int = 0
    first_s: float = math.inf
    last_s: float = -math.inf


def residence(
    trajectory: Trajectory,
    weights: NDArray[np.float64],
    grid: LocalGrid,
    min_absence_s: float,
) -> dict[tuple[int, int], CellUse]:
    """Time per cell from the fixes' weights, and visits: a new visit starts when the subject
    returns after more than `min_absence_s` away from the cell."""
    out: dict[tuple[int, int], CellUse] = {}
    if len(trajectory) == 0:
        return out
    ix, iy = grid.cells_of(trajectory.lat, trajectory.lon)
    for i in range(len(trajectory)):
        key = (int(ix[i]), int(iy[i]))
        t = float(trajectory.times[i])
        use = out.get(key)
        if use is None:
            use = CellUse(key[0], key[1])
            out[key] = use
        if use.last_s == -math.inf or t - use.last_s > min_absence_s:
            use.visits += 1
        use.seconds += float(weights[i])
        use.first_s = min(use.first_s, t)
        use.last_s = max(use.last_s, t)
    return out


def hotspots(
    cells: dict[tuple[int, int], CellUse], share: float
) -> list[tuple[tuple[int, int], CellUse]]:
    """The cells that together hold `share` of the time, busiest first."""
    ordered = sorted(cells.items(), key=lambda kv: kv[1].seconds, reverse=True)
    total = sum(c.seconds for _, c in ordered)
    if total <= 0:
        return []
    out = []
    held = 0.0
    for key, cell in ordered:
        out.append((key, cell))
        held += cell.seconds
        if held / total >= share:
            break
    return out
