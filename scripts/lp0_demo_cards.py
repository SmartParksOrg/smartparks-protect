#!/usr/bin/env python3
"""Demo cards of an LP0 offload network (phase 42; Tim, 2026-10-16): three offload stations and
one collar with a month of synthetic data, uploaded to a project so the Offload page and the
import can be tried before a real card exists.

    uv run scripts/lp0_demo_cards.py --project-id <id> --email <ops> --password <secret> \\
        [--base-url https://dev-protect.smartparks.org] [--days 30] [--until YYYY-MM-DD] \\
        [--seed 42] [--out DIR]

What it makes: three RangerEdge stations (SP05xxxx) standing around a pygmy hippo's range in the
Gola Rainforest, each an Offload station entity with its place and its own LP0 credentials, and
one CollarEdge (SP10xxxx) on a hippo entity with its own credentials. The collar fixes every 15
minutes (port 2), reports its status every hour (port 4) and offloads once a day to the station
of the day; each station reports itself every hour on port 23 into its own card. The cards are
LP0 v5 files (the `lp0` object, ordinary LoRaWAN frames under each device's own keys, a 16-bit
counter that wraps once in the month) in `LOG_N` folders, one zip per station, uploaded on the
station's device. Keys are synthetic, derived from the seed, and never printed. A re-run finds
the devices by serial and the server refuses a file it already holds, so nothing doubles.
With `--out` the zips are written there, and beside each zip the card's own layout (a folder per
station with its `LOG_N` folders) for an SD card or Protect Go's folder picker, and nothing is
uploaded. The data ends at the run's hour unless `--until` names a day (the data then ends at
00:00 UTC of that day), so a second set for the same stations can cover another period and is
new to the server rather than a day-shifted copy of the first.
"""

import argparse
import base64
import hashlib
import io
import json
import math
import random
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from shared.connectivity.adapters.lp0_station.lorawan import Credentials, build_uplink
from shared.device_drivers.opencollar import (
    KNOWN_PORTS,
    LP0_COUNTERS,
    LP0_STATUS_BITS,
    PORT_LP0_STATISTICS,
    PORT_POSITION,
    PORT_STATUS,
)

FRAME_PAYLOAD_MAX = 222  # under the firmware's 228, whole records only
CENTER = (7.75, -10.88)  # the Gola Rainforest, Sierra Leone: pygmy hippo country
STATIONS = (
    ("SP050101", "0016C001F0500101", (7.762, -10.896)),
    ("SP050102", "0016C001F0500102", (7.741, -10.862)),
    ("SP050103", "0016C001F0500103", (7.736, -10.903)),
)
COLLAR = ("SP100001", "0016C001F0100001")
HIPPO = "Pygmy hippo Nyama"


@dataclass(slots=True)
class Frame:
    received_at: datetime
    phy: bytes
    source_eui: str
    session: int
    window: int
    slot: int
    rssi: int
    snr: int


@dataclass(slots=True)
class Station:
    name: str
    eui: str
    place: tuple[float, float]
    credentials: Credentials
    frames: list[Frame] = field(default_factory=list)
    counter: int = 1
    visits: int = 0
    data_frames: int = 0
    data_bytes: int = 0
    reports: int = 0


def keys_for(seed: int, eui: str) -> Credentials:
    """Synthetic per-device credentials from the seed: an address and two keys."""
    digest = hashlib.sha256(f"{seed}:{eui}".encode()).digest()
    dev_addr = ("2" + digest[:4].hex().upper())[:8]
    app = hashlib.sha256(digest + b"app").digest()[:16]
    nwk = hashlib.sha256(digest + b"nwk").digest()[:16]
    return Credentials(dev_addr, app, nwk)


def record(port: int, data: bytes, stored_at: datetime) -> bytes:
    """One flash record: port, message id, length, data, store time."""
    msg_id, length = KNOWN_PORTS.get(port, (0x9D, None))
    assert length is None or len(data) == length, (port, len(data))
    return bytes([port, msg_id, len(data)]) + data + struct.pack("<I", int(stored_at.timestamp()))


def position(lat: float, lon: float, when: datetime, rng: random.Random, heading: float) -> bytes:
    return struct.pack(
        "<BBBHiiiBBHBIB",
        1,
        0,
        0,
        rng.randint(8, 60),
        round(lat * 1e7),
        round(lon * 1e7),
        round((120 + rng.uniform(-4, 4)) * 1000),
        3,
        rng.randint(5, 11),
        rng.randint(4, 25),
        rng.randint(1, 4),
        int(when.timestamp()),
        1,
    ) + struct.pack("<HB", round(18000 + heading * 100) % 36000, rng.randint(0, 1))


