"""The time of the last movement a device's accelerometer showed, on its current state.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_current_state",
        sa.Column(
            "last_movement_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="The last status message whose accelerometer sample changed above the threshold",
        ),
    )


def downgrade() -> None:
    op.drop_column("device_current_state", "last_movement_at")
