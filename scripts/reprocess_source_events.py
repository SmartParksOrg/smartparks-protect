"""Decode stored source events again, for data that arrived before its decoder existed.

A source event is decoded once and nothing revisits it: a message that produced no canonical
rows stays that way, however much the driver later learns. The PWN readers had been scanning
since 8 September 2026 and every one of those 2,112 messages sat decoded into nothing, because
ports 7 and 11 produced no rows until phase 30. This walks such events oldest first, decodes
each in its own transaction and publishes what came of it, the way the identity walk in the
decoder service does (`on_identity_reprocess`).

Decoding is idempotent: a row that already exists is counted as a duplicate and written once
(ADR 0008), so a second run is safe and a half-finished run is resumed by running it again.

It needs the decoder's imports, its database and its bus, so it runs inside that container:

    docker compose cp scripts/reprocess_source_events.py decoder:/tmp/r.py
    docker compose exec decoder /app/.venv/bin/python /tmp/r.py --port 7 --port 11 --dry-run
    docker compose exec decoder /app/.venv/bin/python /tmp/r.py --port 7 --port 11

The image has no `python` on its PATH: the service runs `/app/.venv/bin/python` and so must this.

Without `--port` it takes every event of the devices named, which is a much bigger thing to ask
for: prefer the ports that changed.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from sqlalchemy import text

from protect_decoder.pipeline import process_source_event, publish_outcome
from shared.bus import RedisStreamsBus
from shared.database import session_scope
from shared.logger import get_logger

log = get_logger("reprocess")
REPORT_EVERY = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", action="append", default=[], help="LoRaWAN fPort; repeatable")
    parser.add_argument("--device", action="append", default=[], help="Device name; repeatable")
    parser.add_argument("--since", help="Only events ingested at or after this ISO timestamp")
    parser.add_argument("--dry-run", action="store_true", help="Count them and stop")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.port and not args.device:
        raise SystemExit("give --port or --device; reprocessing everything is never what is meant")
    where = ["se.device_id IS NOT NULL"]
    params: dict[str, object] = {}
    if args.port:
        where.append("se.provider_metadata->>'f_port' = ANY(:ports)")
        params["ports"] = [str(p) for p in args.port]
    if args.device:
        where.append("d.name = ANY(:names)")
        params["names"] = list(args.device)
    if args.since:
        where.append("se.ingested_at >= :since")
        params["since"] = args.since
    statement = text(
        "SELECT se.id, se.ingested_at FROM source_events se "
        "JOIN devices d ON d.id = se.device_id "
        f"WHERE {' AND '.join(where)} ORDER BY se.ingested_at, se.id"
    )
    async with session_scope() as session:
        rows = (await session.execute(statement, params)).all()
    print(f"{len(rows)} source events to decode")
    if args.dry_run or not rows:
        return

    bus = RedisStreamsBus()
    counts: Counter[str] = Counter()
    try:
        for index, (event_id, ingested_at) in enumerate(rows, 1):
            try:
                async with session_scope() as session:
                    outcome = await process_source_event(
                        session, int(event_id), ingested_at, reprocess=True
                    )
                    await session.commit()
                await publish_outcome(bus, outcome)
                for kind, made in outcome.created.items():
                    counts[kind] += made
                counts["duplicates"] += outcome.duplicates
                counts["decoded"] += 1
            except Exception as error:  # one bad frame must not stop the rest
                counts["failed"] += 1
                log.warning("reprocess failed", source_event_id=int(event_id), error=str(error))
            if index % REPORT_EVERY == 0:
                print(f"  {index}/{len(rows)} {dict(counts)}", flush=True)
    finally:
        await bus.close()
    print(f"done: {dict(counts)}")


asyncio.run(main())
