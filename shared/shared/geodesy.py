"""Distances and bearings on the sphere, shared by the rule evaluator, the satellite module
and the analysis primitives. A mean earth radius is enough for the distances a park holds."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two points given as latitude and longitude."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The same for two (longitude, latitude) points, the order GeoJSON uses."""
    return haversine_m(a[1], a[0], b[1], b[0])


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """The initial bearing from the first point to the second, 0 to 360 degrees clockwise
    from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    x = math.sin(dlmb) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(x, y)) + 360) % 360
