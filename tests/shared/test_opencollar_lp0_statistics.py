"""The offload station's port 23 report (firmware 8.1, phase 42, decision D323): the driver's
reading of constructed reports of versions 1, 2 and 3 against the firmware's own decoder
(`decodeLP0Statistics` in the vendored branch decoder, run with node when node is on the path)
and against the README's layout; an inconsistent report is refused. Version 2 brought the
card's capacity and free share, version 3 the `sd_card_missing` and `sdfs_error` bits (the
firmware branch of 2026-10-20, decision D345)."""

import json
import shutil
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.device_drivers.base import SourceEventData
from shared.device_drivers.opencollar import (
    LP0_CAPACITY_UNKNOWN,
    LP0_COUNTERS,
    LP0_FREE_UNKNOWN,
    LP0_STATUS_BITS,
    OPENCOLLAR_HEALTH,
    OpenCollarDriver,
    lp0_sd_card_ok,
)
from shared.enums import AcquisitionChannel
from shared.trace import ApplicationError

DECODER = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "payloads"
    / "opencollar"
    / "decoders"
    / "ttn_decoder-lp0-7bae042.js"
)
RECEIVED = datetime(2026, 10, 15, 12, tzinfo=UTC)
UPTIME = 86_400 * 3 + 7
driver = OpenCollarDriver()


def report(
    *,
    version: int = 1,
    flags: int = 0b000_0110_0011,
    known: int = 0x07FF,
    pending: int = 1,
    high: int = 3,
    capacity: int = LP0_CAPACITY_UNKNOWN,
    free: int = LP0_FREE_UNKNOWN,
) -> bytes:
    """A report as the firmware's `lp0_statistics_encode` writes one: version 1 is 99 bytes,
    versions 2 and 3 are 104 with the capacity (whole MB) and free share (percent) after the
    counters, unknown as the two sentinels together."""
    counters = [100 + i for i in range(len(LP0_COUNTERS))]
    body = struct.pack("<BHHIHH", version, flags, known, UPTIME, pending, high)
    body += struct.pack(f"<{len(counters)}I", *counters)
    if version >= 2:
        body += struct.pack("<IB", capacity, free)
    assert len(body) == (97 if version == 1 else 102)
    return bytes([0x9D, len(body)]) + body


def decode(frame: bytes, channel: AcquisitionChannel = AcquisitionChannel.LP0):
    return driver.decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload={},
            provider_metadata={"f_port": 23},
            network_received_at=RECEIVED,
            ingested_at=RECEIVED,
            device_attributes={},
            device_type_settings={},
            frame=frame,
            f_port=23,
            acquisition_channel=channel,
            firmware_version="8.1",
        )
    )


def test_the_report_becomes_a_state_and_measurements():
    records = decode(report())
    assert len(records.states) == 1
    state = records.states[0].state["lp0_station"]
    assert records.states[0].record_type == "lp0_station"
    assert state["version"] == 1
    assert state["uptime_seconds"] == UPTIME
    assert (state["storage_pending"], state["storage_high_water"]) == (1, 3)
    assert (state["sd_capacity_mb"], state["sd_free_percent"]) == (None, None)
    assert state["status"]["card_detected"] is True
    assert state["status"]["card_writable"] is True
    assert state["status"]["sdfs_unresponsive"] is False
    assert state["status"]["lp0_enabled"] is True and state["status"]["lp0_listening"] is True
    # the version 3 bits are unknown on an older report, never false
    assert state["status"]["sd_card_missing"] is None and state["status"]["sdfs_error"] is None
    assert state["counters"] == {name: 100 + i for i, name in enumerate(LP0_COUNTERS)}
    figures = {m.metric_key: m.value for m in records.measurements}
    assert figures["lp0_sd_card_ok"] is True
    assert figures["lp0_uptime"] == UPTIME
    assert figures["lp0_visits_complete"] == 100 and figures["lp0_report_sd_failed"] == 120
    assert "lp0_sd_capacity_mb" not in figures and "lp0_sd_free_percent" not in figures
    assert all(m.record_type == "lp0_station" for m in records.measurements)
    assert all(m.time == RECEIVED for m in records.measurements)


