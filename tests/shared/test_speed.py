"""The speed and course a fix carries become measurements (phase 37): `speed` for every fix
that reports one, `heading` only while moving, at the fix's own time and record type."""

from datetime import UTC, datetime

from shared.device_drivers.base import DecodedPosition
from shared.domain.speed import speed_measurements

AT = datetime(2026, 9, 25, 15, 15, tzinfo=UTC)


def _fix(speed: float | None, heading: float | None, record_type: str = "gnss") -> DecodedPosition:
    return DecodedPosition(
        time=AT,
        latitude=51.5,
        longitude=3.8,
        record_type=record_type,
        speed_mps=speed,
        heading_deg=heading,
    )


def test_a_moving_fix_writes_speed_and_course():
    out = speed_measurements([_fix(12.0, 52.5)])
    assert [(m.metric_key, m.value, m.record_type, m.time) for m in out] == [
        ("speed", 12.0, "gnss", AT),
        ("heading", 52.5, "gnss", AT),
    ]


def test_a_standstill_writes_the_speed_and_no_course():
    out = speed_measurements([_fix(0.0, 180.0)])
    assert [(m.metric_key, m.value) for m in out] == [("speed", 0.0)]


def test_a_fix_without_speed_writes_nothing_and_a_course_is_normalised():
    assert speed_measurements([_fix(None, 90.0), _fix(None, None)]) == []
    out = speed_measurements([_fix(3.0, -10.0, record_type="position")])
    assert [(m.metric_key, m.value, m.record_type) for m in out] == [
        ("speed", 3.0, "position"),
        ("heading", 350.0, "position"),
    ]
