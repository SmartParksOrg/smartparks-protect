"""A local metric grid over a trajectory, residence time and visits per cell, and what runs in
PostGIS: DBSCAN clusters of a subject's fixes and geodesic areas (plan, section 8.2)."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@dataclass(slots=True)
class Cluster:
    """A DBSCAN cluster of one subject's fixes: its hull in degrees, how many fixes, the share
    of the subject's fixes, and when it was first and last used."""

    hull: dict[str, Any]
    fixes: int
    fix_share: float
    first_at: datetime
    last_at: datetime


def utm_srid(lat: float, lon: float) -> int:
    """The UTM zone's EPSG code for a point, for metric distances in PostGIS."""
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + min(60, max(1, zone))


async def clusters_sql(
    session: AsyncSession,
    entity_id: uuid.UUID,
    time_from: datetime,
    time_to: datetime,
    *,
    eps_m: float,
    min_points: int,
    max_clusters: int,
) -> list[Cluster]:
    """`ST_ClusterDBSCAN` over the subject's device fixes in the period, in the UTM zone of
    their centre; the largest `max_clusters` clusters with their convex hulls in degrees."""
    centre = (
        await session.execute(
            text(
                """
                SELECT ST_Y(ST_Centroid(ST_Collect(coalesce(curated_geom, geom)))) AS lat,
                       ST_X(ST_Centroid(ST_Collect(coalesce(curated_geom, geom)))) AS lon,
                       count(*) AS n
                FROM positions
                WHERE entity_id = :entity_id
                  AND coalesce(curated_time, time) >= :time_from
                  AND coalesce(curated_time, time) < :time_to
                  AND valid AND record_type <> 'network'
                """
            ),
            {"entity_id": entity_id, "time_from": time_from, "time_to": time_to},
        )
    ).one()
    if not centre.n or centre.n < min_points:
        return []
    srid = utm_srid(float(centre.lat), float(centre.lon))
    rows = (
        await session.execute(
            text(
                """
                WITH fixes AS (
                    SELECT ST_Transform(coalesce(curated_geom, geom), CAST(:srid AS integer)) AS g,
                           coalesce(curated_time, time) AS t
                    FROM positions
                    WHERE entity_id = :entity_id
                      AND coalesce(curated_time, time) >= :time_from
                      AND coalesce(curated_time, time) < :time_to
                      AND valid AND record_type <> 'network'
                ),
                labelled AS (
                    SELECT g, t,
                           ST_ClusterDBSCAN(
                               g, eps := CAST(:eps AS float8), minpoints := CAST(:min_points AS integer)
                           ) OVER () AS cid
                    FROM fixes
                )
                SELECT ST_AsGeoJSON(ST_Transform(ST_ConvexHull(ST_Collect(g)), 4326)) AS hull,
                       count(*) AS n, min(t) AS first_at, max(t) AS last_at
                FROM labelled
                WHERE cid IS NOT NULL
                GROUP BY cid
                ORDER BY count(*) DESC
                LIMIT CAST(:max_clusters AS integer)
                """
            ),
            {
                "srid": srid,
                "entity_id": entity_id,
                "time_from": time_from,
                "time_to": time_to,
                "eps": eps_m,
                "min_points": min_points,
                "max_clusters": max_clusters,
            },
        )
    ).all()
    total = int(centre.n)
    return [
        Cluster(
            hull=json.loads(r.hull),
            fixes=int(r.n),
            fix_share=round(int(r.n) / total, 4),
            first_at=r.first_at,
            last_at=r.last_at,
        )
        for r in rows
    ]


async def hectares(session: AsyncSession, geojson: dict[str, Any]) -> float:
    """The geodesic area of a GeoJSON polygon in hectares, from PostGIS."""
    value = await session.scalar(
        text("SELECT ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)::geography) / 10000"),
        {"g": json.dumps(geojson)},
    )
    return float(value or 0)
