"""The AWT tracker driver (decision D241): the layout AWT's own codec reads, checked against
that codec's output over the fixture frames (`scripts/awt_golden.py`), and the records that
come out."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.device_drivers.awt import AwtDriver, decode_latitude, decode_longitude, parse_frame
from shared.device_drivers.base import SourceEventData
from shared.trace import ApplicationError

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "awt" / "golden.json"
RECEIVED = datetime(2026, 9, 17, 9, tzinfo=UTC)
driver = AwtDriver()


def event(data_hex: str) -> SourceEventData:
    return SourceEventData(
        id=1,
        event_type="uplink",
        payload={"fPort": 1},
        provider_metadata={"f_port": 1},
        network_received_at=RECEIVED,
        ingested_at=RECEIVED,
        device_attributes={},
        device_type_settings={},
        frame=bytes.fromhex(data_hex),
        f_port=1,
    )


def golden_rows() -> list[dict]:
    return json.loads(GOLDEN.read_text())


@pytest.mark.parametrize("row", golden_rows(), ids=lambda r: r["frame"]["note"][:40])
def test_the_driver_reads_what_the_codec_reads(row):
    codec = row["codec"]["data"]
    fields = parse_frame(bytes.fromhex(row["frame"]["data_hex"]))
    assert fields["message_counter"] == codec["messageCounter"]
    assert fields["encrypted"] == (codec["command"] == "Encrypted")
    assert fields["header_crc_ok"] is codec["headerCRC"] is True
    assert fields["payload_crc_ok"] is codec["payloadCRC"] is True
    assert fields["master_tag_id"] == codec["masterTagID"] and fields["tag_id"] == codec["tagID"]
    assert fields["alarms"]["low_battery"] == codec["alarms"]["lowBattery"]
    assert fields["alarms"]["tamper_foil"] == codec["alarms"]["tamperFoil"]
    assert fields["alarms"]["service_coverage"] == codec["alarms"]["serviceCoverage"]
    assert fields["acks"]["humidity_alarm"] == codec["ackRetries"]["humidityAlarm"]
    assert fields["upload_retries"] == codec["ackRetries"]["uploadRetry"]
    assert fields["software_version"] == codec["softwareVersion"]
    assert fields["battery_voltage"] == pytest.approx(codec["batteryVoltage"])
    assert fields["epoch"] == codec["timestamp"]
    # the codec puts every fix south and east; the fixtures lie there, so the two agree
    assert fields["latitude"] == pytest.approx(codec["latitude"], abs=1e-4)
    assert fields["longitude"] == pytest.approx(codec["longitude"], abs=1e-4)
    assert fields["flags"]["alarm"] == codec["alarmFlag"]
    assert fields["flags"]["movement"] == codec["movementFlag"]
    assert fields["flags"]["global_ack"] == codec["globalAck"]
    assert fields["ground_speed_raw"] == codec["groundSpeed"]
    assert fields["accelerometer"] == codec["accelerometer"]
    assert fields["temperature_c"] == codec["temperature"]
    assert fields.get("altitude_m") == codec.get("altitude")
    assert fields.get("light_raw") == codec.get("lightLevel")


def test_the_sign_bits_and_the_hdop_are_read_from_the_words():
    # 24.6541 south with HDOP 2; the codec cannot tell north from south
    south, hdop = decode_latitude(0x80000000 | (2 << 27) | 24_392_460)
    north, _ = decode_latitude((2 << 27) | 24_392_460)
    assert south == pytest.approx(-24.6541, abs=1e-4) and north == pytest.approx(24.6541, abs=1e-4)
    assert hdop == 2
    east, flags = decode_longitude(0x80000000 | 0x20000000 | 25_545_220)
    west, _ = decode_longitude(25_545_220)
    assert east == pytest.approx(25.9087, abs=1e-4) and west == pytest.approx(-25.9087, abs=1e-4)
    assert flags == {"global_ack": False, "movement": True, "alarm": False}


def test_records_position_measurements_status_settings_and_errors():
    rows = golden_rows()
    alarmed = driver.decode(event(rows[1]["frame"]["data_hex"]))
    assert len(alarmed.positions) == 1
    position = alarmed.positions[0]
    assert position.latitude == pytest.approx(-19.0154, abs=1e-4)
    assert position.altitude_m == 940 and position.attributes["hdop"] == 9
    assert position.time == datetime.fromtimestamp(1789600000, tz=UTC)
    metrics = {m.metric_key: m.value for m in alarmed.measurements}
    assert metrics["battery_voltage"] == pytest.approx(3.31)
    assert metrics["device_temperature"] == 41 and metrics["gnss_hdop"] == 9
    status = next(s for s in alarmed.states if s.record_type == "status").state
    assert status["errors"]["low_battery"] and status["errors"]["tamper_foil"]
    assert status["errors"]["humidity_alarm"] and not status["errors"]["memory_full"]
    assert status["firmware_version"] == "43" and status["light_raw"] == 612
    assert status["reporting_interval_s"] == 86400 and status["upload_retries"] == 3
    settings = next(s for s in alarmed.states if s.record_type == "settings").state
    assert settings == {"settings": {"fix_interval": 86400}}
    assert [e.event_type for e in alarmed.events] == ["device_error"]
    assert alarmed.events[0].context["errors"] == ["low_battery", "tamper_foil", "humidity_alarm"]
    # no fix and no clock: no position, network time, a note
    unfixed = driver.decode(event(rows[2]["frame"]["data_hex"]))
    assert unfixed.positions == [] and unfixed.measurements[0].time == RECEIVED
    assert any("before 2015" in note for note in unfixed.notes)
    assert unfixed.events[0].context["errors"] == ["service_coverage"]
    # too short a frame is refused, not half read
    with pytest.raises(ApplicationError):
        driver.decode(event("a5019100" + "00" * 10))
