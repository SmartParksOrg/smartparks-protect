"""Golden tests over the wiki examples. Expected values are the public decoder's output."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.device_drivers.base import SourceEventData, canonical_key
from shared.device_drivers.opencollar import OpenCollarDriver
from shared.device_drivers.registry import DRIVERS
from shared.enums import ErrorCode
from shared.trace import ApplicationError

FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "opencollar" / "uplinks.jsonl"
)
RECEIVED = datetime(2023, 11, 30, 10, 0, tzinfo=UTC)
driver = OpenCollarDriver()


def load() -> dict[int, dict]:
    return {
        row["f_port"]: row
        for row in (json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip())
    }


def event(port: int, hex_data: str) -> SourceEventData:
    frame = bytes.fromhex(hex_data)
    return SourceEventData(
        id=1,
        event_type="uplink",
        payload={"fPort": port},
        provider_metadata={"f_port": port},
        network_received_at=RECEIVED,
        ingested_at=RECEIVED,
        device_attributes={},
        device_type_settings={},
        frame=frame,
        f_port=port,
    )


def test_registered():
    assert DRIVERS["opencollar"].key == "opencollar"


def test_port_2_position_matches_the_public_decoder():
    row = load()[2]
    records = driver.decode(event(2, row["data_hex"]))
    assert len(records.positions) == 1
    position = records.positions[0]
    expected = row["expected"]
    assert position.latitude == pytest.approx(expected["latitude"], abs=1e-7)
    assert position.longitude == pytest.approx(expected["longitude"], abs=1e-7)
    assert position.altitude_m == pytest.approx(expected["altitude"], abs=1e-3)
    assert position.time == datetime.fromtimestamp(expected["fix_time"], tz=UTC)
    assert position.satellites == expected["SIV"] and position.accuracy_m == expected["h_acc_est"]
    assert (
        position.attributes["fix_type"] == expected["fixType"]
        and position.attributes["pdop"] == expected["pDOP"]
    )
    metrics = {m.metric_key: m.value for m in records.measurements}
    assert metrics["gnss_fix"] is True and metrics["gnss_time_to_fix"] == expected["ttf"]


def test_port_4_status():
    row = load()[4]
    records = driver.decode(event(4, row["data_hex"]))
    metrics = {m.metric_key: m.value for m in records.measurements}
    assert metrics["battery_voltage"] == pytest.approx(row["expected"]["bat"] / 1000)
    assert metrics["device_temperature"] == pytest.approx(row["expected"]["temp"], abs=0.01)
    assert metrics["acceleration_z"] == pytest.approx(row["expected"]["acc_z"], abs=0.01)
    assert "charging_voltage" not in metrics
    state = records.states[0].state
    assert state["firmware_version"] == "4.4" and state["hardware_version"] == "1.4"
    assert state["hardware_type"] == "rangeredge" and state["firmware_type"] == "rangeredge"
    assert state["reset_reason"]["software"] is True and not any(state["errors"].values())
    assert records.events == []
    assert records.measurements[0].time == RECEIVED  # status has no clock: network time


def test_port_13_short_position():
    row = load()[13]
    records = driver.decode(event(13, row["data_hex"]))
    position = records.positions[0]
    assert position.time == datetime.fromtimestamp(row["expected"]["fix_timestamp"], tz=UTC)
    assert position.latitude == pytest.approx(row["expected"]["latitude"], abs=1e-7)
    assert position.accuracy_m == row["expected"]["h_acc_est"]


def test_port_16_resend_has_the_same_canonical_key_as_the_original():
    import uuid

    row = load()[13]
    original = driver.decode(event(13, row["data_hex"])).positions[0]
    resend_hex = "95" + row["data_hex"][2:]
    resend = driver.decode(event(16, resend_hex)).positions[0]
    device = uuid.uuid4()
    assert canonical_key(device, original.time, original.record_type) == canonical_key(
        device, resend.time, resend.record_type
    )
    assert resend.attributes["resend"] is True


def test_port_29_flash_log_yields_positions_at_their_fix_time():
    row = load()[29]
    records = driver.decode(event(29, row["data_hex"]))
    assert len(records.positions) == row["expected"]["records"]
    assert records.positions[0].time == datetime.fromtimestamp(
        row["expected"]["first_fix_timestamp"], tz=UTC
    )
    assert records.positions[-1].time == datetime.fromtimestamp(
        row["expected"]["last_fix_timestamp"], tz=UTC
    )
    assert all(p.attributes["via"] == "flash_log" for p in records.positions)
    # a stored status record uses the store timestamp
    status = bytes.fromhex("04" + load()[4]["data_hex"]) + (1701339971).to_bytes(4, "little")
    stored = driver.decode(event(29, status.hex()))
    assert stored.measurements[0].time == datetime.fromtimestamp(1701339971, tz=UTC)


def test_flash_status_fence_and_not_canonical_ports():
    rows = load()
    flash = {
        m.metric_key: m.value for m in driver.decode(event(14, rows[14]["data_hex"])).measurements
    }
    assert flash == {"flash_used_percent": 0, "flash_messages": 16}
    fence = driver.decode(event(12, rows[12]["data_hex"]))
    assert {m.metric_key for m in fence.measurements} == {
        "fence_voltage",
        "fence_pulse_count",
        "fence_energy",
    }
    assert driver.decode(event(5, rows[5]["data_hex"])).empty


def test_no_fix_yields_no_position_but_a_false_gnss_fix():
    no_fix = (
        "f21e"
        + "00"
        + "0000"
        + "1000"
        + "00000000"
        + "00000000"
        + "00000000"
        + "00"
        + "00"
        + "0000"
        + "00"
        + "00000000"
        + "00"
        + "000000"
    )
    records = driver.decode(event(2, no_fix))
    assert records.positions == []
    assert {m.metric_key: m.value for m in records.measurements}["gnss_fix"] is False


def test_switch_timestamp_and_command_confirmation():
    change = driver.decode(event(19, "9805" + "01" + (2500).to_bytes(4, "little").hex()))
    assert (
        change.events[0].event_type == "switch_activated"
        and change.events[0].context["previous_period_seconds"] == 2.5
    )
    status = {
        m.metric_key: m.value
        for m in driver.decode(
            event(20, "9905" + "02" + (7).to_bytes(4, "little").hex())
        ).measurements
    }
    assert status == {"switch_count": 7}
    clock = driver.decode(event(18, "9704" + (1701339971).to_bytes(4, "little").hex()))
    assert clock.states[0].state["device_time"] == 1701339971
    confirm = driver.decode(event(31, "f302a401"))
    assert confirm.states[0].state["last_command"] == {"id": 0xA4, "executed": True}


def test_unknown_and_legacy_ports_are_notes_not_failures():
    """A port the catalogue does not know (research 3.23) keeps the source event and says so
    on the trace; a KPN collar on firmware 6.x still sends the Modem-E message on port 199."""
    unknown = driver.decode(event(99, "0102"))
    assert unknown.empty and unknown.notes == ["port 99 is not in the fw7.2.0 catalogue"]
    legacy = driver.decode(event(199, "000a011700038004d904054c00064c00"))
    assert legacy.empty and legacy.notes[0].startswith(
        "port 199 is not in the fw7.2.0 catalogue: the legacy Modem-E info message"
    )


def test_bad_frames_are_decode_failures():
    for port, hex_data in ((2, "f21d00"), (4, "f20e" + "00" * 14), (2, "f21e0100")):
        with pytest.raises(ApplicationError) as excinfo:
            driver.decode(event(port, hex_data))
        assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED
    with pytest.raises(ApplicationError):
        driver.decode(
            SourceEventData(
                id=1,
                event_type="uplink",
                payload={},
                provider_metadata={},
                network_received_at=RECEIVED,
                ingested_at=RECEIVED,
                device_attributes={},
                device_type_settings={},
            )
        )


def test_simulator_frames_decode_to_positions_and_status():
    """The quick start relies on the simulator's synthetic frames being real OpenCollar messages."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "simulate_opencollar", Path(__file__).parents[2] / "scripts/simulate_opencollar.py"
    )
    simulator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(simulator)
    items = simulator.synthetic(10, -24.9, 31.5, 60.0)
    assert [i["f_port"] for i in items].count(2) == 10 and [i["f_port"] for i in items].count(
        4
    ) == 2
    driver = OpenCollarDriver()
    positions = []
    status_metrics = set()
    for item in items:
        records = driver.decode(event(item["f_port"], item["data_hex"]))
        positions += records.positions
        status_metrics |= {m.metric_key for m in records.measurements if m.record_type == "status"}
    assert len(positions) == 10
    assert all(abs(p.latitude + 24.9) < 0.02 and abs(p.longitude - 31.5) < 0.02 for p in positions)
    assert positions[0].time < positions[-1].time and positions[-1].speed_mps is not None
    assert {"battery_voltage", "device_temperature"} <= status_metrics


