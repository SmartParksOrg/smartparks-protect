#!/usr/bin/env python3
"""Synthetic benchmark dataset (architecture 13.9), scalable to the reference envelope.

    uv run scripts/benchmark/generate.py --scale 0.01          # 2.5 M positions, 10 M measurements
    uv run scripts/benchmark/generate.py --scale 0.1 --workers 6
    uv run scripts/benchmark/generate.py --scale 0.2 --workers 4 --compress   # on a small disk
    uv run scripts/benchmark/generate.py --reset                # remove every benchmark row

The envelope at scale 1 is 10,000 active devices, 5,000 entities, 250 million positions and
1 billion measurements. Devices report at a fixed interval between 5 minutes and 1 hour with
jitter; positions walk around a home range inside one of eight parks; four measurements go
with every position (battery, temperature, activity, satellites). Rows go in with COPY, in
time blocks (oldest first, decision D91) from several connections, and `--compress` compresses
the chunks behind the write frontier so the disk holds compressed history plus one block. Raw
source events are not generated: they would
double the volume and the ingest benchmark produces real ones.

Everything the generator creates is named `bench-...` or lives in a `Benchmark ...` project,
so `--reset` can remove it again.
"""

import argparse
import asyncio
import io
import json
import math
import os
import random
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg

_here = Path(__file__).resolve()
if len(_here.parents) > 2:  # from the checkout; inside a container the package is installed
    sys.path.insert(0, str(_here.parents[2] / "shared"))
from shared.connectivity.transports.http import hash_token, new_webhook_token  # noqa: E402

ENVELOPE = {
    "devices": 10_000,
    "entities": 5_000,
    "positions": 250_000_000,
    "measurements": 1_000_000_000,
}
PARKS = [
    ("Kruger", -24.0, 31.5),
    ("Akagera", -1.9, 30.7),
    ("Liwonde", -14.8, 35.3),
    ("Garamba", 4.0, 29.5),
    ("Gonarezhou", -21.6, 31.9),
    ("Kafue", -15.0, 26.0),
    ("Zakouma", 10.8, 19.7),
    ("Odzala", 0.6, 14.9),
]
INTERVALS = [(300, 0.35), (600, 0.25), (900, 0.15), (1800, 0.15), (3600, 0.10)]  # seconds, weight
METRICS = ("battery_voltage", "device_temperature", "activity", "gnss_satellites")
BATCH_ROWS = 200_000


def database_dsn() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://protect:protect-dev-password@localhost:5432/smartparks_protect",
    )
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def reset(conn: asyncpg.Connection) -> None:
    # Deleting from compressed chunks decompresses them; lift the per-transaction limit.
    await conn.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
    projects = [
        r["id"] for r in await conn.fetch("SELECT id FROM projects WHERE slug LIKE 'bench-%'")
    ]
    if projects:
        for table in ("measurements", "positions", "device_state_history"):
            await conn.execute(f"DELETE FROM {table} WHERE project_id = ANY($1::uuid[])", projects)
        await conn.execute(
            "DELETE FROM source_events WHERE device_id IN (SELECT id FROM devices WHERE name LIKE 'bench-%')"
        )
        await conn.execute("DELETE FROM projects WHERE id = ANY($1::uuid[])", projects)
    await conn.execute(
        "DELETE FROM device_current_state WHERE device_id IN (SELECT id FROM devices WHERE name LIKE 'bench-%')"
    )
    await conn.execute("DELETE FROM external_identities WHERE external_id LIKE 'BENCH%'")
    await conn.execute("DELETE FROM devices WHERE name LIKE 'bench-%'")
    await conn.execute("DELETE FROM data_sources WHERE name LIKE 'Benchmark source%'")
    await conn.execute("DELETE FROM device_types WHERE key = 'bench_collar'")
    await conn.execute("DELETE FROM entity_types WHERE key = 'bench_animal'")