def status(day: int, battery_mv: float, temperature: float, rng: random.Random) -> bytes:
    byte = lambda v: max(0, min(255, round((v + 100) * 255 / 200)))  # noqa: E731
    return struct.pack(
        "<14B",
        0,
        0,
        max(0, min(255, round((battery_mv - 2500) / 10))),
        0x80,
        byte(temperature),
        min(255, day),
        byte(rng.uniform(-1, 1)),
        byte(rng.uniform(-1, 1)),
        byte(-9.8 + rng.uniform(-0.3, 0.3)),
        0x14,
        0x81,  # firmware 8.1
        0x08,  # CollarEdge
        0,
        0,
    )


def report(station: Station, uptime_s: int) -> bytes:
    flags = sum(
        1 << LP0_STATUS_BITS.index(name)
        for name in (
            "card_detected",
            "card_writable",
            "sdfs_active",
            "lp0_enabled",
            "lp0_listening",
            "flash_available",
        )
    )
    counters = {name: 0 for name in LP0_COUNTERS}
    counters["visits_complete"] = station.visits
    counters["data_received"] = station.data_frames
    counters["data_saved"] = station.data_frames
    counters["data_saved_bytes"] = station.data_bytes
    counters["reports_generated"] = station.reports
    body = struct.pack("<BHHIHH", 1, flags, 0x07FF, uptime_s, 0, 2)
    body += struct.pack(f"<{len(LP0_COUNTERS)}I", *(counters[name] for name in LP0_COUNTERS))
    assert len(body) == 97
    return body


def pack_frames(records: list[bytes]) -> list[bytes]:
    """Whole records into payloads of at most `FRAME_PAYLOAD_MAX` bytes."""
    payloads: list[bytes] = []
    current = b""
    for item in records:
        if current and len(current) + len(item) > FRAME_PAYLOAD_MAX:
            payloads.append(current)
            current = b""
        current += item
    if current:
        payloads.append(current)
    return payloads


def walk(
    start: datetime, end: datetime, rng: random.Random, stations: list[Station]
) -> list[tuple[datetime, float, float, float]]:
    """A fix every 15 minutes: a hippo wandering between the river and the station of the day,
    which it reaches in the late afternoon."""
    fixes = []
    lat, lon = CENTER
    heading = 0.0
    when = start
    while when < end:
        day = (when - start).days
        target = stations[day % len(stations)].place
        hour = when.hour + when.minute / 60
        pull = 0.25 if 14 <= hour <= 18 else 0.04
        d_lat = (target[0] - lat) * pull + rng.gauss(0, 0.0009)
        d_lon = (target[1] - lon) * pull + rng.gauss(0, 0.0009)
        if hour < 6 or hour > 21:  # resting at night
            d_lat *= 0.15
            d_lon *= 0.15
        lat = max(CENTER[0] - 0.04, min(CENTER[0] + 0.04, lat + d_lat))
        lon = max(CENTER[1] - 0.04, min(CENTER[1] + 0.04, lon + d_lon))
        heading = (math.degrees(math.atan2(d_lon, d_lat)) + 360) % 360
        fixes.append((when, lat, lon, heading))
        when += timedelta(minutes=15)
    return fixes


def generate(
    days: int, seed: int, until: datetime | None = None
) -> tuple[list[Station], Credentials, datetime, datetime]:
    rng = random.Random(seed)
    end = until or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    stations = [
        Station(name=name, eui=eui, place=place, credentials=keys_for(seed, eui))
        for name, eui, place in STATIONS
    ]
    collar = keys_for(seed, COLLAR[1])
    fixes = walk(start, end, rng, stations)

    # the collar's records, offloaded once a day at 17:00 to the station of the day
    collar_counter = 65400  # wraps to zero within the month, as the firmware's allocator does
    last_offload = start
    battery = 4100.0
    for day in range(days):
        visit_at = start + timedelta(days=day, hours=17)
        if visit_at > end:
            break
        records: list[bytes] = []
        for when, lat, lon, heading in fixes:
            if last_offload < when <= visit_at:
                if when.minute == 0:
                    battery -= 0.35
                    records.append(
                        record(
                            PORT_STATUS,
                            status(day, battery, 26 + 4 * math.sin(when.hour / 24 * 6.283), rng),
                            when,
                        )
                    )
                records.append(record(PORT_POSITION, position(lat, lon, when, rng, heading), when))
        last_offload = visit_at
        station = stations[day % len(stations)]
        session = day + 1
        station.visits += 1
        for index, payload in enumerate(pack_frames(records)):
            phy = build_uplink(collar, collar_counter & 0xFFFF, 29, payload)
            collar_counter += 1
            station.frames.append(
                Frame(
                    received_at=visit_at + timedelta(seconds=2 * index),
                    phy=phy,
                    source_eui=COLLAR[1],
                    session=session,
                    window=index // 5 + 1,
                    slot=index % 5,
                    rssi=rng.randint(-95, -60),
                    snr=rng.randint(-2, 10),
                )
            )
            station.data_frames += 1
            station.data_bytes += len(phy)

    # each station's hourly report of itself, two per frame, into its own card
    for station in stations:
        when = start + timedelta(minutes=5)
        pending: list[tuple[datetime, bytes]] = []
        while when < end:
            station.reports += 1
            uptime = int((when - start).total_seconds())
            pending.append((when, record(PORT_LP0_STATISTICS, report(station, uptime), when)))
            if len(pending) == 2:
                phy = build_uplink(
                    station.credentials,
                    station.counter & 0xFFFF,
                    29,
                    b"".join(r for _, r in pending),
                )
                station.counter += 1
                station.frames.append(
                    Frame(
                        received_at=pending[-1][0],
                        phy=phy,
                        source_eui=station.eui,
                        session=0,
                        window=0,
                        slot=0,
                        rssi=-30,
                        snr=10,
                    )
                )
                pending = []
            when += timedelta(hours=1)
    return stations, collar, start, end


