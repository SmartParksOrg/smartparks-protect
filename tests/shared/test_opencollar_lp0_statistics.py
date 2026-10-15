"""The offload station's port 23 report (firmware 8.1, phase 42, decision D323): the driver's
reading of a constructed report against the firmware's own decoder (`decodeLP0Statistics` in
the vendored branch decoder, run with node when node is on the path) and against the README's
layout; an inconsistent report is refused."""

import json
import shutil
import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.device_drivers.base import SourceEventData
from shared.device_drivers.opencollar import (
    LP0_COUNTERS,
    LP0_STATUS_BITS,
    OPENCOLLAR_HEALTH,
    OpenCollarDriver,
)
from shared.enums import AcquisitionChannel
from shared.trace import ApplicationError

DECODER = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "payloads"
    / "opencollar"
    / "decoders"
    / "ttn_decoder-lp0-5ff74907.js"
)
RECEIVED = datetime(2026, 10, 15, 12, tzinfo=UTC)
driver = OpenCollarDriver()


def report(
    *, flags: int = 0b000_0110_0011, known: int = 0x07FF, pending: int = 1, high: int = 3
) -> bytes:
    counters = [100 + i for i in range(len(LP0_COUNTERS))]
    body = struct.pack("<BHHIHH", 1, flags, known, 86_400 * 3 + 7, pending, high)
    body += struct.pack(f"<{len(counters)}I", *counters)
    assert len(body) == 97
    return bytes([0x9D, 97]) + body


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
    assert state["uptime_seconds"] == 86_400 * 3 + 7
    assert (state["storage_pending"], state["storage_high_water"]) == (1, 3)
    assert state["status"]["card_detected"] is True
    assert state["status"]["card_writable"] is True
    assert state["status"]["sdfs_unresponsive"] is False
    assert state["status"]["lp0_enabled"] is True and state["status"]["lp0_listening"] is True
    assert state["counters"] == {name: 100 + i for i, name in enumerate(LP0_COUNTERS)}
    figures = {m.metric_key: m.value for m in records.measurements}
    assert figures["lp0_sd_card_ok"] is True
    assert figures["lp0_uptime"] == 86_400 * 3 + 7
    assert figures["lp0_visits_complete"] == 100 and figures["lp0_report_sd_failed"] == 120
    assert all(m.record_type == "lp0_station" for m in records.measurements)
    assert all(m.time == RECEIVED for m in records.measurements)


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
        decode(report(known=0x0FFF))  # a reserved bit
    bad_version = bytearray(report())
    bad_version[2] = 2
    with pytest.raises(ApplicationError, match="version"):
        decode(bytes(bad_version))
    with pytest.raises(ApplicationError, match="length"):
        decode(bytes([0x9D, 96]) + report()[2:98])


def test_the_report_over_lorawan_reads_the_same():
    over_air = decode(report(), AcquisitionChannel.LORAWAN)
    over_card = decode(report(), AcquisitionChannel.LP0)
    assert over_air.states[0].state == over_card.states[0].state


def test_the_health_card_levels_the_sd_card_line():
    from shared.domain.health import device_health

    records = decode(report(flags=0b01, known=0b11))
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
    assert (line.level, line.text) == ("critical", "absent or not writable")
    errors = next(f for f in health.fields if f.key == "lp0_sd_media_errors")
    assert errors.level == "warn"  # 110 errors since boot in the constructed report


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on the path")
def test_the_firmware_decoder_agrees():
    frame = report(flags=0b000_0110_0011, known=0x07FF, pending=1, high=3)
    shim = (
        "const fs = require('fs');"
        f"const src = fs.readFileSync({json.dumps(str(DECODER))}, 'utf8');"
        "const holder = {};"
        "new Function('holder', src + '\\n; holder.Decoder = Decoder;')(holder);"
        f"const bytes = Buffer.from({json.dumps(frame.hex())}, 'hex');"
        "process.stdout.write(JSON.stringify(holder.Decoder(bytes, 23)));"
    )
    out = subprocess.run(["node", "-e", shim], capture_output=True, text=True, check=True)
    theirs = json.loads(out.stdout)
    ours = decode(frame).states[0].state["lp0_station"]
    assert theirs["uptime_seconds"] == ours["uptime_seconds"]
    assert theirs["storage_pending"] == ours["storage_pending"]
    assert theirs["storage_high_water"] == ours["storage_high_water"]
    assert theirs["counters"] == ours["counters"]
    assert list(theirs["status"]) == list(LP0_STATUS_BITS)
    for name in LP0_STATUS_BITS:
        assert theirs["status"][name] == ours["status"][name], name