async def registry(conn: asyncpg.Connection, scale: float, sources: int, since: datetime) -> dict:
    """Projects, types, data sources, devices, entities and assignments. Returns what the load
    needs: device ids with their park, entity and interval."""
    n_devices = max(2, round(ENVELOPE["devices"] * scale))
    n_entities = max(1, round(ENVELOPE["entities"] * scale))
    entity_type = await conn.fetchval(
        "INSERT INTO entity_types (key, label, group_key, icon_key) VALUES ('bench_animal', 'Benchmark animal', 'tracked', 'wildlife.generic') RETURNING id"
    )
    device_type = await conn.fetchval(
        "INSERT INTO device_types (key, label, driver_key, icon_key) VALUES ('bench_collar', 'Benchmark collar', 'generic_json', 'device.sensor') RETURNING id"
    )
    tokens = []
    source_ids = []
    for i in range(sources):
        token = new_webhook_token()
        tokens.append(token)
        source_ids.append(
            await conn.fetchval(
                "INSERT INTO data_sources (name, adapter_key, config, webhook_token_hash) VALUES ($1, 'generic_http', '{}', $2) RETURNING id",
                f"Benchmark source {i + 1}",
                hash_token(token),
            )
        )
    projects = []
    for name, lat, lon in PARKS:
        project_id = await conn.fetchval(
            "INSERT INTO projects (name, slug, timezone, settings) VALUES ($1, $2, 'Africa/Johannesburg', '{}') RETURNING id",
            f"Benchmark {name}",
            f"bench-{name.lower()}",
        )
        for source_id in source_ids:
            await conn.execute(
                "INSERT INTO data_source_project_scopes (data_source_id, project_id) VALUES ($1, $2)",
                source_id,
                project_id,
            )
        projects.append((project_id, name, lat, lon))

    rng = random.Random(1)
    entities = []
    for i in range(n_entities):
        project_id, park, lat, lon = projects[i % len(projects)]
        home_lat = lat + rng.gauss(0, 0.25)
        home_lon = lon + rng.gauss(0, 0.25)
        entities.append((uuid.uuid4(), project_id, f"bench {park} {i:05d}", home_lat, home_lon))
    await conn.copy_records_to_table(
        "entities",
        records=[(e[0], e[1], entity_type, e[2], "active", "{}") for e in entities],
        columns=["id", "project_id", "entity_type_id", "name", "status", "attributes"],
    )

    devices = []
    for i in range(n_devices):
        interval = rng.choices([s for s, _ in INTERVALS], [w for _, w in INTERVALS])[0]
        entity = (
            entities[i % n_entities] if i < n_entities * 2 else None
        )  # up to two devices per entity
        project_id = entity[1] if entity else projects[i % len(projects)][0]
        home = (
            (entity[3], entity[4])
            if entity
            else (projects[i % len(projects)][2], projects[i % len(projects)][3])
        )
        devices.append(
            {
                "id": uuid.uuid4(),
                "name": f"bench-{i:05d}",
                "project_id": project_id,
                "entity_id": entity[0] if entity else None,
                "home": home,
                "interval": interval,
                "source_id": source_ids[i % sources],
            }
        )
    await conn.copy_records_to_table(
        "devices",
        records=[(d["id"], device_type, d["name"], "active", "{}") for d in devices],
        columns=["id", "device_type_id", "name", "status", "attributes"],
    )
    await conn.copy_records_to_table(
        "external_identities",
        records=[
            (d["source_id"], d["id"], f"BENCH{i:08X}", "device_id", "{}")
            for i, d in enumerate(devices)
        ],
        columns=["data_source_id", "device_id", "external_id", "identity_type", "attributes"],
    )
    await conn.executemany(
        "INSERT INTO device_project_assignments (device_id, project_id, validity) VALUES ($1, $2, tstzrange($3, NULL, '[)'))",
        [(d["id"], d["project_id"], since) for d in devices],
    )
    await conn.executemany(
        "INSERT INTO device_entity_assignments (device_id, entity_id, validity) VALUES ($1, $2, tstzrange($3, NULL, '[)'))",
        [(d["id"], d["entity_id"], since) for d in devices if d["entity_id"] is not None],
    )
    return {
        "devices": devices,
        "projects": projects,
        "tokens": tokens,
        "source_ids": source_ids,
        "n_entities": n_entities,
    }