# Multi-path deliveries (architecture 25, phase 11): the same frames over WebBLE, from a raw
# log file and over Iridium.


def channel_event(channel: str, hex_data: str) -> SourceEventData:
    return SourceEventData(
        id=2,
        event_type="uplink",
        payload={"data_hex": hex_data},
        provider_metadata={},
        network_received_at=None,
        ingested_at=RECEIVED,
        device_attributes={},
        device_type_settings={},
        frame=bytes.fromhex(hex_data),
        f_port=None,
        acquisition_channel=channel,
    )


def test_ble_status_frame_carries_the_port_in_front():
    row = load()[4]
    records = driver.decode(channel_event("webble", "04" + row["data_hex"]))
    assert {m.metric_key for m in records.measurements} >= {"battery_voltage", "device_temperature"}
    assert records.states[0].state["via"] == "webble"


def test_log_file_line_and_satellite_buffer_decode_like_a_flash_log():
    row = load()[29]
    over_lorawan = driver.decode(event(29, row["data_hex"]))
    from_file = driver.decode(channel_event("log_file", "1d" + row["data_hex"]))
    over_iridium = driver.decode(channel_event("iridium", row["data_hex"]))
    times = [p.time for p in over_lorawan.positions]
    assert len(times) == 10  # the wiki example holds ten stored short positions
    assert [p.time for p in from_file.positions] == times
    assert [p.time for p in over_iridium.positions] == times
    assert {p.attributes["via"] for p in from_file.positions} == {"flash_log"}
    device_id = uuid.uuid4()
    assert {canonical_key(device_id, p.time, "gnss") for p in from_file.positions} == {
        canonical_key(device_id, p.time, "gnss") for p in over_lorawan.positions
    }


