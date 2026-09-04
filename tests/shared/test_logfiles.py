"""Raw log file parsing (decision D77): the BLE app's one-base64-frame-per-line format, hex
lines, comments and unreadable lines."""

import base64

from shared.logfiles import frames_to_text, parse_log_text

RECORD = bytes.fromhex("1d0d930ef9636865aba50d1f8e090e031500006468")


def test_parse_base64_and_hex_lines_skipping_blanks_and_comments():
    text = "\n".join(
        [
            "# exported by the BLE app",
            base64.b64encode(RECORD).decode(),
            "",
            RECORD.hex().upper(),
            "   ",
            "not base64 at all!!",
            "AA",  # one byte: too short for a frame
        ]
    )
    parsed = parse_log_text(text)
    assert [f.line for f in parsed.frames] == [2, 4]
    assert all(f.data == RECORD for f in parsed.frames)
    assert [n for n, _ in parsed.errors] == [6, 7]
    assert parsed.lines == 4


def test_frames_to_text_round_trips():
    text = frames_to_text([RECORD, b"\x04\xf4\x0e" + bytes(14)])
    parsed = parse_log_text(text)
    assert len(parsed.frames) == 2 and not parsed.errors
    assert parsed.frames[1].data[:3] == b"\x04\xf4\x0e"
    assert frames_to_text([]) == ""
