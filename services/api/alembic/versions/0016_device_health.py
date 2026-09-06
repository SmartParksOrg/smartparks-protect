"""Device health: the latest value per metric and the time of the last state on the current
state row, so lists, the map and the device page show health without touching the hypertables
(phase 15, decision D104).

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_current_state",
        sa.Column(
            "latest_measurements",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="metric key to {value, time} of the newest measurement per metric",
        ),
    )
    op.add_column(
        "device_current_state",
        sa.Column(
            "latest_state_time",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Canonical time of the newest state record (a status message)",
        ),
    )


def downgrade() -> None:
    op.drop_column("device_current_state", "latest_state_time")
    op.drop_column("device_current_state", "latest_measurements")