def test_short_channel_frames_are_decode_failures():
    with pytest.raises(ApplicationError) as excinfo:
        driver.decode(channel_event("webble", "04"))
    assert excinfo.value.code == ErrorCode.PAYLOAD_DECODE_FAILED
    with pytest.raises(ApplicationError):
        driver.decode(channel_event("iridium", "0d93"))


def test_catalog_lists_the_protocol_tables():
    catalog = OpenCollarDriver.catalog()
    settings = {s["name"]: s for s in catalog["settings"]}
    assert settings["ublox_send_interval"] == {
        "id": 2,
        "name": "ublox_send_interval",
        "length": 4,
        "type": "uint32",
        "default": 0,
        "min": 0,
        "max": 172800,
    }
    assert len(settings) == 123
    commands = {c["name"]: c for c in catalog["commands"]}
    assert commands["cmd_flash_get_all"]["id"] == 0xBB
    assert commands["cmd_flash_get_from_head"]["argument_length"] == 12
    assert catalog["firmware"] == "7.3.0"


def test_live_chirpstack_status_uplink_matches_chirpstacks_decoder():
    """The first recorded live uplink (collar SP051307 over chirpstack-dev4, 2026-09-05): our
    driver and ChirpStack's JavaScript decoder read the same frame the same way."""
    import base64

    from shared.connectivity.adapters.chirpstack import parse_event

    fixture = FIXTURES.parent.parent / "chirpstack" / "up_opencollar_status_live.json"
    payload = json.loads(fixture.read_text())
    from shared.connectivity.base import AdapterCapabilities, DataSourceContext

    source = DataSourceContext(
        id=uuid.uuid4(),
        name="chirpstack-dev4",
        adapter_key="chirpstack",
        config={},
        credentials={},
        capabilities=AdapterCapabilities(uplink=True),
    )
    message = parse_event(source, "application/-/device/-/event/up", json.dumps(payload).encode())
    assert message.external_id == "0016C001F01192A0" and message.event_type == "uplink"
    assert message.provider_metadata["f_port"] == 4 and message.gateway_receptions[0].rssi == -82
    frame = base64.b64decode(payload["data"])
    records = driver.decode(event(4, frame.hex()))
    theirs = payload["object"]
    metrics = {m.metric_key: m.value for m in records.measurements}
    assert metrics["battery_voltage"] == pytest.approx(theirs["bat"] / 1000)
    assert metrics["device_temperature"] == pytest.approx(theirs["temp"], abs=0.01)
    assert metrics["acceleration_z"] == pytest.approx(theirs["acc_z"], abs=0.01)
    assert metrics["uptime"] == theirs["uptime"] * 86400  # days in the firmware
    state = records.states[0].state
    assert state["firmware_version"] == "7.2" and state["hardware_version"] == "1.8"
    assert state["reset_reason"]["software"] is True  # ChirpStack's reset 4
    assert not any(state["errors"].values())