def line(station_eui: str, frame: Frame) -> str:
    """The station's JSON line, as `prv_stringify` in the firmware prints it (LP0 v5)."""
    document = {
        "gatewayEui": station_eui,
        "rxpk": {
            "time": frame.received_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tmst": int(frame.received_at.timestamp()),
            "freq": 864.629,
            "chan": 0,
            "rfch": 0,
            "stat": 1,
            "modu": "LORA",
            "datr": "SF7BW250",
            "codr": "4/5",
            "rssi": frame.rssi,
            "lsnr": frame.snr,
            "size": len(frame.phy),
            "data": base64.b64encode(frame.phy).decode(),
        },
        "lp0": {
            "version": 5,
            "source_eui": frame.source_eui,
            "session": frame.session,
            "window": frame.window,
            "slot": frame.slot,
        },
    }
    return "\n" + json.dumps(document)


def card_zip(station: Station) -> bytes:
    """The station's card: one file per day of reception in `LOG_N` folders of 64 files."""
    by_day: dict[datetime, list[Frame]] = {}
    for frame in sorted(station.frames, key=lambda f: f.received_at):
        day = frame.received_at.replace(hour=0, minute=0, second=0, microsecond=0)
        by_day.setdefault(day, []).append(frame)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (_, frames) in enumerate(sorted(by_day.items())):
            folder = f"LOG_{index // 64 + 1}"
            name = f"{station.eui}_{int(frames[0].received_at.timestamp())}.jsonl"
            archive.writestr(
                f"{folder}/{name}", "".join(line(station.eui, f) for f in frames) + "\n"
            )
    return buffer.getvalue()


class Api:
    def __init__(self, base_url: str, email: str, password: str) -> None:
        self.client = httpx.Client(base_url=base_url, timeout=120)
        token = self.client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        ).raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"

    def get(self, path: str, **params: object) -> dict | list:
        return self.client.get(path, params=params).raise_for_status().json()

    def post(self, path: str, **kwargs: object) -> httpx.Response:
        return self.client.post(path, **kwargs)  # type: ignore[arg-type]

    def device_by_serial(self, serial: str) -> dict | None:
        items = self.get("/api/v1/devices", q=serial, limit=5)["items"]  # type: ignore[index]
        return next((d for d in items if (d.get("serial_number") or "").upper() == serial), None)


