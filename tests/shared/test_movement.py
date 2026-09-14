"""Movement from the accelerometer sample of status messages: the change between samples,
the previous sample from the current state, and the health line's words."""

from datetime import UTC, datetime, timedelta

from shared.device_drivers.base import DecodedMeasurement
from shared.domain.movement import (
    MOVEMENT_THRESHOLD_MPS2,
    activity_between,
    derive_activity,
    movement_text,
    previous_sample,
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


def test_the_previous_sample_needs_all_three_axes_at_one_time():
    at = T0.isoformat()
    state = {
        "acceleration_x": {"value": 1.0, "time": at},
        "acceleration_y": {"value": 2.0, "time": at},
        "acceleration_z": {"value": 9.0, "time": at},
        "battery_voltage": {"value": 3.9, "time": at},
    }
    assert previous_sample(state) == ((1.0, 2.0, 9.0), T0)
    assert previous_sample({"acceleration_x": {"value": 1.0, "time": at}}) is None
    assert previous_sample(None) is None
    mixed = dict(
        state, acceleration_z={"value": 9.0, "time": (T0 - timedelta(hours=1)).isoformat()}
    )
    assert previous_sample(mixed) is None


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
    # a replay older than the state's sample gets no activity; the first sample ever neither
    assert derive_activity(_sample(T0 - timedelta(hours=1), 1, 1, 1), previous) == []
    assert derive_activity(_sample(T0, 1, 1, 1), None) == []
    # two samples in one delivery without a state: the second against the first
    two = _sample(T0, 0, 0, 9.8) + _sample(T0 + timedelta(hours=1), 0, 0.5, 9.8)
    assert [m.value for m in derive_activity(two, None)] == [0.5]
    assert 0.5 < MOVEMENT_THRESHOLD_MPS2 < 5


def test_the_health_line_words():
    now = T0
    assert movement_text(None, T0, now) == ("no movement seen yet", None, T0)
    assert movement_text(T0 - timedelta(hours=2), T0, now) == (
        "moving",
        "ok",
        T0 - timedelta(hours=2),
    )
    text, level, _ = movement_text(T0 - timedelta(hours=14), T0, now)
    assert (text, level) == ("still for 14 h", "warn")
    text, level, _ = movement_text(T0 - timedelta(hours=50), T0, now)
    assert (text, level) == ("still for 2 d 2 h", "critical")
