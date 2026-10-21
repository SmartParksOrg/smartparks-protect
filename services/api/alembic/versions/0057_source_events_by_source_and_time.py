"""An index on source events by data source and time (decision D347). "When did this source
last deliver" is asked per source by the System health page and the ingestion area; without
an index that leads with the source, Postgres walks the time index backwards through every
newer event of every other source until it meets one of the source asked for, which is the
whole table for a source that has been quiet for a while (half a second per source on the dev
server, times nineteen sources, and the page did not load during a deploy).

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels = None
depends_on = None

INDEX = "ix_source_events_source_time"


def upgrade() -> None:
    op.create_index(INDEX, "source_events", ["data_source_id", "ingested_at"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="source_events")