def upload(
    api: Api, project_id: str, stations: list[Station], collar: Credentials, start: datetime
) -> None:
    types = api.get("/api/v1/device-types", limit=500)["items"]  # type: ignore[index]
    opencollar = next(
        (t for t in types if t["key"] == "opencollar_edge"),
        next((t for t in types if t["driver_key"] == "opencollar"), None),
    )
    if opencollar is None:
        sys.exit("the server has no OpenCollar device type")
    entity_types = {t["key"]: t for t in api.get("/api/v1/entity-types", limit=500)["items"]}  # type: ignore[index]
    hippo = entity_types.get("hippo") or entity_types["wildlife"]

    def in_project_since(device: dict) -> None:
        """A device made today holds its project from today; the month of records behind it
        needs the assignment to start at the window's start, which re-attributes what was
        decoded already (decision D103)."""
        detail = api.get(f"/api/v1/devices/{device['id']}")
        current = next(
            (
                a
                for a in detail["project_assignments"]  # type: ignore[index]
                if a["project_id"] == project_id and not a.get("valid_to")
            ),
            None,
        )
        if current is None:
            sys.exit(f"{device['name']}: not in the project")
        if datetime.fromisoformat(current["valid_from"]) <= start:
            return
        moved = api.post(
            f"/api/v1/devices/{device['id']}/project-assignments/{current['id']}/extend-start",
            json={"valid_from": start.isoformat()},
        )
        if moved.status_code != 200:
            sys.exit(f"{device['name']}: extend {moved.status_code} {moved.text}")
        print(f"{device['name']}: in the project since {start.date()}")

    def ensure_device(name: str, eui: str, credentials: Credentials) -> dict:
        existing = api.device_by_serial(eui)
        if existing is not None:
            print(f"{name}: device exists ({existing['id']})")
            in_project_since(existing)
            return existing
        response = api.post(
            f"/api/v1/projects/{project_id}/devices",
            json={
                "device_type_id": opencollar["id"],
                "name": name,
                "serial_number": eui,
                "firmware_version": "8.1",
                "attributes": {"demo": "lp0_demo_cards"},
                "lp0": {
                    "dev_addr": credentials.dev_addr,
                    "app_s_key": credentials.app_s_key.hex(),
                    "nwk_s_key": credentials.nwk_s_key.hex(),
                    "source": "person",
                },
            },
        )
        if response.status_code != 201:
            sys.exit(f"{name}: {response.status_code} {response.text}")
        print(f"{name}: device made with its LP0 credentials")
        device = response.json()
        in_project_since(device)
        return device

    for station in stations:
        device = ensure_device(station.name, station.eui, station.credentials)
        setup = api.post(
            f"/api/v1/projects/{project_id}/offload/stations",
            json={
                "device_id": device["id"],
                "entity_name": f"Station {station.name}",
                "latitude": station.place[0],
                "longitude": station.place[1],
            },
        )
        if setup.status_code != 201:
            sys.exit(f"{station.name}: setup {setup.status_code} {setup.text}")
        made = setup.json()
        print(
            f"{station.name}: offload station, entity {made['entity_name']}"
            f"{' (new)' if made['entity_created'] else ''}, gateway row"
            f"{' (new)' if made['gateway_created'] else ''}"
        )
        station_device_id = device["id"]
        card = card_zip(station)
        result = api.post(
            f"/api/v1/devices/{station_device_id}/offload-files",
            files={"file": (f"{station.name}-card.zip", card, "application/zip")},
        )
        if result.status_code == 201:
            files = result.json()["files"]
            print(
                f"{station.name}: card uploaded, {len(files)} files, "
                f"{sum(f['frames_total'] or 0 for f in files)} frames, decoding in the background"
            )
        elif result.status_code == 422:
            print(f"{station.name}: card not uploaded, {result.json().get('detail')}")
        else:
            sys.exit(f"{station.name}: upload {result.status_code} {result.text}")

    collar_device = ensure_device(COLLAR[0], COLLAR[1], collar)
    if collar_device.get("entity_id"):
        print(f"{COLLAR[0]}: tracks {collar_device['entity_name']} already")
    else:
        assigned = api.post(
            f"/api/v1/projects/{project_id}/entity-assignments",
            json={
                "device_id": collar_device["id"],
                "valid_from": start.isoformat(),
                "new_entity": {"name": HIPPO, "entity_type_id": hippo["id"]},
            },
        )
        if assigned.status_code != 201:
            sys.exit(f"{COLLAR[0]}: entity {assigned.status_code} {assigned.text}")
        print(f"{COLLAR[0]}: tracks {HIPPO} since {start.date()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project-id", help="the project the stations and the collar belong to")
    parser.add_argument("--base-url", default="https://dev-protect.smartparks.org")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--until",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC),
        help="the day the data ends at (00:00 UTC); default: the hour of the run",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out", type=Path, help="write the zips and the cards' folders here and upload nothing"
    )
    args = parser.parse_args()
    stations, collar, start, end = generate(args.days, args.seed, args.until)
    print(f"{args.days} days, {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC")
    for station in stations:
        own = sum(1 for f in station.frames if f.source_eui == station.eui)
        print(
            f"{station.name} ({station.eui}): {len(station.frames)} frames, "
            f"{len(station.frames) - own} of the collar over {station.visits} visits, {own} own reports"
        )
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for station in stations:
            card = card_zip(station)
            path = args.out / f"{station.name}-card.zip"
            path.write_bytes(card)
            folder = args.out / f"{station.name}-card"
            with zipfile.ZipFile(io.BytesIO(card)) as archive:
                archive.extractall(folder)
            files = sum(1 for _ in folder.rglob("*.jsonl"))
            print(f"wrote {path} ({path.stat().st_size} bytes) and {folder}/ ({files} files)")
        return
    if not (args.project_id and args.email and args.password):
        sys.exit("--project-id, --email and --password are needed to upload (or use --out)")
    api = Api(args.base_url, args.email, args.password)
    upload(api, args.project_id, stations, collar, start)


if __name__ == "__main__":
    main()
