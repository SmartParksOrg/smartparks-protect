"""The shared decode path of a station frame (phase 43 P6): the refusals by code and words,
and the records of the firmware's fixture frame, with no database in sight."""

import json
from datetime import UTC, datetime

import pytest

from shared.device_drivers.opencollar import OpenCollarDriver
from shared.enums import ErrorCode
from shared.station_decode import (
    FrameRefused,
    decode_station_frame,
    frame_metadata,
    unwrap_station_frame,
)
from tests.decoder.test_logfiles import FLASH
from tests.shared.test_lp0_lorawan import (
    APP_S_KEY,
    CREDENTIALS,
    NWK_S_KEY,
    SAVED_REPLAY_PACKET,
    THREE_RECORDS,
    Credentials,
    build_uplink,
)

DOCUMENT = json.loads(
    '{"gatewayEui": "0016C001F0ABCDEF", "rxpk": {"time": "2026-10-12T08:50:31Z", "tmst": 1791795031,'
    ' "freq": 864.629, "datr": "SF7BW250", "codr": "4/5", "rssi": -71, "lsnr": 9, "size": 46,'
    ' "data": "QAMBAiYAZQAdmQO+Xdlf"}}'
)


def test_the_fixture_opens_and_the_metadata_is_the_pipelines():
    frame = unwrap_station_frame(
        SAVED_REPLAY_PACKET,
        CREDENTIALS,
        device_name="SP100001",
        device_eui="0016C001F0100001",
        source_eui="0016c001f0100001",
        lp0_version=5,
        last_f_cnt=None,
    )
    assert (frame.payload, frame.f_port, frame.f_cnt, frame.f_cnt16, frame.dev_addr) == (
        THREE_RECORDS,
        29,
        101,
        101,
        "26010203",
    )
    assert frame_metadata(frame) == {
        "frame_hex": THREE_RECORDS.hex(),
        "f_port": 29,
        "f_cnt": 101,
        "f_cnt32": 101,
        "mic_ok": True,
    }


def test_refusals_carry_the_pipelines_codes_and_words():
    with pytest.raises(FrameRefused) as no_keys:
        unwrap_station_frame(
            SAVED_REPLAY_PACKET,
            None,
            device_name="SP100001",
            device_eui=None,
            source_eui=None,
            lp0_version=None,
            last_f_cnt=None,
        )
    assert (
        no_keys.value.code == ErrorCode.CREDENTIALS_MISSING
        and "SP100001 has no LP0 keys" in no_keys.value.message
    )
    with pytest.raises(FrameRefused) as wrong_tracker:
        unwrap_station_frame(
            SAVED_REPLAY_PACKET,
            CREDENTIALS,
            device_name="SP100001",
            device_eui="0016C001F0100001",
            source_eui="0016C001F0100002",
            lp0_version=5,
            last_f_cnt=None,
        )
    assert wrong_tracker.value.code == ErrorCode.DEVICE_IDENTITY_AMBIGUOUS
    assert "address 26010203 belongs to SP100001" in wrong_tracker.value.message
    with pytest.raises(FrameRefused) as unknown_version:
        unwrap_station_frame(
            SAVED_REPLAY_PACKET,
            CREDENTIALS,
            device_name="SP100001",
            device_eui=None,
            source_eui=None,
            lp0_version=6,
            last_f_cnt=None,
        )
    assert (
        unknown_version.value.code == ErrorCode.PAYLOAD_DECODE_FAILED
        and "version 6" in unknown_version.value.message
    )
    with pytest.raises(FrameRefused) as bad_keys:
        unwrap_station_frame(
            SAVED_REPLAY_PACKET,
            Credentials("26010203", NWK_S_KEY, APP_S_KEY),
            device_name="SP100001",
            device_eui=None,
            source_eui=None,
            lp0_version=None,
            last_f_cnt=None,
        )
    assert (
        bad_keys.value.code == ErrorCode.PAYLOAD_DECODE_FAILED
        and "does not verify" in bad_keys.value.message
    )


def test_the_driver_reads_the_opened_frame_as_a_stored_stream():
    """A real flash stream (the decoder tests' fixture, three stored fixes) in a station frame
    under the fixture keys: the records keep their stored times, as on the server."""
    phy = build_uplink(CREDENTIALS, 7, 29, bytes.fromhex(FLASH))
    frame = unwrap_station_frame(
        phy,
        CREDENTIALS,
        device_name="SP100001",
        device_eui=None,
        source_eui=None,
        lp0_version=None,
        last_f_cnt=None,
    )
    assert (frame.f_port, frame.f_cnt) == (29, 7)
    records = decode_station_frame(
        OpenCollarDriver(),
        frame,
        document=DOCUMENT,
        received_at=datetime(2026, 10, 12, 8, 50, 31, tzinfo=UTC),
        fallback_time=datetime(2026, 10, 17, tzinfo=UTC),
        firmware_version=None,
    )
    assert records.stored is True
    assert len(records.positions) == 3
    assert all(p.time < datetime(2026, 10, 12, tzinfo=UTC) for p in records.positions)
