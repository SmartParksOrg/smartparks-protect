"""Time helpers both modules use (plan, section 8.2): day and night by the sun's elevation, the
calendar day of a moment in the project's time zone, and the seasons of a window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

SUN_CLASSES = ("day", "twilight", "night")


def sun_elevation_deg(
    times_s: NDArray[np.float64], lat: NDArray[np.float64], lon: NDArray[np.float64]
) -> NDArray[np.float64]:
    """The sun's elevation above the horizon, in degrees, by the NOAA approximation: within
    a degree, enough to tell day from night."""
    days = times_s / 86_400.0
    doy = (days % 365.25) + 1  # close enough for the declination's yearly swing
    hour = (times_s % 86_400.0) / 3_600.0
    gamma = 2 * np.pi / 365.0 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2 * gamma)
        - 0.040849 * np.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2 * gamma)
        + 0.000907 * np.sin(2 * gamma)
        - 0.002697 * np.cos(3 * gamma)
        + 0.00148 * np.sin(3 * gamma)
    )
    tst = hour * 60 + eqtime + 4 * lon
    ha = np.radians(tst / 4 - 180)
    phi = np.radians(lat)
    cos_zenith = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(ha)
    out: NDArray[np.float64] = 90 - np.degrees(np.arccos(np.clip(cos_zenith, -1, 1)))
    return out


def sun_class(
    times_s: NDArray[np.float64], lat: NDArray[np.float64], lon: NDArray[np.float64]
) -> NDArray[np.str_]:
    """`day` above the horizon, `night` below civil twilight (6 degrees under), `twilight`
    between."""
    elevation = sun_elevation_deg(times_s, lat, lon)
    out = np.full(elevation.shape, "twilight", dtype="<U8")
    out[elevation > 0] = "day"
    out[elevation < -6] = "night"
    return out


def local_day(moment: datetime, tz: str) -> date:
    return moment.astimezone(ZoneInfo(tz)).date()


def local_days(times_s: NDArray[np.float64], tz: str) -> list[date]:
    zone = ZoneInfo(tz)
    return [datetime.fromtimestamp(float(t), tz=UTC).astimezone(zone).date() for t in times_s]


def seasons(
    time_from: datetime, time_to: datetime, tz: str, southern: bool
) -> list[tuple[str, datetime, datetime]]:
    """The meteorological seasons the window touches, in the project's time zone, clipped to
    the window: (name, from, to). December starts winter in the north and summer in the south."""
    zone = ZoneInfo(tz)
    names_north = {
        12: "winter",
        1: "winter",
        2: "winter",
        3: "spring",
        4: "spring",
        5: "spring",
        6: "summer",
        7: "summer",
        8: "summer",
        9: "autumn",
        10: "autumn",
        11: "autumn",
    }
    swap = {"winter": "summer", "summer": "winter", "spring": "autumn", "autumn": "spring"}
    start = time_from.astimezone(zone)
    end = time_to.astimezone(zone)
    out: list[tuple[str, datetime, datetime]] = []
    cursor = start
    while cursor < end:
        month = cursor.month
        first_month = ((month - 12) // 3 * 3 + 12) % 12 or 12  # 12, 3, 6, 9
        season_start = cursor.replace(
            month=first_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if first_month == 12 and month < 12:
            season_start = season_start.replace(year=cursor.year - 1)
        next_start = (season_start + timedelta(days=93)).replace(day=1)
        name = names_north[first_month]
        if southern:
            name = swap[name]
        out.append((name, max(cursor, start), min(next_start, end)))
        cursor = next_start
    return out
