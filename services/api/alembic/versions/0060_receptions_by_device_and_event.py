"""Gateway receptions by device and source event (decision D371, Tim, 2026-11-06: the coverage
layer of Okonjima took 47 s over 30 days, 94 s with the lines to the gateways).

The coverage read joins every heard position to the receptions of its uplink on device and
source event id; the index on device and time made Postgres walk every reception of the device
in the window per position, 1.7 ms per chunk, 8,600 positions, five chunks. This index answers
the join with one lookup per position (24 s to 4 s for the shares alone on dev, measured in a
rolled-back transaction).

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_gateway_receptions_device_event",
        "gateway_receptions",
        ["device_id", "source_event_id", "time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_gateway_receptions_device_event", table_name="gateway_receptions")
