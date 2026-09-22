"""Golden test (decision D100, ADR 0021): every recorded OpenCollar frame decoded by our driver
with the layout of a firmware range gives what the firmware's own reference decoder of that
range gives. `golden.json` is written by `scripts/opencollar_golden.py`; this test needs no node."""

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.device_drivers.base import SourceEventData
from shared.device_drivers.opencollar import (
    HARDWARE_TYPES,
    OpenCollarDriver,
    uptime_unit_seconds,
)

GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "opencollar" / "golden.json"
)
FIRMWARE = {"7.2.0": "7.2", "6.15.1": "6.15", "6.11.2": "6.11"}
RECEIVED = datetime(2026, 9, 6, 12, tzinfo=UTC)
driver = OpenCollarDriver()


def decode(port: int, data_hex: str, firmware: str):
    return driver.decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload={"fPort": port},
            provider_metadata={"f_port": port},
            network_received_at=RECEIVED,
            ingested_at=RECEIVED,
            device_attributes={},
            device_type_settings={},
            frame=bytes.fromhex(data_hex),
            f_port=port,
            firmware_version=firmware,
        )
    )


def close(a, b, tolerance=1e-6):
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=tolerance)


def cases():
    for entry in json.loads(GOLDEN.read_text()):
        for version, expected in entry["decoders"].items():
            yield pytest.param(
                entry, version, expected, id=f"{entry['source']}:{entry['port']}:v{version}"
            )


