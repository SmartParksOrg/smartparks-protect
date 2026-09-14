"""A reboot from the uptime of status messages: the event, the reason, the health note."""

from datetime import UTC, datetime, timedelta

from shared.device_drivers.base import DecodedMeasurement, DecodedState
from shared.domain.reboot import detect_reboots, previous_uptime, reboot_note

T0 = datetime(2026, 9, 14, 8, tzinfo=UTC)


def _uptime(time: datetime, days: float) -> DecodedMeasurement:
    return DecodedMeasurement(
        time=time, metric_key="uptime", value=days * 86400, record_type="status"
    )


def test_an_uptime_lower_than_before_is_a_reboot_with_its_reason():
    state = DecodedState(
        time=T0 + timedelta(hours=1),
        state={"reset_reason": {"pin": False, "watchdog": True}},
        record_type="status",
    )
    events = detect_reboots([_uptime(T0 + timedelta(hours=1), 0)], [state], (5 * 86400, T0))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "device_reset" and event.severity == "warning"
    assert event.title == "Device rebooted (watchdog)"
    assert (
        event.context["uptime_before_seconds"] == 5 * 86400
        and event.context["reset_reason"] == "watchdog"
    )
    # the same uptime, or a higher one, is no reboot; a replay older than the state neither
    assert detect_reboots([_uptime(T0 + timedelta(hours=1), 5)], [], (5 * 86400, T0)) == []
    assert detect_reboots([_uptime(T0 - timedelta(hours=1), 0)], [], (5 * 86400, T0)) == []
    assert detect_reboots([_uptime(T0, 0)], [], None) == []
    # two statuses in one delivery: the second against the first
    two = [_uptime(T0, 3), _uptime(T0 + timedelta(hours=1), 0)]
    assert [e.title for e in detect_reboots(two, [], None)] == ["Device rebooted"]


def test_the_previous_uptime_comes_from_the_current_state():
    at = T0.isoformat()
    assert previous_uptime({"uptime": {"value": 432000, "time": at}}) == (432000.0, T0)
    assert previous_uptime({"battery_voltage": {"value": 3.9, "time": at}}) is None
    assert previous_uptime(None) is None


def test_the_uptime_line_warns_for_a_day_after_a_reboot():
    now = T0
    state = {"reset_reason": {"software": True, "watchdog": False}}
    assert reboot_note(now - timedelta(hours=2), state, now) == (
        "rebooted 2 h ago (software)",
        "warn",
    )
    assert reboot_note(now - timedelta(minutes=20), {}, now) == (
        "rebooted less than an hour ago",
        "warn",
    )
    assert reboot_note(now - timedelta(hours=30), state, now) == (None, None)
    assert reboot_note(None, state, now) == (None, None)


def test_a_wrap_of_the_uptime_counter_is_no_reboot():
    """An OpenCollar uptime byte goes from 255 back to 0 without a reboot (Tim, 2026-09-14)."""
    wrap = 255 * 3600  # hours on firmware before 4.0.1
    from_255 = detect_reboots([_uptime(T0 + timedelta(hours=1), 0)], [], (255 * 3600, T0), wrap)
    assert from_255 == []
    from_200 = detect_reboots([_uptime(T0 + timedelta(hours=1), 0)], [], (200 * 3600, T0), wrap)
    assert len(from_200) == 1
    # without a wrap known, every drop is a reboot
    assert len(detect_reboots([_uptime(T0 + timedelta(hours=1), 0)], [], (255 * 3600, T0))) == 1