# Firmware layouts (decision D100, ADR 0021)


def test_layout_selection_follows_the_reported_firmware():
    from shared.device_drivers.opencollar import LAYOUTS, layout_for, parse_firmware

    assert layout_for(None).key == "fw7.2.0"
    assert layout_for("7.3").key == "fw7.2.0" and layout_for("7.1").key == "fw7.2.0"
    assert layout_for("6.15").key == "fw6.15.1"
    assert layout_for("6.0").key == "fw6.15.1"  # 6.16 reports as 6.0 (the minor nibble)
    assert layout_for("6.14").key == "fw6.11.2" and layout_for("6.9").key == "fw6.11.2"
    assert layout_for("6.8").key == "fw6.5.0" and layout_for("6.1").key == "fw6.5.0"
    assert layout_for("4.4").key == "fw4.4.3" and layout_for("v5.2").key == "fw4.4.3"
    assert parse_firmware("garbage") is None and layout_for("garbage").key == "fw7.2.0"
    by_key = {layout.key: layout for layout in LAYOUTS}
    assert 21 in by_key["fw7.2.0"].ports and 8 not in by_key["fw7.2.0"].ports
    assert {8, 17, 18, 19, 20} <= set(by_key["fw6.15.1"].ports) and 21 not in by_key[
        "fw6.15.1"
    ].ports
    assert 18 not in by_key["fw6.11.2"].ports and 15 in by_key["fw6.11.2"].ports
    assert 15 not in by_key["fw4.4.3"].ports and by_key["fw6.5.0"].cmdq_record_length == 13


def firmware_event(port: int, hex_data: str, firmware: str | None) -> SourceEventData:
    from dataclasses import replace

    return replace(event(port, hex_data), firmware_version=firmware)


