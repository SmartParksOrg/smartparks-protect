"""Movement from the accelerometer sample of status messages and from the fixes: the change
between samples, the samples read back from rows, the fixes' bar, and the health line's words."""

from datetime import UTC, datetime, timedelta

from shared.device_drivers.base import DecodedMeasurement
from shared.domain.movement import (
    FIX_MOVEMENT_MIN_M,
    MOVEMENT_THRESHOLD_MPS2,
    SOURCE_ACCELEROMETER,
    SOURCE_POSITIONS,
    activity_between,
    complete_samples,
    derive_activity,
    fix_moved,
    last_movement,
    movement_text,
)

T0 = datetime(2026, 9, 14, 8, tzinfo=UTC)


def _sample(time: datetime, x: float, y: float, z: float) -> list[DecodedMeasurement]:
    return [
        DecodedMeasurement(time=time, metric_key=k, value=v, record_type="status")
        for k, v in (("acceleration_x", x), ("acceleration_y", y), ("acceleration_z", z))
    ]


def test_the_change_of_the_vector():
    assert activity_between((0, 0, 9.8), (0, 0, 9.8)) == 0
    assert activity_between((0, 0, 9.8), (3, 4, 9.8)) == 5
    assert activity_between((1, 1, 1), (1, 1, 2)) == 1


def test_a_sample_needs_all_three_axes_at_one_time():
    later = T0 + timedelta(hours=1)
    rows = [
        (T0, "acceleration_x", 1.0),
        (T0, "acceleration_y", 2.0),
        (T0, "acceleration_z", 9.0),
        (T0, "battery_voltage", 3.9),
        (later, "acceleration_x", 1.0),  # an incomplete sample is no sample
        (later, "acceleration_y", 2.0),
        (later - timedelta(minutes=30), "acceleration_z", True),  # a bool is no number
    ]
    assert complete_samples(rows) == [((1.0, 2.0, 9.0), T0)]
    assert complete_samples([]) == []
    # in time order whatever the order given
    two = [*_sample(later, 0, 0, 9.8), *_sample(T0, 1, 1, 1)]
    assert [t for _, t in complete_samples((m.time, m.metric_key, m.value) for m in two)] == [
        T0,
        later,
    ]


def test_activity_per_sample_in_time_order_against_the_one_before():
    previous = ((0.0, 0.0, 9.8), T0)
    later = _sample(T0 + timedelta(hours=2), 0, 0, 9.8)  # the same posture: still
    earlier = _sample(T0 + timedelta(hours=1), 3, 4, 9.8)  # a move, delivered out of order
    out = derive_activity(later + earlier, previous)
    assert [(m.time, m.value) for m in out] == [
        (T0 + timedelta(hours=1), 5.0),
        (T0 + timedelta(hours=2), 5.0),
    ]
    assert all(m.metric_key == "activity" and m.record_type == "status" for m in out)
    # a sample older than the one before gets no activity; the first sample ever neither
    assert derive_activity(_sample(T0 - timedelta(hours=1), 1, 1, 1), previous) == []
    assert derive_activity(_sample(T0, 1, 1, 1), None) == []
    # two samples in one delivery without a sample before: the second against the first
    two = _sample(T0, 0, 0, 9.8) + _sample(T0 + timedelta(hours=1), 0, 0.5, 9.8)
    assert [m.value for m in derive_activity(two, None)] == [0.5]
    assert 0.5 < MOVEMENT_THRESHOLD_MPS2 < 5


def test_a_fix_moves_when_it_lies_beyond_the_jitter_and_its_own_accuracy():
    """Decision D363: SP051307 parked in Namibia wandered up to 22 m a step; its drive moved
    hundreds of metres between fixes five minutes apart."""
    assert FIX_MOVEMENT_MIN_M == 50
    assert not fix_moved(22.0, None)
    assert not fix_moved(50.0, None)
    assert fix_moved(51.0, 10.0)
    assert fix_moved(400.0, None)
    # a fix whose accuracy is worse than the bar must beat that accuracy
    assert not fix_moved(120.0, 150.0)
    assert fix_moved(160.0, 150.0)


def test_the_newer_of_the_two_sources_is_the_last_movement():
    assert last_movement(None, None) == (None, None)
    assert last_movement(T0, None) == (T0, SOURCE_ACCELEROMETER)
    assert last_movement(None, T0) == (T0, SOURCE_POSITIONS)
    later = T0 + timedelta(hours=3)
    assert last_movement(T0, later) == (later, SOURCE_POSITIONS)
    assert last_movement(later, T0) == (later, SOURCE_ACCELEROMETER)
    # the same moment is the fixes' word, the plainer one
    assert last_movement(T0, T0) == (T0, SOURCE_POSITIONS)


def test_the_health_line_words():
    now = T0
    assert movement_text(None, T0, now) == ("no movement seen yet", None, T0)
    assert movement_text(T0 - timedelta(hours=2), T0, now) == (
        "moving (accelerometer samples)",
        "ok",
        T0 - timedelta(hours=2),
    )
    text, level, _ = movement_text(T0 - timedelta(hours=14), T0, now)
    assert (text, level) == ("still for 14 h (accelerometer samples)", "warn")
    text, level, _ = movement_text(T0 - timedelta(hours=50), T0, now)
    assert (text, level) == ("still for 2 d 2 h (accelerometer samples)", "critical")
    # the fixes showed the device moving three hours ago while the accelerometer saw nothing
    # for twenty (SP051307's drive on 2026-10-28): the line follows the fixes and says so
    text, level, at = movement_text(
        T0 - timedelta(hours=20), T0, now, fix_at=T0 - timedelta(hours=3)
    )
    assert (text, level, at) == ("moving (positions)", "ok", T0 - timedelta(hours=3))
    text, level, _ = movement_text(None, T0, now, fix_at=T0 - timedelta(hours=30))
    assert (text, level) == ("still for 1 d 6 h (positions)", "critical")
