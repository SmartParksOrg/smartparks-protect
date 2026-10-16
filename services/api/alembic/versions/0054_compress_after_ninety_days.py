"""Compress after 90 days instead of 7 (decision D328): a card or a raw log carries weeks of
history, and every row that lands in a chunk already compressed costs TimescaleDB a
decompression first; on the dev server the month of a demo card decoded at a frame every two
to three seconds for that reason (2026-10-16). The chunks of the last 90 days that are
compressed today are decompressed here, so the new window holds from this migration on; the
policy compresses them again once they are older than 90 days. Also `pg_stat_statements`,
when the server preloads it (the compose file does), so a slow query can be named.

Revision ID: 0054
Revises: 0053
"""

from __future__ import annotations

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels = None
depends_on = None

TABLES = (
    "source_events",
    "positions",
    "measurements",
    "gateway_receptions",
    "device_state_history",
    "device_contacts",
)


def _set_window(days: int) -> None:
    for table in TABLES:
        op.execute(f"CALL remove_columnstore_policy('{table}', if_exists => true)")
        op.execute(f"CALL add_columnstore_policy('{table}', after => INTERVAL '{days} days')")


def upgrade() -> None:
    _set_window(90)
    # the recent chunks compressed under the old window: back to row storage, so an import of
    # the last three months writes at full speed from now on (a big server takes a while here)
    for table in TABLES:
        op.execute(
            f"""
            SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, true)
            FROM timescaledb_information.chunks
            WHERE hypertable_name = '{table}' AND is_compressed
              AND range_end > now() - INTERVAL '90 days'
            """
        )
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_stat_statements not available: %', SQLERRM;
        END $$;
        """
    )


def downgrade() -> None:
    _set_window(7)
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