def test_ports_decode_or_note_per_layout():
    """Port 21 is air quality from 7.2; up to 6.16 it is not a message. Port 8 is the RF scanner
    up to 6.16; from 7.1 it is not a message. The note names the layout and the firmware."""
    # BME690 only: five little-endian floats (IAQ 25, 21.5 °C, 1013.2 hPa, 45 %, 120000 Ω)
    import struct

    bme = struct.pack("<5f", 25.0, 21.5, 1013.2, 45.0, 120000.0)
    frame = bytes([0x9A, len(bme)]) + bme
    new = driver.decode(firmware_event(21, frame.hex(), "7.2"))
    values = {m.metric_key: m.value for m in new.measurements}
    assert new.decoder_version == "fw7.2.0"
    assert values["air_q_iaq"] == 25.0 and values["air_q_pressure"] == 1013.2
    assert values["air_q_humidity"] == 45.0 and values["air_q_raw_gas"] == 120000.0
    old = driver.decode(firmware_event(21, frame.hex(), "6.15"))
    assert old.empty and old.decoder_version == "fw6.15.1"
    assert old.notes == [
        "port 21 is not in the fw6.15.1 catalogue: the air quality message of firmware 7.2.0 and later"
    ]
    # both sensors: BMV080 (six floats and the obstruction byte) then BME690
    bmv = struct.pack("<6f", 3.5, 2.0, 5.5, 40.0, 30.0, 45.0) + b"\x01"
    both = bytes([0x9A, len(bmv + bme)]) + bmv + bme
    values = {
        m.metric_key: m.value
        for m in driver.decode(firmware_event(21, both.hex(), "7.3")).measurements
    }
    assert values["air_q_pm2_5_mass"] == 3.5 and values["air_q_obstructed"] is True
    assert values["air_q_temperature"] == 21.5

    # an RF scan on an old collar: version 1, alert, one band 868.0 to 868.6 MHz, 3 peaks, -95 dBm
    scan = bytes([0xFB, 8, 1, 1]) + struct.pack("<HH", 8680, 8686) + bytes([3, 95])
    legacy = driver.decode(firmware_event(8, scan.hex(), "6.15"))
    assert legacy.decoder_version == "fw6.15.1" and legacy.states[0].record_type == "rf_scan"
    band = legacy.states[0].state["rf_scan"]["bands"][0]
    assert band == {"start_mhz": 868.0, "stop_mhz": 868.6, "peak_count": 3, "max_rssi": -95}
    assert legacy.states[0].state["rf_scan"]["should_alert"] is True
    modern = driver.decode(firmware_event(8, scan.hex(), "7.2"))
    assert modern.empty and modern.notes[0].startswith("port 8 is not in the fw7.2.0 catalogue")
    # open sky detection has no message id byte: length then negated RSSI pairs
    sky = driver.decode(firmware_event(17, bytes([0x00, 4, 90, 80, 95, 85]).hex(), "6.11"))
    assert sky.states[0].state["open_sky"] == [
        {"average_rssi": -90, "max_rssi": -80},
        {"average_rssi": -95, "max_rssi": -85},
    ]


def test_status_feature_bit_two_is_the_rf_scanner_before_seven():
    row = load()[4]
    with_bit = bytearray(bytes.fromhex(row["data_hex"]))
    with_bit[2 + 13] |= 2  # features byte is the last of the 14 data bytes
    old = driver.decode(firmware_event(4, with_bit.hex(), "6.15"))
    assert old.states[0].state["rf_scan_enabled"] is True
    new = driver.decode(firmware_event(4, with_bit.hex(), "7.2"))
    assert "rf_scan_enabled" not in new.states[0].state


def test_flash_log_learns_the_firmware_from_its_status_records():
    """A log stream decoded with no known firmware starts on the newest layout; a status record
    inside it names an older firmware, and the records after it use that layout."""
    status = load()[4]["data_hex"]  # firmware 4.4 on the wiki collar
    import struct

    scan = bytes([0xFB, 8, 1, 0]) + struct.pack("<HH", 8680, 8686) + bytes([2, 100])
    stamp = struct.pack("<I", 1701339971)
    stream = bytes([4]) + bytes.fromhex(status)[:] + stamp + bytes([8]) + scan + stamp
    records = driver.decode(channel_event("log_file", (bytes([29]) + stream).hex()))
    assert records.decoder_version == "fw4.4.3"
    assert any(s.record_type == "rf_scan" for s in records.states), records.notes
