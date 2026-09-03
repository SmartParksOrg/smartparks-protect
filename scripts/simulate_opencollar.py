#!/usr/bin/env python3
"""Publish recorded uplinks as ChirpStack MQTT integration events.

The events land on the same broker and topics a real ChirpStack publishes to, so the ingest
service and everything after it run exactly as in production. The LoRaWAN radio path (gateway
bridge, join, MIC, deduplication) is not simulated; ChirpStack itself is exercised by the
bootstrap script and by a real gateway.

    uv run scripts/simulate_opencollar.py --fixtures tests/fixtures/payloads/opencollar/uplinks.jsonl \
        --dev-eui 70B3D57ED0001234 --application-id <chirpstack application id> --rate 2

Fixture lines are JSON objects with at least `f_port` and `data_hex`; optional `time` (offset from
now in seconds, negative for the past), `f_cnt`, `rssi`, `snr`, `spreading_factor`.
Without `--fixtures`, a synthetic track around the given start point is produced from the
generic JSON driver's payload format, so the pipeline can be watched without OpenCollar payloads.
"""

import argparse
import asyncio
import base64
import json
import math
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiomqtt


def chirpstack_event(
    *,
    dev_eui: str,
    application_id: str,
    f_port: int,
    data: bytes,
    f_cnt: int,
    time: datetime,
    rssi: float,
    snr: float,
    spreading_factor: int,
    device_name: str,
    gateway_id: str,
) -> dict:
    return {
        "deduplicationId": str(uuid.uuid4()),
        "time": time.isoformat().replace("+00:00", "Z"),
        "deviceInfo": {
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "tenantName": "Simulator",
            "applicationId": application_id,
            "applicationName": "Simulator",
            "deviceProfileId": "00000000-0000-0000-0000-000000000000",
            "deviceProfileName": "Simulated OpenCollar",
            "deviceName": device_name,
            "devEui": dev_eui.lower(),
            "tags": {"simulated": "true"},
        },
        "devAddr": "01234567",
        "adr": True,
        "dr": 5,
        "fCnt": f_cnt,
        "fPort": f_port,
        "confirmed": False,
        "data": base64.b64encode(data).decode(),
        "rxInfo": [
            {
                "gatewayId": gateway_id,
                "uplinkId": random.randint(1, 2**31),
                "rssi": rssi,
                "snr": snr,
                "metadata": {"region_name": "eu868", "region_common_name": "EU868"},
            }
        ],
        "txInfo": {
            "frequency": 868100000,
            "modulation": {
                "lora": {
                    "bandwidth": 125000,
                    "spreadingFactor": spreading_factor,
                    "codeRate": "CR_4_5",
                }
            },
        },
    }


def load_fixtures(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def synthetic(count: int, lat: float, lon: float, interval: float) -> list[dict]:
    """Generic JSON payloads on port 1 walking a slow circle, one every `interval` seconds."""
    items = []
    for i in range(count):
        angle = i / count * 2 * math.pi
        payload = {
            "time": (datetime.now(UTC) - timedelta(seconds=(count - i) * interval)).isoformat(),
            "lat": round(lat + 0.01 * math.sin(angle), 6),
            "lon": round(lon + 0.01 * math.cos(angle), 6),
            "altitude": 300 + random.uniform(-5, 5),
            "speed": round(random.uniform(0, 1.5), 2),
            "measurements": {
                "battery_voltage": round(3.9 - i * 0.001, 3),
                "temperature": round(25 + 5 * math.sin(angle), 1),
                "activity": random.randint(0, 100),
            },
        }
        items.append(
            {
                "f_port": 1,
                "data_hex": json.dumps(payload).encode().hex(),
                "f_cnt": i + 1,
                "rssi": random.uniform(-110, -60),
                "snr": random.uniform(-5, 10),
                "spreading_factor": random.choice([7, 9, 12]),
            }
        )
    return items


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--dev-eui", default="70B3D57ED0001234")
    parser.add_argument("--device-name", default="Simulated collar")
    parser.add_argument("--application-id", default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--gateway-id", default="0016c001f153a14c")
    parser.add_argument("--fixtures", type=Path, help="JSON lines with f_port and data_hex")
    parser.add_argument(
        "--count", type=int, default=20, help="synthetic uplinks when no fixtures are given"
    )
    parser.add_argument("--lat", type=float, default=-24.9)
    parser.add_argument("--lon", type=float, default=31.5)
    parser.add_argument("--rate", type=float, default=1.0, help="uplinks per second")
    parser.add_argument("--loop", action="store_true", help="repeat forever")
    args = parser.parse_args()

    items = (
        load_fixtures(args.fixtures)
        if args.fixtures
        else synthetic(args.count, args.lat, args.lon, 1 / args.rate)
    )
    topic = f"application/{args.application_id}/device/{args.dev_eui.lower()}/event/up"
    sent = 0
    async with aiomqtt.Client(
        args.host, port=args.port, identifier=f"protect-simulator-{uuid.uuid4().hex[:6]}"
    ) as client:
        while True:
            for i, item in enumerate(items):
                offset = float(item.get("time", 0))
                event = chirpstack_event(
                    dev_eui=args.dev_eui,
                    application_id=args.application_id,
                    f_port=int(item["f_port"]),
                    data=bytes.fromhex(item["data_hex"]),
                    f_cnt=int(item.get("f_cnt", i + 1)),
                    time=datetime.now(UTC) + timedelta(seconds=offset),
                    rssi=float(item.get("rssi", -80)),
                    snr=float(item.get("snr", 5)),
                    spreading_factor=int(item.get("spreading_factor", 9)),
                    device_name=args.device_name,
                    gateway_id=args.gateway_id,
                )
                await client.publish(topic, json.dumps(event).encode())
                sent += 1
                sys.stdout.write(f"\rsent {sent} uplinks on {topic}")
                sys.stdout.flush()
                await asyncio.sleep(1 / args.rate)
            if not args.loop:
                break
    sys.stdout.write("\n")


if __name__ == "__main__":
    asyncio.run(main())