class Walker:
    """The positions and measurements of one device: an Ornstein-Uhlenbeck walk around the
    home, advanced block by block so rows can be written in time order (decision D91)."""

    def __init__(
        self,
        device: dict,
        since: datetime,
        until: datetime,
        positions_per_device: int,
        rng: random.Random,
    ) -> None:
        self.rng = rng
        interval = device["interval"]
        self.since = since
        span = (until - since).total_seconds()
        self.count = min(positions_per_device, int(span // interval))
        self.step = span / max(self.count, 1)
        self.lat, self.lon = device["home"]
        self.home_lat, self.home_lon = device["home"]
        self.sigma = 0.0005 * math.sqrt(interval / 300)  # about 50 m per 5 minutes
        self.battery = rng.uniform(3.9, 4.15)
        self.drain = rng.uniform(0.2, 0.5) / max(self.count, 1)  # volts over the whole span
        self.k = 0

    def rows(
        self, block_end: datetime
    ) -> Iterator[tuple[datetime, float, float, float, float, float, int]]:
        """Every sample up to `block_end`, in time order; the walk state carries over."""
        rng = self.rng
        while self.k < self.count:
            t = self.since + timedelta(
                seconds=self.k * self.step + rng.uniform(-0.1, 0.1) * self.step
            )
            if t >= block_end:
                return
            self.k += 1
            self.lat += 0.05 * (self.home_lat - self.lat) + rng.gauss(0, self.sigma)
            self.lon += 0.05 * (self.home_lon - self.lon) + rng.gauss(0, self.sigma)
            hour = t.hour + t.minute / 60
            activity = max(
                0.0,
                min(100.0, 50 + 40 * math.sin((hour - 6) / 24 * 2 * math.pi) + rng.gauss(0, 12)),
            )
            temperature = 24 + 8 * math.sin((hour - 9) / 24 * 2 * math.pi) + rng.gauss(0, 1)
            self.battery -= self.drain
            satellites = rng.randint(4, 12)
            yield t, self.lat, self.lon, activity, temperature, self.battery, satellites


async def load_devices(
    dsn: str,
    devices: list[dict],
    since: datetime,
    until: datetime,
    positions_per_device: int,
    seed: int,
    progress: dict,
    blocks: list[datetime],
    barrier: asyncio.Barrier,
) -> None:
    """One worker: its shard of devices, block by block. Every worker waits at the barrier
    after each block, so the write frontier moves in step and chunks behind it can be
    compressed while the run continues."""
    conn = await asyncpg.connect(dsn)
    try:
        walkers = []
        for device in devices:
            rng = random.Random(f"{seed}-{device['name']}")
            walkers.append((device, Walker(device, since, until, positions_per_device, rng)))
        for block_end in blocks:
            position_rows: list[str] = []
            measurement_rows: list[tuple] = []
            for device, walker in walkers:
                rng = walker.rng
                device_id, project_id, entity_id = (
                    device["id"],
                    device["project_id"],
                    device["entity_id"],
                )
                source_id = device["source_id"]
                for t, lat, lon, activity, temperature, battery, satellites in walker.rows(
                    block_end
                ):
                    ingested = t + timedelta(seconds=rng.uniform(2, 60))
                    stamp = t.isoformat()
                    key = f"{device_id}|gnss|{int(t.timestamp())}"
                    position_rows.append(
                        f"{stamp},{ingested.isoformat()},{device_id},{project_id},{entity_id or ''},{source_id},gnss,{key},"
                        f"SRID=4326;POINT({lon:.6f} {lat:.6f}),{rng.uniform(280, 420):.1f},{rng.randint(3, 40)},{satellites},{{}}\n"
                    )
                    for metric, value in (
                        ("battery_voltage", round(battery, 3)),
                        ("device_temperature", round(temperature, 2)),
                        ("activity", round(activity, 1)),
                        ("gnss_satellites", float(satellites)),
                    ):
                        measurement_rows.append(
                            (
                                t,
                                ingested,
                                device_id,
                                project_id,
                                entity_id,
                                source_id,
                                metric,
                                f"{device_id}|{metric}|{int(t.timestamp())}",
                                value,
                            )
                        )
                if len(measurement_rows) >= BATCH_ROWS:
                    await flush(conn, position_rows, measurement_rows, progress)
                    position_rows, measurement_rows = [], []
            await flush(conn, position_rows, measurement_rows, progress)
            await barrier.wait()
    finally:
        await conn.close()


async def compress_behind(
    dsn: str, blocks: list[datetime], barrier: asyncio.Barrier, progress: dict
) -> None:
    """After every block, compress the chunks that end before the block that was just written
    (they receive no more rows), so the disk holds compressed history plus one block."""
    conn = await asyncpg.connect(dsn)
    try:
        for block_end in blocks:
            await barrier.wait()
            for table in ("positions", "measurements"):
                chunks = await conn.fetch(
                    """
                    SELECT format('%I.%I', chunk_schema, chunk_name) AS chunk
                    FROM timescaledb_information.chunks
                    WHERE hypertable_name = $1 AND NOT is_compressed AND range_end <= $2
                    """,
                    table,
                    block_end - timedelta(days=1),
                )
                for row in chunks:
                    await conn.execute(
                        f"SELECT compress_chunk('{row['chunk']}', if_not_compressed => true)"
                    )
                    progress["compressed"] = progress.get("compressed", 0) + 1
    finally:
        await conn.close()


async def flush(
    conn: asyncpg.Connection,
    position_rows: list[str],
    measurement_rows: list[tuple],
    progress: dict,
) -> None:
    if position_rows:
        await conn.copy_to_table(
            "positions",
            source=io.BytesIO("".join(position_rows).encode()),
            columns=[
                "time",
                "ingested_at",
                "device_id",
                "project_id",
                "entity_id",
                "data_source_id",
                "record_type",
                "canonical_key",
                "geom",
                "altitude_m",
                "accuracy_m",
                "satellites",
                "attributes",
            ],
            format="csv",
            null="",
        )
    if measurement_rows:
        await conn.copy_records_to_table(
            "measurements",
            records=measurement_rows,
            columns=[
                "time",
                "ingested_at",
                "device_id",
                "project_id",
                "entity_id",
                "data_source_id",
                "metric_key",
                "canonical_key",
                "value_num",
            ],
        )
    progress["positions"] += len(position_rows)
    progress["measurements"] += len(measurement_rows)
    done = progress["positions"]
    if done // 500_000 != (done - len(position_rows)) // 500_000:
        elapsed = time.perf_counter() - progress["started"]
        sys.stderr.write(
            f"  {done:>12,} positions  {progress['measurements']:>14,} measurements  {elapsed:7.0f} s\n"
        )


async def current_state(conn: asyncpg.Connection) -> None:
    """Latest position per device and entity, as the decoder would have left it."""
    await conn.execute(
        """
        INSERT INTO device_current_state (device_id, last_seen_at, latest_position_time, latest_position, latest_state, battery_voltage)
        SELECT DISTINCT ON (p.device_id) p.device_id, p.time, p.time, p.geom, '{}'::jsonb, NULL
        FROM positions p JOIN devices d ON d.id = p.device_id
        WHERE d.name LIKE 'bench-%'
        ORDER BY p.device_id, p.time DESC
        ON CONFLICT (device_id) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at,
            latest_position_time = EXCLUDED.latest_position_time, latest_position = EXCLUDED.latest_position
        """
    )
    await conn.execute(
        """
        INSERT INTO entity_current_state (entity_id, project_id, device_id, last_seen_at, latest_position_time, latest_position, status_summary)
        SELECT DISTINCT ON (p.entity_id) p.entity_id, p.project_id, p.device_id, p.time, p.time, p.geom, '{}'::jsonb
        FROM positions p JOIN projects pr ON pr.id = p.project_id
        WHERE pr.slug LIKE 'bench-%' AND p.entity_id IS NOT NULL
        ORDER BY p.entity_id, p.time DESC
        ON CONFLICT (entity_id) DO UPDATE SET device_id = EXCLUDED.device_id, last_seen_at = EXCLUDED.last_seen_at,
            latest_position_time = EXCLUDED.latest_position_time, latest_position = EXCLUDED.latest_position
        """
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scale", type=float, default=0.01, help="fraction of the reference envelope"
    )
    parser.add_argument("--days", type=int, default=365, help="history span ending now")
    parser.add_argument("--sources", type=int, default=2, help="number of data sources")
    parser.add_argument("--workers", type=int, default=4, help="parallel connections for the load")
    parser.add_argument(
        "--block-days",
        type=int,
        default=7,
        help="rows are written in time blocks of this many days, oldest first",
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="compress chunks behind the write frontier while loading (keeps the disk small)",
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--reset", action="store_true", help="remove benchmark rows and stop")
    parser.add_argument("--manifest", type=Path, help="write the dataset manifest as JSON here")
    args = parser.parse_args()

    dsn = database_dsn()
    conn = await asyncpg.connect(dsn)
    started = time.perf_counter()
    try:
        existing = await conn.fetchval("SELECT count(*) FROM projects WHERE slug LIKE 'bench-%'")
        if existing:
            sys.stderr.write("removing the previous benchmark dataset\n")
            await reset(conn)
        if args.reset:
            sys.stdout.write("benchmark rows removed\n")
            return
        until = datetime.now(UTC)
        since = until - timedelta(days=args.days)
        reg = await registry(conn, args.scale, args.sources, since)
    finally:
        await conn.close()

    devices = reg["devices"]
    target_positions = round(ENVELOPE["positions"] * args.scale)
    per_device = max(1, target_positions // len(devices))
    sys.stderr.write(
        f"{len(devices)} devices, {reg['n_entities']} entities, about {target_positions:,} positions over {args.days} days, {args.workers} workers\n"
    )
    progress = {"positions": 0, "measurements": 0, "started": time.perf_counter()}
    shards = [devices[i :: args.workers] for i in range(args.workers)]
    blocks: list[datetime] = []
    cursor = since
    while cursor < until:
        cursor = min(cursor + timedelta(days=args.block_days), until)
        blocks.append(cursor)
    blocks[-1] = until + timedelta(days=1)  # the last block takes every remaining sample
    parties = len(shards) + (1 if args.compress else 0)
    barrier = asyncio.Barrier(parties)
    tasks = [
        load_devices(dsn, shard, since, until, per_device, args.seed, progress, blocks, barrier)
        for shard in shards
    ]
    if args.compress:
        tasks.append(compress_behind(dsn, blocks, barrier, progress))
    await asyncio.gather(*tasks)
    if progress.get("compressed"):
        sys.stderr.write(f"  compressed {progress['compressed']} chunks during the load\n")

    conn = await asyncpg.connect(dsn)
    try:
        await current_state(conn)
        await conn.execute("ANALYZE positions")
        await conn.execute("ANALYZE measurements")
        size = await conn.fetchrow(
            "SELECT pg_size_pretty(hypertable_size('positions')) AS positions, pg_size_pretty(hypertable_size('measurements')) AS measurements"
        )
    finally:
        await conn.close()
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scale": args.scale,
        "days": args.days,
        "devices": len(devices),
        "entities": reg["n_entities"],
        "projects": [name for _, name, _, _ in reg["projects"]],
        "positions": progress["positions"],
        "measurements": progress["measurements"],
        "table_sizes": dict(size),
        "seconds": round(time.perf_counter() - started, 1),
        "webhook_tokens": {
            str(s): t for s, t in zip(reg["source_ids"], reg["tokens"], strict=True)
        },
    }
    if args.manifest:
        args.manifest.write_text(json.dumps(manifest, indent=1))
    public = {k: v for k, v in manifest.items() if k != "webhook_tokens"}
    sys.stdout.write(json.dumps(public, indent=1) + "\n")
    sys.stdout.write(
        "webhook tokens for the ingest benchmark are in the manifest file only\n"
        if args.manifest
        else json.dumps(manifest["webhook_tokens"]) + "\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
