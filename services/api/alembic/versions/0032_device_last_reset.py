"""The time of the last reboot a device's uptime showed, on its current state.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_current_state",
        sa.Column(
            "last_reset_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="The last status message whose uptime was lower than the one before it",
        ),
    )


def downgrade() -> None:
    op.drop_column("device_current_state", "last_reset_at")
