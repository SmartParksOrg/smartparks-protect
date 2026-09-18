"""Set static places from the coordinates a network keeps in its own device tags. A one-off.

Some networks carry a device's place in the tags of every uplink. PWN's ChirpStack does: the
readers there arrive with `tags.scanner = "yes"` and `tags.latitude` / `tags.longitude`, which is
where somebody wrote down the post the reader stands on.

**This is deliberately not a mechanism** (Tim, 2026-09-18). Protect never reads a place out of a
network's tags on its own, and this script does not install anything that would. A tag is
somebody else's metadata: nobody promises it is kept current, nothing says who last edited it or
when, and a place taken from it silently would be a position on the map with no accountable
origin. Setting a place is a statement by a person that a device does not move (decision D261),
so a person runs this, reads what it proposes, and accepts it.

What it does: reads the newest stored uplink of every device, takes the tag coordinates when they
are there, and sets the static place of the devices that have none. A device that already has a
place is left alone — a measurement somebody made in the field outranks a tag. Setting the place
also gives the sightings that device already made a position (decision D258), so this can write a
good many rows; `--dry-run` says how many devices it would touch first.

    docker compose cp scripts/place_devices_from_tags.py decoder:/tmp/p.py
    docker compose exec decoder /app/.venv/bin/python /tmp/p.py --project PWN --dry-run
    docker compose exec decoder /app/.venv/bin/python /tmp/p.py --project PWN --tag scanner=yes
"""

from __future__ import annotations

import argparse
import asyncio

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import text

from shared.database import session_scope
from shared.domain.static_place import place_past_sightings, show_static_place
from shared.enums import LocationSource
from shared.models import Device
from shared.timeutil import utc_now

#: Where a ChirpStack uplink keeps the tags a person put on the device.
TAGS = "payload->'deviceInfo'->'tags'"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="Only devices assigned to this project today")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Only devices whose tags carry this key=value, e.g. scanner=yes; repeatable",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Also replace a place already set. Off by default: a place somebody measured in "
        "the field outranks a tag",
    )
    parser.add_argument("--dry-run", action="store_true", help="Say what it would do and stop")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    conditions = [f"{TAGS}->>'latitude' IS NOT NULL", f"{TAGS}->>'longitude' IS NOT NULL"]
    params: dict[str, object] = {}
    for index, pair in enumerate(args.tag):
        key, _, value = pair.partition("=")
        conditions.append(f"{TAGS}->>:tag_key_{index} = :tag_value_{index}")
        params[f"tag_key_{index}"] = key
        params[f"tag_value_{index}"] = value
    project_join = ""
    if args.project:
        project_join = (
            "JOIN device_project_assignments a ON a.device_id = se.device_id "
            "AND upper_inf(a.validity) "
            "JOIN projects p ON p.id = a.project_id AND p.name = :project"
        )
        params["project"] = args.project

    statement = text(
        f"""
        SELECT DISTINCT ON (se.device_id)
               se.device_id,
               ({TAGS}->>'latitude')::float8 AS latitude,
               ({TAGS}->>'longitude')::float8 AS longitude
        FROM source_events se
        {project_join}
        WHERE se.device_id IS NOT NULL AND {" AND ".join(conditions)}
        ORDER BY se.device_id, se.ingested_at DESC
        """
    )
    async with session_scope() as session:
        rows = (await session.execute(statement, params)).all()
    print(f"{len(rows)} devices carry a place in their tags")
    if not rows:
        return

    written = skipped = placed_sightings = 0
    for device_id, latitude, longitude in rows:
        async with session_scope() as session:
            device = await session.get(Device, device_id)
            if device is None:
                continue
            if device.static_geom is not None and not args.overwrite:
                skipped += 1
                continue
            if args.dry_run:
                print(f"  would place {device.name} at {latitude}, {longitude}")
                written += 1
                continue
            now = utc_now()
            device.static_geom = from_shape(Point(longitude, latitude), srid=4326)
            device.static_position_at = now
            device.location_source = LocationSource.STATIC
            await session.flush()
            await show_static_place(session, device, now)
            made = await place_past_sightings(session, device)
            await session.commit()
            placed_sightings += made
            written += 1
            print(f"  {device.name} at {latitude}, {longitude} ({made} sightings placed)")
    verb = "would place" if args.dry_run else "placed"
    print(
        f"{verb} {written}, left {skipped} that already had a place, {placed_sightings} sightings"
    )


asyncio.run(main())
