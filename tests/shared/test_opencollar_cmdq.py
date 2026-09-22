"""The cardiac tag (CMDQ) records of port 15 (phase 34, decisions D282 and D283).

The golden test covers the 15 byte records of firmware 6.9.0 and later, because every vendored
reference decoder assumes that length. The 13 byte records of firmware 6.1 to 6.8 have no
vendored decoder, so they are checked here against the values the firmware's own
`app/src/bt_module/bt_cmdq/README.md` prints for its two examples.
"""

from datetime import UTC, datetime

import pytest

from shared.device_drivers.base import SourceEventData
from shared.device_drivers.opencollar import OpenCollarDriver

RECEIVED = datetime(2026, 9, 22, 12, tzinfo=UTC)
driver = OpenCollarDriver()

# `bt_cmdq/README.md`, "Example of a message with 1 successful detection", without its port byte.
ONE_DETECTION = "fc0d58f3cd65000000000006bc0ff0"
TWO_DETECTIONS = "fc1a58f3cd65000000000006bc0ff070f4cd65000000000006bc0ff0"
EMPTY_REPORT = "fc00"


def decode(data_hex: str, firmware: str):
    return driver.decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload={"fPort": 15},
            provider_metadata={"f_port": 15},
            network_received_at=RECEIVED,
            ingested_at=RECEIVED,
            device_attributes={},
            device_type_settings={},
            frame=bytes.fromhex(data_hex),
            f_port=15,
            firmware_version=firmware,
        )
    )


def by_time(records) -> dict[int, dict[str, float]]:
    grouped: dict[int, dict[str, float]] = {}
    for measurement in records.measurements:
        grouped.setdefault(int(measurement.time.timestamp()), {})[measurement.metric_key] = (
            measurement.value
        )
    return grouped


def test_thirteen_byte_record_matches_the_firmware_readme() -> None:
    """The README's own parsed output: timestamp 1707995992, raw_temp 1724, impedance 4080, and
    every cardiac field zero. Firmware 6.5 sends no HRV, so none is written."""
    readings = by_time(decode(ONE_DETECTION, "6.5"))
    assert list(readings) == [1707995992]
    reading = readings[1707995992]
    assert reading["cmdq_rr_median"] == 0
    assert reading["cmdq_rr_median_modesum"] == 0
    assert reading["cmdq_activity_average"] == 0
    assert reading["cmdq_activity_max"] == 0
    assert reading["cmdq_active_min_in_last_hour"] == 0
    assert reading["cmdq_raw_temperature"] == 1724
    assert reading["cmdq_impedance"] == 4080
    assert reading["cmdq_success"] is True
    assert reading["cmdq_temperature"] == pytest.approx(1724 * 0.0248 - 18.09, abs=0.001)
    # the tag was heard, the heart was not: no heart rate is invented for a zero R-R median
    assert "heart_rate" not in reading
    assert "heart_rate_variability" not in reading
    assert "cmdq_hrv_raw" not in reading


def test_two_detections_are_two_readings_at_their_own_times() -> None:
    readings = by_time(decode(TWO_DETECTIONS, "6.5"))
    assert list(readings) == [1707995992, 1707996272]


def test_every_record_carries_the_device_clock() -> None:
    """The timestamp is the collar's own `get_global_unix_time()` at the scan, so the clock
    rules of D119 and D259 apply to it the way they do to a scan's contacts."""
    records = decode(TWO_DETECTIONS, "6.5")
    assert records.measurements
    assert all(m.device_clock for m in records.measurements)
    assert all(m.record_type == "cmdq" for m in records.measurements)


def test_an_empty_report_is_a_note_and_no_measurement() -> None:
    records = decode(EMPTY_REPORT, "6.5")
    assert not records.measurements
    assert records.notes == ["no cardiac detection in the reporting interval"]


def test_a_firmware_without_the_tag_says_so_and_keeps_the_delivery() -> None:
    """Firmware 4.x has no CMDQ module at all, so port 15 is not in its catalogue. The frame is
    data, not a fault: a note on the trace and the source event kept (decision D100)."""
    records = decode(ONE_DETECTION, "4.4")
    assert not records.measurements
    assert records.notes and "not in the fw4.4.3 catalogue" in records.notes[0]


def test_a_tail_that_is_not_a_whole_record_is_noted_and_the_rest_kept() -> None:
    """A frame whose length is not a multiple of the record length still holds whole records in
    front of the tail. Reading them at the right offsets matters more than refusing the lot."""
    truncated = "fc11" + "58f3cd65000000000006bc0ff0" + "70f4cd65"  # 13 bytes and a stub
    records = decode(truncated, "6.5")
    assert list(by_time(records)) == [1707995992]
    assert records.notes and "not a whole number of 13 byte records" in records.notes[0]


def test_fifteen_byte_records_carry_hrv_and_a_heart_rate() -> None:
    """The built fixture of `uplinks.jsonl`: 75 tens of milliseconds between R peaks is 80 bpm,
    and an HRV of 2025 is an RMSSD of 45 ms."""
    frame = (
        "fc2dc09ba26a4b0c03091108ea0ff007e9749ca26a3c0e15402609020fe00384289da26a"
        "0000000000000000000000"
    )
    readings = by_time(decode(frame, "7.2"))
    first = readings[1789041600]
    assert first["heart_rate"] == pytest.approx(80.0)
    assert first["heart_rate_variability"] == pytest.approx(45.0)
    assert first["cmdq_hrv_raw"] == 2025
    # the third sighting heard the tag and nothing else
    last = readings[1789041960]
    assert last["cmdq_success"] is False
    assert "heart_rate" not in last and "cmdq_temperature" not in last
    # nor a variability of zero, which would be a heart beating perfectly evenly
    assert "heart_rate_variability" not in last
    assert last["cmdq_hrv_raw"] == 0
