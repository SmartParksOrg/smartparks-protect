"""An offload station's files (phase 42, decision D321): the JSONL lines the station writes,
the names of its files and folders, and a zip of a card."""

import base64
import io
import json
import zipfile
from datetime import UTC, datetime

from shared.domain.lp0 import normalise_dev_addr, parse_key, station_eui_from_name
from shared.logfiles import (
    looks_like_station_file,
    parse_station_jsonl,
    parse_station_line,
    unpack_card_zip,
)
from tests.shared.test_lp0_lorawan import SAVED_REPLAY_PACKET

STATION = "0016C001F0ABCDEF"


def line(data: bytes = SAVED_REPLAY_PACKET, **overrides: object) -> str:
    rxpk = {
        "time": "2026-10-12T08:50:31Z",
        "tmst": 1791795031,
        "freq": 864.629000,
        "chan": 0,
        "rfch": 0,
        "stat": 1,
        "modu": "LORA",
        "datr": "SF7BW250",
        "codr": "4/5",
        "rssi": -71,
        "lsnr": 9,
        "size": len(data),
        "data": base64.b64encode(data).decode(),
    }
    rxpk.update(overrides)
    return json.dumps({"gatewayEui": STATION, "rxpk": rxpk})


def test_parse_station_lines_with_the_leading_newline_and_a_bad_line():
    text = "\n" + line() + "\n" + "not json" + "\n" + line(rssi=-99, lsnr=-2) + "\n"
    parsed = parse_station_jsonl(text)
    assert [f.line for f in parsed.frames] == [2, 4]
    assert parsed.errors == [(3, "not JSON: Expecting value: line 1 column 1 (char 0)")]
    first = parsed.frames[0]
    assert first.station_eui == STATION and first.data == SAVED_REPLAY_PACKET
    assert first.received_at == datetime(2026, 10, 12, 8, 50, 31, tzinfo=UTC)
    assert (first.rssi, first.snr, first.frequency_hz) == (-71.0, 9.0, 864_629_000)
    assert (first.data_rate, first.spreading_factor, first.coding_rate) == ("SF7BW250", 7, "4/5")
    assert parsed.frames[1].rssi == -99.0 and parsed.lines == 3


def test_time_falls_back_to_tmst_in_unix_seconds():
    frame = parse_station_line(1, line(time="not a time"))
    assert frame.received_at == datetime(2026, 10, 12, 8, 50, 31, tzinfo=UTC)
    frame = parse_station_line(1, line(time="", tmst=0))
    assert frame.received_at is None


def test_unreadable_lines_say_why():
    parsed = parse_station_jsonl(
        "\n".join(
            [
                json.dumps({"gatewayEui": STATION}),
                json.dumps({"gatewayEui": "nope", "rxpk": {"data": "AA=="}}),
                line(data=b"\x40\x01"),
                json.dumps({"gatewayEui": STATION, "rxpk": {"data": "***"}}),
            ]
        )
    )
    assert not parsed.frames
    assert [m.split(":")[0] for _, m in parsed.errors] == [
        "no rxpk document",
        "gatewayEui is not sixteen hex digits",
        "frame shorter than a LoRaWAN uplink",
        "data is not base64",
    ]


def test_a_line_may_name_the_tracker_and_its_frame_format():
    """Issue 772 lets a station keep the tracker's EUI as routing metadata and may version
    the stored frame; both are kept on the frame and nothing is read into them."""
    document = json.loads(line())
    document["devEui"] = "0016c001f09c74fc"
    document["frameFormat"] = "lorawan"
    frame = parse_station_line(1, json.dumps(document))
    assert (frame.dev_eui, frame.frame_format) == ("0016C001F09C74FC", "lorawan")
    document["devEui"] = "not an eui"
    assert parse_station_line(1, json.dumps(document)).dev_eui is None
    assert parse_station_line(1, line()).dev_eui is None


def test_station_file_names_and_recognition():
    assert station_eui_from_name("0016c001f0abcdef_1791795031.jsonl") == STATION
    assert station_eui_from_name("LOG_3\\0016C001F0ABCDEF_1791795031_002.jsonl") == STATION
    assert station_eui_from_name("raw_logs-all-SP05.txt") is None
    assert looks_like_station_file("x.jsonl", b"") is True
    assert looks_like_station_file("x.txt", b'\n{"gatewayEui"') is True
    assert looks_like_station_file("x.txt", b"AAEC\n") is False


def test_unpack_a_card_zip_keeps_the_folder_and_skips_the_rest():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("LOG_1/0016C001F0ABCDEF_1791795031.jsonl", line())
        archive.writestr("LOG_2/0016C001F0ABCDEF_1791796000_001.jsonl", line())
        archive.writestr("LOG_2/notes.txt", "hello")
        archive.writestr("0016C001F0ABCDEF_1791700000.jsonl", line())
    card = unpack_card_zip(buffer.getvalue(), member_max_bytes=1_000_000)
    assert [(m.folder, m.name) for m in card.members] == [
        ("LOG_1", "0016C001F0ABCDEF_1791795031.jsonl"),
        ("LOG_2", "0016C001F0ABCDEF_1791796000_001.jsonl"),
        ("", "0016C001F0ABCDEF_1791700000.jsonl"),
    ]
    assert card.skipped == ["LOG_2/notes.txt"]
    small = unpack_card_zip(buffer.getvalue(), member_max_bytes=10)
    assert not small.members and len(small.skipped) == 4


def test_addresses_and_keys_are_normalised():
    assert normalise_dev_addr("26:01:02:03") == "26010203"
    assert normalise_dev_addr("2601 0203") == "26010203"
    assert parse_key("00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f") == bytes(range(16))
    for bad in ("2601020", "2601020G", ""):
        try:
            normalise_dev_addr(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
