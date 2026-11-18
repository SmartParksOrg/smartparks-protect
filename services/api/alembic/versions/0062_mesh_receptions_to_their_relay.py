"""A Gateway Mesh relay's receptions belong to the relay (decision D398, Tim, 2026-11-18:
BPC's coverage showed a border gateway hearing what its relays heard).

ChirpStack names the border gateway as `gatewayId` of a relayed uplink and the relay that heard
the device in `metadata.relay_id`, so every such reception was stored under the border (3944 on
dev since 2026-09-16). The adapter gives them to the relay now; this moves the stored ones:
the gateway id becomes the relay id, `mesh` in the attributes keeps the border and the hop
count, the border's `location` goes, the rows of one relay's uplink that came through several
borders become one, and a relay the platform's list never named gets its registry row.

The table is compressed after 90 days with the gateway as the segment, so every statement names
one gateway and one week and joins nothing, and the cap on decompressed tuples is lifted for
this transaction.

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels = None
depends_on = None

WINDOW = timedelta(days=7)

BORDERS = sa.text(
    """
    SELECT DISTINCT g.external_id
    FROM gateways g JOIN data_sources d ON d.id = g.data_source_id
    WHERE d.adapter_key = 'chirpstack' AND coalesce(g.attributes->>'kind', '') <> 'relay'
    """
)
RELAYS = sa.text("SELECT DISTINCT external_id FROM gateways WHERE attributes->>'kind' = 'relay'")
SPAN = sa.text("SELECT min(time), max(time) FROM gateway_receptions WHERE gateway_id = :gateway")

MOVE = sa.text(
    """
    UPDATE gateway_receptions
    SET gateway_id = lower(attributes->'metadata'->>'relay_id'),
        attributes = (attributes - 'location') || jsonb_build_object(
            'mesh',
            jsonb_build_object(
                'border_gateway_ids', jsonb_build_array(gateway_id),
                'hop_count',
                CASE WHEN attributes->'metadata'->>'hop_count' ~ '^[0-9]+$'
                     THEN (attributes->'metadata'->>'hop_count')::int END
            )
        )
    WHERE gateway_id = :gateway AND time >= :start AND time < :end
      AND coalesce(attributes->'metadata'->>'relay_id', '') <> ''
      AND NOT attributes ? 'mesh'
    RETURNING id, time, data_source_id, source_event_id, gateway_id AS relay,
              (attributes->'mesh'->>'hop_count')::int AS hops
    """
)
MERGE = sa.text(
    """
    UPDATE gateway_receptions
    SET attributes = attributes || jsonb_build_object('mesh', CAST(:mesh AS jsonb))
    WHERE gateway_id = :relay AND time = :time AND id = :id
    """
)
DROP = sa.text(
    "DELETE FROM gateway_receptions WHERE gateway_id = :relay AND time = :time AND id = ANY(:ids)"
)
REGISTER = sa.text(
    """
    INSERT INTO gateways (data_source_id, external_id, status, first_seen_at, last_seen_at,
                          attributes)
    SELECT CAST(:source AS uuid), CAST(:relay AS varchar), 'unknown',
           CAST(:first AS timestamptz), CAST(:last AS timestamptz), '{"kind": "relay"}'::jsonb
    WHERE NOT EXISTS (SELECT 1 FROM gateways WHERE external_id = CAST(:relay AS varchar))
    """
)
BACK = sa.text(
    """
    UPDATE gateway_receptions
    SET gateway_id = attributes->'mesh'->'border_gateway_ids'->>0,
        attributes = attributes - 'mesh'
    WHERE gateway_id = :gateway AND time >= :start AND time < :end
      AND coalesce(attributes->'mesh'->'border_gateway_ids'->>0, '') <> ''
    """
)


def _weeks(connection: sa.Connection, gateway: str) -> Iterator[tuple[datetime, datetime]]:
    first, last = connection.execute(SPAN, {"gateway": gateway}).one()
    while first is not None and first <= last:
        yield first, first + WINDOW
        first += WINDOW


def recredit(connection: sa.Connection) -> int:
    """Moves the relayed receptions to their relays; returns how many rows it moved."""
    connection.execute(
        sa.text("SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
    )
    moved: dict[tuple[Any, Any, str], list[dict[str, Any]]] = {}
    count = 0
    for gateway in connection.scalars(BORDERS).all():
        for start, end in _weeks(connection, gateway):
            rows = connection.execute(MOVE, {"gateway": gateway, "start": start, "end": end})
            for row in rows.mappings():
                count += 1
                # a reception without a source event has nothing to be merged on
                key = (row["data_source_id"], row["source_event_id"] or row["id"], row["relay"])
                moved.setdefault(key, []).append({**row, "border": gateway})

    seen: dict[tuple[Any, str], tuple[datetime, datetime]] = {}
    for (source, _event, relay), rows in moved.items():
        times = [row["time"] for row in rows]
        first, last = seen.get((source, relay), (times[0], times[0]))
        seen[(source, relay)] = (min(first, *times), max(last, *times))
        if len(rows) == 1:
            continue
        rows.sort(key=lambda row: row["id"])
        keep = rows[0]
        hops = [row["hops"] for row in rows if row["hops"] is not None]
        mesh = {
            "border_gateway_ids": sorted({row["border"] for row in rows}),
            "hop_count": min(hops) if hops else None,
        }
        connection.execute(
            MERGE,
            {"relay": relay, "time": keep["time"], "id": keep["id"], "mesh": json.dumps(mesh)},
        )
        for time in {row["time"] for row in rows[1:]}:
            ids = [row["id"] for row in rows[1:] if row["time"] == time]
            connection.execute(DROP, {"relay": relay, "time": time, "ids": ids})
    for (source, relay), (first, last) in seen.items():
        connection.execute(
            REGISTER, {"source": source, "relay": relay, "first": first, "last": last}
        )
    return count


def upgrade() -> None:
    recredit(op.get_bind())


def downgrade() -> None:
    """The receptions go back to the first border they came through. Rows merged from several
    borders stay one."""
    connection = op.get_bind()
    connection.execute(
        sa.text("SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
    )
    for gateway in connection.scalars(RELAYS).all():
        for start, end in _weeks(connection, gateway):
            connection.execute(BACK, {"gateway": gateway, "start": start, "end": end})
