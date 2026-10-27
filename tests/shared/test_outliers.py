"""The GNSS outlier rule (decision D221) on synthetic fixes: a jump an animal cannot make is
flagged, scatter over a short interval and a long journey over days are not."""

from datetime import UTC, datetime, timedelta

from shared.domain.outliers import Outlier, agrees, outlier_of

T0 = datetime(2026, 9, 15, 22, 42, tzinfo=UTC)
OKONJIMA = (-20.78273, 16.61707)


def test_a_jump_of_thousands_of_kilometres_in_an_hour_is_an_outlier():
    # SP010403's case: 3,271 km in an hour with 19 m accuracy
    far = (5.18, 52.37)
    outlier = outlier_of((*OKONJIMA, T0), (*far, T0 + timedelta(hours=1)))
    assert outlier is not None
    assert outlier.distance_m > 3_000_000 and outlier.speed_mps > 800
    assert outlier.previous_time == T0
    assert outlier.title().startswith("Fix 8") or "km from the last one in 1.0 h" in outlier.title()
    figures = outlier.attribute(max_speed_mps=50, min_jump_m=1000)
    assert figures["max_speed_mps"] == 50 and figures["previous_time"] == T0.isoformat()


def test_scatter_and_ordinary_movement_are_never_outliers():
    near = (OKONJIMA[0] + 0.004, OKONJIMA[1])  # about 450 m
    # 450 m in ten seconds is 45 m/s, yet under the jump floor: GPS scatter, not an outlier
    assert outlier_of((*OKONJIMA, T0), (*near, T0 + timedelta(seconds=10))) is None
    # 578 m in an hour, the device's usual step
    assert outlier_of((*OKONJIMA, T0), (*near, T0 + timedelta(hours=1))) is None
    # a vehicle on a highway: 150 km in an hour is under 50 m/s
    highway = (OKONJIMA[0] + 1.35, OKONJIMA[1])
    assert outlier_of((*OKONJIMA, T0), (*highway, T0 + timedelta(hours=1))) is None
    # a long journey over days
    far = (5.18, 52.37)
    assert outlier_of((*OKONJIMA, T0), (*far, T0 + timedelta(days=3))) is None
    # a fix at the same moment or earlier is not judged
    assert outlier_of((*OKONJIMA, T0), (*far, T0)) is None
    assert outlier_of((*OKONJIMA, T0), (*far, T0 - timedelta(hours=1))) is None
    # the bounds are the caller's
    assert (
        outlier_of((*OKONJIMA, T0), (*highway, T0 + timedelta(hours=1)), max_speed_mps=30)
        is not None
    )


def test_the_next_fix_confirms_a_flagged_one_and_the_run_is_the_device_s_move():
    """Decision D360: a flagged fix that the fix after it agrees with was a real move."""
    far = (5.18, 52.37)
    flagged = (*far, T0 + timedelta(hours=1))
    first = outlier_of((*OKONJIMA, T0), flagged)
    assert first is not None
    # ten minutes on, a kilometre further: the two agree, the device was carried there
    assert agrees(flagged, (far[0] + 0.01, far[1], T0 + timedelta(hours=1, minutes=10)))
    # back at the old place an hour later: the flagged fix was a wild one
    assert not agrees(flagged, (*OKONJIMA, T0 + timedelta(hours=2)))
    # a fix before the flagged one confirms nothing, nor one at the same moment
    assert not agrees(flagged, (*far, T0))
    assert not agrees(flagged, flagged)
    # the bounds are the caller's: 15 km in ten minutes passes at 50 m/s, not at 20
    onward = (far[0] + 0.135, far[1], T0 + timedelta(hours=1, minutes=10))
    assert agrees(flagged, onward) and not agrees(flagged, onward, max_speed_mps=20)
    title = first.confirmed_title()
    assert title.startswith("Jump of 4853 km") and title.endswith(
        "km in 1.0 h confirmed by the next fix: the device moved"
    )
    back = Outlier.from_attribute(first.attribute(max_speed_mps=50, min_jump_m=1000))
    assert back.previous_time == T0 and round(back.distance_m) == round(first.distance_m)
    assert back.confirmed_title() == title
