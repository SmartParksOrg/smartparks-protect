"""A trap from the external switch (phase 32, decision D266): the wiring decides what active
means, a change raises the event, and a reading that says the same as before raises none."""

from datetime import UTC, datetime, timedelta

from shared.device_drivers.base import DecodedMeasurement, DecodedRecords
from shared.domain.trap import closed_when_active, derive_trap, previous_closed

T0 = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def _records(*states: bool) -> DecodedRecords:
    records = DecodedRecords(decoder_version="test")
    for i, state in enumerate(states):
        records.measurements.append(
            DecodedMeasurement(
                time=T0 + timedelta(minutes=i),
                metric_key="switch_active",
                value=state,
                record_type="switch",
            )
        )
    return records


def test_active_means_closed_by_default_and_a_change_is_an_event():
    records = _records(True)
    derive_trap(records, entity_name="Trap 3", wiring_closed_when_active=True, was_closed=False)
    trap = [m for m in records.measurements if m.metric_key == "trap_triggered"]
    assert [m.value for m in trap] == [True]
    assert [(e.event_type, e.title, e.severity) for e in records.events] == [
        ("TRAP_CLOSED", "Trap Trap 3 closed", "warning")
    ]


def test_the_wiring_can_say_the_other_way_round():
    records = _records(True)
    derive_trap(records, entity_name="Trap 3", wiring_closed_when_active=False, was_closed=True)
    assert [m.value for m in records.measurements if m.metric_key == "trap_triggered"] == [False]
    assert [e.event_type for e in records.events] == ["TRAP_OPENED"]


def test_the_same_state_again_is_no_event():
    records = _records(True)
    derive_trap(records, entity_name="Trap 3", wiring_closed_when_active=True, was_closed=True)
    assert records.events == []


def test_the_first_reading_ever_only_speaks_when_it_is_shut():
    quiet = _records(False)
    derive_trap(quiet, entity_name="T", wiring_closed_when_active=True, was_closed=None)
    assert quiet.events == []
    shut = _records(True)
    derive_trap(shut, entity_name="T", wiring_closed_when_active=True, was_closed=None)
    assert [e.event_type for e in shut.events] == ["TRAP_CLOSED"]


def test_a_delivery_with_several_readings_raises_one_event_per_change():
    records = _records(False, True, True, False)
    derive_trap(records, entity_name="T", wiring_closed_when_active=True, was_closed=False)
    assert [e.event_type for e in records.events] == ["TRAP_CLOSED", "TRAP_OPENED"]


def test_the_device_attribute_and_the_current_state_are_read_plainly():
    assert closed_when_active(None) is True
    assert closed_when_active({"trap_closed_when_active": False}) is False
    assert previous_closed({"trap_triggered": {"value": True, "time": "x"}}) is True
    assert previous_closed({"battery_voltage": {"value": 3.6}}) is None
