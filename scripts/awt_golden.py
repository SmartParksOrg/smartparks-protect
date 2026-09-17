#!/usr/bin/env python3
"""Build the AWT fixture frames and run them through AWT's own codec (decision D241).

    uv run scripts/awt_golden.py

Writes `tests/fixtures/payloads/awt/frames.jsonl` (the synthetic frames, keeping any recorded
one already there) and `golden.json` (the codec's output per frame). Needs node."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "payloads" / "awt"

SHIM = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const frames = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const holder = {};
new Function("holder", src + "\\n; holder.decodeUplink = decodeUplink;")(holder);
const out = frames.map((f) => holder.decodeUplink({ bytes: Array.from(Buffer.from(f.data_hex, "hex")), fPort: 1 }));
process.stdout.write(JSON.stringify(out));
"""


def xor(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def lat_word(latitude: float, hdop: int) -> int:
    """The latitude word: ddmmmmmm digits in the low 27 bits, HDOP in bits 27 to 30, bit 31
    for south."""
    degrees = int(abs(latitude))
    minutes = round((abs(latitude) - degrees) * 60 * 10000)
    word = degrees * 1_000_000 + minutes
    word |= (hdop & 0x0F) << 27
    if latitude < 0:
        word |= 0x80000000
    return word


def lon_word(longitude: float, *, alarm: bool, movement: bool, global_ack: bool) -> int:
    degrees = int(abs(longitude))
    minutes = round((abs(longitude) - degrees) * 60 * 10000)
    word = degrees * 1_000_000 + minutes
    if global_ack:
        word |= 0x10000000
    if movement:
        word |= 0x20000000
    if alarm:
        word |= 0x40000000
    if longitude >= 0:
        word |= 0x80000000
    return word


def frame(
    *,
    counter: int,
    encrypted: bool,
    payload_type: int,
    master: int,
    tag: int,
    alarms: int,
    acks: int,
    version: int,
    interval: int,
    battery: float,
    epoch: int,
    latitude: float,
    longitude: float,
    hdop: int,
    flags: tuple[bool, bool, bool],
    speed: int,
    key: int,
    accel: tuple[int, int, int],
    temperature: int,
    altitude: int | None,
    light: int | None,
) -> bytes:
    body = bytearray()
    body.append(payload_type)
    body += struct.pack("<HH", master, tag)
    body += bytes([alarms, acks, version, interval])
    body += struct.pack(">H", round(battery * 100))
    body += struct.pack(">I", epoch)
    body += struct.pack(">I", lat_word(latitude, hdop))
    body += struct.pack(
        ">I", lon_word(longitude, alarm=flags[0], movement=flags[1], global_ack=flags[2])
    )
    body += bytes([speed, key])
    body += struct.pack(">hhh", *accel)
    body.append(temperature & 0xFF)
    if altitude is not None:
        body += struct.pack(">H", altitude)
    if light is not None:
        body += struct.pack(">H", light)
    head = bytes([0xA5, counter, 0x91 if encrypted else 0xD1, len(body) + 1])
    return head + bytes([xor(head)]) + bytes(body) + bytes([xor(bytes(body))])


SYNTHETIC = [
    (
        "standard type, a fix south of Gaborone at hourly reporting, no alarms",
        frame(
            counter=7,
            encrypted=False,
            payload_type=0x01,
            master=0x0102,
            tag=0x2A3B,
            alarms=0x00,
            acks=0x02,
            version=42,
            interval=2,
            battery=3.87,
            epoch=1789552800,
            latitude=-24.6541,
            longitude=25.9087,
            hdop=2,
            flags=(False, True, False),
            speed=3,
            key=9,
            accel=(120, -45, 1010),
            temperature=27,
            altitude=None,
            light=None,
        ),
    ),
    (
        "altitude and light, low battery and tamper alarms, retries, 24 hours",
        frame(
            counter=200,
            encrypted=True,
            payload_type=0x05,
            master=0xFFFF,
            tag=0x0001,
            alarms=0x0A,
            acks=0x61,
            version=43,
            interval=5,
            battery=3.31,
            epoch=1789600000,
            latitude=-19.0154,
            longitude=23.4275,
            hdop=9,
            flags=(True, False, True),
            speed=0,
            key=1,
            accel=(-2000, 500, -1),
            temperature=41,
            altitude=940,
            light=612,
        ),
    ),
    (
        "minimal type, no fix yet (zero coordinates), clock not set",
        frame(
            counter=1,
            encrypted=False,
            payload_type=0x00,
            master=0,
            tag=7,
            alarms=0x20,
            acks=0x00,
            version=42,
            interval=1,
            battery=4.02,
            epoch=0,
            latitude=0.0,
            longitude=0.0,
            hdop=0,
            flags=(False, False, False),
            speed=0,
            key=0,
            accel=(0, 0, 0),
            temperature=19,
            altitude=None,
            light=None,
        ),
    ),
]


def main() -> int:
    frames_file = FIXTURES / "frames.jsonl"
    recorded = []
    if frames_file.exists():
        recorded = [
            json.loads(line)
            for line in frames_file.read_text().splitlines()
            if line.strip() and "synthetic" not in json.loads(line).get("kind", "synthetic")
        ]
    rows = [{"kind": "synthetic", "note": note, "data_hex": data.hex()} for note, data in SYNTHETIC]
    rows += recorded
    frames_file.write_text("".join(json.dumps(r) + "\n" for r in rows))
    shim = FIXTURES / "_shim.js"
    frames_json = FIXTURES / "_frames.json"
    shim.write_text(SHIM)
    frames_json.write_text(json.dumps(rows))
    try:
        out = subprocess.run(
            ["node", str(shim), str(FIXTURES / "decoder.js"), str(frames_json)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    finally:
        shim.unlink(missing_ok=True)
        frames_json.unlink(missing_ok=True)
    golden = [{"frame": r, "codec": c} for r, c in zip(rows, json.loads(out), strict=True)]
    (FIXTURES / "golden.json").write_text(json.dumps(golden, indent=2) + "\n")
    print(f"{len(golden)} frames through the codec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
