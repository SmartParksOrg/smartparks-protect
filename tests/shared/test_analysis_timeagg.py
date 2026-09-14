"""Sun classes and calendar helpers at known places and dates."""

from datetime import UTC, datetime

import numpy as np

from shared.analysis.primitives.timeagg import local_days, seasons, sun_class, sun_elevation_deg


def _at(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def test_noon_is_day_and_midnight_is_night_in_amersfoort():
    lat, lon = np.array([52.16, 52.16]), np.array([5.39, 5.39])
    times = np.array([_at("2026-06-21T11:00:00+00:00"), _at("2026-06-21T00:30:00+00:00")])
    elevation = sun_elevation_deg(times, lat, lon)
    assert 55 < elevation[0] < 65  # the summer solstice noon at 52 north: about 61 degrees
    assert elevation[1] < -6
    assert list(sun_class(times, lat, lon)) == ["day", "night"]


def test_twilight_sits_between():
    lat, lon = np.array([52.16]), np.array([5.39])
    # civil dusk in Amersfoort on 21 June is about 20:35 UTC
    assert sun_class(np.array([_at("2026-06-21T20:20:00+00:00")]), lat, lon)[0] == "twilight"


def test_local_days_follow_the_project_time_zone():
    moment = datetime(2026, 9, 13, 23, 30, tzinfo=UTC)
    assert (
        local_days(np.array([moment.timestamp()]), "Europe/Amsterdam")[0].isoformat()
        == "2026-09-14"
    )
    assert local_days(np.array([moment.timestamp()]), "UTC")[0].isoformat() == "2026-09-13"


def test_seasons_split_a_window_and_swap_in_the_south():
    north = seasons(
        datetime(2026, 2, 15, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC), "UTC", southern=False
    )
    assert [s[0] for s in north] == ["winter", "spring", "summer"]
    assert north[0][1] == datetime(2026, 2, 15, tzinfo=UTC)
    assert north[1][1].month == 3 and north[1][1].day == 1
    south = seasons(
        datetime(2026, 2, 15, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
        "Africa/Windhoek",
        southern=True,
    )
    assert [s[0] for s in south] == ["summer", "autumn", "winter"]
