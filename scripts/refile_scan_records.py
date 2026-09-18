"""Refile the scan records a device's bad clock put in the wrong place (decision D259).

A scan leaves three kinds of record: the sightings, the record of the scan, and the count of what
it detected. They are one reading of one clock, so they belong at one time. Until 2026-09-18 the
clock rule moved only the sightings, so a device whose clock runs far behind had the scan and the
count filed at the time the device claimed while its sightings were filed at the delivery — the
same scan in two places, 45 hours apart on the PWN reader that showed it.

This removes those records so that a reprocess writes them back where they belong.

Removing them is not the first choice and not a light one. Moving them in place was tried first
and the database refuses it: `time` partitions the hypertable, each chunk carries a check
constraint on its own range, and an update that would carry a row into another chunk fails. So
the only way to refile a record is to write it again, which means the old one has to go.

Nothing is lost by that. Every row here is derived from a source event that Protect keeps for
ever, and `reprocess_source_events.py --port 7 --port 11` rebuilds each one at the time the rule
says it belongs at. Nothing else is touched: not a sighting, which was already filed correctly,
and not a position, which the rule deliberately leaves alone.

    docker compose cp scripts/refile_scan_records.py decoder:/tmp/r.py
    docker compose exec decoder /app/.venv/bin/python /tmp/r.py
    docker compose exec decoder /app/.venv/bin/python /tmp/r.py --apply

Without `--apply` it only reports, which is how to see the scope before agreeing to it. Safe to
run again: a record already at its delivery time is no longer far behind it, so a second run
finds nothing.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from shared.database import session_scope

# what the rule itself uses; a record further behind its delivery than this is not believed
TOLERANCE = "24 hours"

SURVEY = text(
    f"""
    SELECT d.name,
           count(*) FILTER (WHERE k.kind = 'state')   AS states,
           count(*) FILTER (WHERE k.kind = 'reading') AS readings,
           max(EXTRACT(EPOCH FROM (k.ingested_at - k.time)) / 3600)::int AS worst_hours
    FROM (
        SELECT h.device_id, h.time, se.ingested_at, 'state' AS kind
        FROM device_state_history h
        JOIN source_events se
          ON se.id = h.source_event_id AND se.ingested_at = h.source_event_ingested_at
        WHERE h.state ? 'ble_scan' AND se.ingested_at - h.time > interval '{TOLERANCE}'
        UNION ALL
        SELECT m.device_id, m.time, se.ingested_at, 'reading'
        FROM measurements m
        JOIN source_events se
          ON se.id = m.source_event_id AND se.ingested_at = m.source_event_ingested_at
        WHERE m.metric_key = 'ble_contacts'
          AND se.ingested_at - m.time > interval '{TOLERANCE}'
    ) k
    JOIN devices d ON d.id = k.device_id
    GROUP BY 1 ORDER BY 1
    """
)

DROP_STATES = text(
    f"""
    DELETE FROM device_state_history h
    USING source_events se
    WHERE se.id = h.source_event_id AND se.ingested_at = h.source_event_ingested_at
      AND h.state ? 'ble_scan'
      AND se.ingested_at - h.time > interval '{TOLERANCE}'
    """
)

DROP_READINGS = text(
    f"""
    DELETE FROM measurements m
    USING source_events se
    WHERE se.id = m.source_event_id AND se.ingested_at = m.source_event_ingested_at
      AND m.metric_key = 'ble_contacts'
      AND se.ingested_at - m.time > interval '{TOLERANCE}'
    """
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Remove them; without this it only reports"
    )
    args = parser.parse_args()

    async with session_scope() as session:
        rows = (await session.execute(SURVEY)).all()
    if not rows:
        print("every scan record is filed with its own sightings")
        return
    for row in rows:
        print(
            f"  {row.name}: {row.states} scans, {row.readings} readings, "
            f"worst {row.worst_hours} h behind their delivery"
        )
    if not args.apply:
        print("report only; pass --apply to remove them, then reprocess ports 7 and 11")
        return

    async with session_scope() as session:
        states = (await session.execute(DROP_STATES)).rowcount
        readings = (await session.execute(DROP_READINGS)).rowcount
        await session.commit()
    print(f"removed {states} scans and {readings} readings")
    print("now run: reprocess_source_events.py --port 7 --port 11")


asyncio.run(main())