@pytest.mark.parametrize(("entry", "version", "expected"), list(cases()))
def test_driver_matches_the_reference_decoder(entry, version, expected):
    port = entry["port"]
    records = decode(port, entry["data_hex"], FIRMWARE[version])
    measurements = {m.metric_key: m.value for m in records.measurements}
    if "error" in expected:
        pytest.skip(f"reference decoder failed: {expected['error']}")
    if not expected:
        # the reference decoder of this range has no branch for the port: neither do we
        assert records.empty and records.notes, (port, version, records.notes)
        return
    if port == 2:
        position = records.positions[0]
        assert close(position.latitude, expected["latitude"]) and close(
            position.longitude, expected["longitude"]
        )
        assert close(position.altitude_m, expected["altitude"], 1e-3)
        assert int(position.time.timestamp()) == expected["fix_timestamp"]
        assert position.attributes["hot_retry"] == expected["hot_retry"]
        assert position.attributes["cold_retry"] == expected["cold_retry"]
        assert (
            position.satellites == expected["SIV"] and position.accuracy_m == expected["h_acc_est"]
        )
        assert position.attributes["fix_type"] == expected["fixType"]
        assert measurements["gnss_time_to_fix"] == expected["ttf"]
        assert measurements["gnss_pdop"] == expected["pDOP"]
    elif port in (13, 16):
        position = records.positions[0]
        assert close(position.latitude, expected["latitude"]) and close(
            position.longitude, expected["longitude"]
        )
        assert int(position.time.timestamp()) == expected["fix_timestamp"]
        assert position.accuracy_m == expected["h_acc_est"]
    elif port == 4:
        state = records.states[0].state
        assert close(measurements["battery_voltage"], expected["bat"] / 1000, 1e-9)
        assert close(measurements["device_temperature"], expected["temp"], 0.01)
        for axis in ("x", "y", "z"):
            assert close(measurements[f"acceleration_{axis}"], expected[f"acc_{axis}"], 0.01)
        # the reference decoder hands the raw byte over with no unit. It is days since firmware
        # 4.0.1 and hours before it ("display uptime in days instead of hours", CHANGELOG
        # 4.0.1), and the unit follows the version the status message itself reports, which is
        # not the version the device is told it runs. Asserting days always passed only while
        # the golden file was stale and held no frame from an older firmware.
        reported = f"{expected['ver_fw_major']}.{expected['ver_fw_minor']}"
        assert measurements["uptime"] == expected["uptime"] * uptime_unit_seconds(reported)
        assert measurements["lr_satellites"] == expected["lr_sat"]
        assert state["firmware_version"] == f"{expected['ver_fw_major']}.{expected['ver_fw_minor']}"
        assert state["hardware_version"] == f"{expected['ver_hw_major']}.{expected['ver_hw_minor']}"
        hardware_type = expected["ver_hw_type"]
        assert state["hardware_type"] == HARDWARE_TYPES.get(hardware_type, str(hardware_type))
        assert state["satellite_enabled"] == bool(expected["sat_support"])
        assert state["fence_enabled"] == bool(expected["fence"])
        assert state["satellite_retries"] == expected["sat_try"]
        for ours, theirs in (
            ("lr_module", "err_lr"),
            ("ble", "err_ble"),
            ("ublox", "err_ublox"),
            ("accelerometer", "err_acc"),
            ("battery", "err_bat"),
            ("ublox_fix", "err_ublox_fix"),
            ("flash", "err_flash"),
        ):
            assert state["errors"][ours] == bool(expected[theirs]), (ours, theirs)
        assert ("rf_scan_enabled" in state) == ("rf_scan" in expected)
    elif port in (7, 11):
        # the reference prints each octet with toString(16), which drops a leading zero, so
        # "a:41:c" and our "0a:41:0c" are the same address; pad before comparing
        def padded(mac: str) -> str:
            return ":".join(part.rjust(2, "0") for part in mac.split(":"))

        seen = [expected[str(i + 1)] for i in range(expected["N_BT_res"])]
        assert [c.address for c in records.contacts] == [padded(r["mac"]) for r in seen]
        assert [c.rssi_dbm for c in records.contacts] == [r["rssi"] for r in seen]
        if port == 11:
            # one scan: its finish time is canonical for every sighting in it
            assert all(int(c.time.timestamp()) == expected["t"] for c in records.contacts)
            assert all(c.sightings == 1 for c in records.contacts)
        else:
            # the aggregate: each record is about its own strongest sighting
            assert [c.sightings for c in records.contacts] == [r["count"] for r in seen]
            assert [int(c.time.timestamp()) for c in records.contacts] == [r["t"] for r in seen]
    elif port == 14:
        assert measurements["flash_used_percent"] == expected["percentage"]
        assert measurements["flash_messages"] == expected["n_msg"]
    elif port == 15:
        # one sighting per record, each at its own time, so the values are grouped by moment
        # rather than by key: a frame carries several records of the same metric.
        by_time: dict[int, dict[str, float]] = {}
        for m in records.measurements:
            by_time.setdefault(int(m.time.timestamp()), {})[m.metric_key] = m.value
        wanted = [expected[str(i)] for i in range(len(expected))]
        assert [t for t in by_time] == [r["cmdq_timestamp"] for r in wanted]
        for reading, ours in zip(wanted, by_time.values(), strict=True):
            assert ours["cmdq_rr_median"] == reading["cmdq_rr_median"]
            assert ours["cmdq_rr_median_modesum"] == reading["cmdq_rr_median_modesum"]
            assert ours["cmdq_activity_average"] == reading["cmdq_activity_average"]
            assert ours["cmdq_activity_max"] == reading["cmdq_activity_max"]
            assert ours["cmdq_active_min_in_last_hour"] == reading["cmdq_active_min_in_last_hour"]
            assert ours["cmdq_raw_temperature"] == reading["cmdq_raw_temp"]
            assert ours["cmdq_impedance"] == reading["cmdq_h_impedance"]
            assert ours["cmdq_success"] == bool(reading["cmdq_success"])
            assert ours["cmdq_hrv_raw"] == reading["cmdq_hrv_raw"]
            # the reference decoder reports a temperature of 0 and an HRV of 0 for a record
            # that carries neither; we leave the value out instead of writing a false reading
            if reading["cmdq_success"]:
                assert close(ours["cmdq_temperature"], reading["cmdq_temp"], 0.01)
            else:
                assert "cmdq_temperature" not in ours
            if reading["cmdq_hrv_raw"]:
                assert close(ours["heart_rate_variability"], reading["cmdq_hrv"], 0.01)
            if reading["cmdq_rr_median"]:
                # our own derivation, from the published tens of milliseconds
                assert close(ours["heart_rate"], 6000 / reading["cmdq_rr_median"], 0.05)
            else:
                assert "heart_rate" not in ours
    else:
        # ports the mapping does not cover: the driver must at least accept the frame
        assert records is not None