def test_version_2_carries_the_card_capacity_and_free_share():
    records = decode(report(version=2, capacity=15_193, free=87))
    state = records.states[0].state["lp0_station"]
    assert state["version"] == 2
    assert (state["sd_capacity_mb"], state["sd_free_percent"]) == (15_193, 87)
    figures = {m.metric_key: m.value for m in records.measurements}
    assert (figures["lp0_sd_capacity_mb"], figures["lp0_sd_free_percent"]) == (15_193.0, 87.0)
    assert figures["lp0_sd_card_ok"] is True
    # unknown together: the figures are absent, the state says None
    records = decode(report(version=2))
    state = records.states[0].state["lp0_station"]
    assert (state["sd_capacity_mb"], state["sd_free_percent"]) == (None, None)
    figures = {m.metric_key: m.value for m in records.measurements}
    assert "lp0_sd_capacity_mb" not in figures and "lp0_sd_free_percent" not in figures


def test_version_3_knows_a_missing_card_and_a_storage_fault():
    all_known = 0x1FFF
    records = decode(
        report(version=3, flags=0b0_0110_0011, known=all_known, capacity=7_580, free=3)
    )
    state = records.states[0].state["lp0_station"]
    assert state["version"] == 3
    assert state["status"]["sd_card_missing"] is False and state["status"]["sdfs_error"] is False
    figures = {m.metric_key: m.value for m in records.measurements}
    assert figures["lp0_sd_card_ok"] is True and figures["lp0_sd_free_percent"] == 3.0
    # the card bits unobserved, the missing bit known and set: the card is not usable
    records = decode(report(version=3, flags=1 << 11, known=(1 << 11) | 0x07FC))
    status = records.states[0].state["lp0_station"]["status"]
    assert status["card_detected"] is None and status["sd_card_missing"] is True
    assert {m.metric_key: m.value for m in records.measurements}["lp0_sd_card_ok"] is False
    # in and writable, but a storage fault latched: not usable either
    records = decode(report(version=3, flags=0b11 | (1 << 12), known=all_known))
    assert {m.metric_key: m.value for m in records.measurements}["lp0_sd_card_ok"] is False


def test_the_card_helper_reads_the_observations():
    assert lp0_sd_card_ok({}) is None
    assert lp0_sd_card_ok({"card_detected": True, "card_writable": None}) is None
    assert lp0_sd_card_ok({"card_detected": True, "card_writable": True}) is True
    assert lp0_sd_card_ok({"card_detected": True, "card_writable": False}) is False
    assert lp0_sd_card_ok({"sd_card_missing": True}) is False
    assert (
        lp0_sd_card_ok({"card_detected": True, "card_writable": True, "sdfs_error": True}) is False
    )
    assert lp0_sd_card_ok({"sd_card_missing": False, "sdfs_error": False}) is None


def test_an_unknown_observation_is_unknown_and_the_card_line_is_then_absent():
    records = decode(report(flags=0b11, known=0b11 | 0x7FC))  # card bits known, no others
    status = records.states[0].state["lp0_station"]["status"]
    assert status["card_detected"] is True and status["card_writable"] is True
    records = decode(report(flags=0, known=0x07FC))  # the two card bits unknown
    status = records.states[0].state["lp0_station"]["status"]
    assert status["card_detected"] is None and status["card_writable"] is None
    assert "lp0_sd_card_ok" not in {m.metric_key for m in records.measurements}
    records = decode(report(flags=0b01, known=0b11))  # in, not writable
    assert {m.metric_key: m.value for m in records.measurements}["lp0_sd_card_ok"] is False


def test_inconsistent_reports_are_refused():
    with pytest.raises(ApplicationError, match="inconsistent"):
        decode(report(flags=0b1, known=0))  # a value bit that is not known
    with pytest.raises(ApplicationError, match="inconsistent"):
        decode(report(pending=5, high=2))
    with pytest.raises(ApplicationError, match="inconsistent"):
        decode(report(known=0x0FFF))  # bit 11 is reserved in version 1
    with pytest.raises(ApplicationError, match="inconsistent"):
        decode(report(version=2, known=0x1FFF))  # and in version 2
    with pytest.raises(ApplicationError, match="inconsistent"):
        decode(report(version=3, known=0x3FFF))  # bit 13 is reserved in version 3
    with pytest.raises(ApplicationError, match="version"):
        decode(report(version=4))  # a version this driver does not read
    bad_version = bytearray(report())
    bad_version[2] = 2  # version 2 is 104 bytes, this is 99
    with pytest.raises(ApplicationError, match="version"):
        decode(bytes(bad_version))
    with pytest.raises(ApplicationError, match="length"):
        decode(bytes([0x9D, 96]) + report()[2:98])


