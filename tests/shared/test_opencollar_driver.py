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


def test_bad_frames_are_decode_failures():
    for port, hex_data in ((2, "f21d00"), (4, "f20e" + "00" * 14), (99, "0102"), (2, "f21e0100")):
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
