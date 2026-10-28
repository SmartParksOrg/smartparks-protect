"""Movement from the fixes, and the offline map cut from several regions (decisions D363 and
D365, Tim, 2026-10-28: SP051307 drove 70 km in Namibia and its Movement line read "still for
20 h", since the line read only the hourly accelerometer sample; and Protect Go's map held the
Netherlands, where the offload station stands, and nothing of Namibia, where the tracker is).

`device_current_state.last_fix_movement_at` is the newest valid fix that lay beyond the jitter
bar from the valid fix before it; the health line shows the newer of it and the accelerometer's
`last_movement_at`. `map_extracts.regions` holds the boxes the map was cut for, one per cluster
of the project's places and current positions, each padded by the margin; the four bbox
columns keep their envelope. A row from before this migration has no regions and is read as
its one box.

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_current_state",
        sa.Column(
            "last_fix_movement_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="The newest valid fix beyond the jitter bar from the valid fix before it (D363)",
        ),
    )
    op.add_column(
        "map_extracts",
        sa.Column("regions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("map_extracts", "regions")
    op.drop_column("device_current_state", "last_fix_movement_at")