def test_invalid_capacity_encodings_are_refused():
    with pytest.raises(ApplicationError, match="capacity"):
        decode(report(version=2, capacity=1000, free=LP0_FREE_UNKNOWN))  # one sentinel alone
    with pytest.raises(ApplicationError, match="capacity"):
        decode(report(version=2, capacity=LP0_CAPACITY_UNKNOWN, free=50))
    with pytest.raises(ApplicationError, match="capacity"):
        decode(report(version=2, capacity=0, free=50))  # a card of no size
    with pytest.raises(ApplicationError, match="capacity"):
        decode(report(version=3, capacity=1000, free=101))  # more than full


def test_the_report_over_lorawan_reads_the_same():
    over_air = decode(report(), AcquisitionChannel.LORAWAN)
    over_card = decode(report(), AcquisitionChannel.LP0)
    assert over_air.states[0].state == over_card.states[0].state


def test_the_health_card_levels_the_sd_card_lines():
    from shared.domain.health import device_health

    records = decode(
        report(version=3, flags=0b01, known=0b11 | (1 << 11) | (1 << 12), capacity=7_580, free=4)
    )
    measurements = {
        m.metric_key: {"value": m.value, "time": m.time.isoformat()} for m in records.measurements
    }
    health = device_health(
        OPENCOLLAR_HEALTH,
        latest_measurements=measurements,
        latest_state=records.states[0].state,
        latest_state_time=RECEIVED,
        last_seen_at=RECEIVED,
    )
    line = next(f for f in health.fields if f.key == "lp0_sd_card_ok")
    assert (line.level, line.text) == ("critical", "absent, faulted or not writable")
    free = next(f for f in health.fields if f.key == "lp0_sd_free_percent")
    assert free.level == "warn"  # 4 % free
    errors = next(f for f in health.fields if f.key == "lp0_sd_media_errors")
    assert errors.level == "warn"  # 110 errors since boot in the constructed report


def _firmware_decoder(frame: bytes) -> dict:
    shim = (
        "const fs = require('fs');"
        f"const src = fs.readFileSync({json.dumps(str(DECODER))}, 'utf8');"
        "const holder = {};"
        "new Function('holder', src + '\\n; holder.Decoder = Decoder;')(holder);"
        f"const bytes = Buffer.from({json.dumps(frame.hex())}, 'hex');"
        "process.stdout.write(JSON.stringify(holder.Decoder(bytes, 23)));"
    )
    out = subprocess.run(["node", "-e", shim], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on the path")
@pytest.mark.parametrize(
    ("frame", "expected_capacity", "expected_free"),
    [
        (report(flags=0b000_0110_0011, known=0x07FF, pending=1, high=3), None, None),
        (report(version=2, capacity=15_193, free=87), 15_193, 87),
        (report(version=3, flags=(1 << 12) | 0b11, known=0x1FFF, capacity=7_580, free=3), 7_580, 3),
    ],
)
def test_the_firmware_decoder_agrees(frame: bytes, expected_capacity, expected_free):
    theirs = _firmware_decoder(frame)
    ours = decode(frame).states[0].state["lp0_station"]
    assert "error" not in theirs, theirs
    assert theirs["uptime_seconds"] == ours["uptime_seconds"]
    assert theirs["storage_pending"] == ours["storage_pending"]
    assert theirs["storage_high_water"] == ours["storage_high_water"]
    assert theirs["sd_capacity_mb"] == ours["sd_capacity_mb"] == expected_capacity
    assert theirs["sd_free_percent"] == ours["sd_free_percent"] == expected_free
    for name in LP0_STATUS_BITS:
        assert theirs["status"].get(name) == ours["status"][name], name
    for name in LP0_COUNTERS:
        assert theirs["counters"][name] == ours["counters"][name], name
