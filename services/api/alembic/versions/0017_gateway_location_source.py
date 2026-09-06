"""Gateway locations keep where they came from and when (phase 15): a platform's gateway
list, a reception's coordinates, or an administrator, whose position platform updates never
overwrite.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateways",
        sa.Column(
            "location_source",
            sa.String(length=16),
            nullable=True,
            comment="platform (gateway list or event), reception (coordinates on an uplink) "
            "or admin (set by hand, kept over platform updates)",
        ),
    )
    op.add_column(
        "gateways",
        sa.Column(
            "location_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the location was last set",
        ),
    )


def downgrade() -> None:
    op.drop_column("gateways", "location_at")
    op.drop_column("gateways", "location_source")
