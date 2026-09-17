"""The cache of environmental layer samples per geometry and week (decision D245).

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_samples",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("layer", sa.String(length=64), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "week",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="The Monday the week starts on, UTC",
        ),
        sa.Column("value", sa.Float(), nullable=True, comment="None: no valid observation"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "layer", "geometry_hash", "week", name="uq_environment_samples_key"
        ),
    )
    op.create_index(
        "ix_environment_samples_geometry_hash", "environment_samples", ["geometry_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_environment_samples_geometry_hash", table_name="environment_samples")
    op.drop_table("environment_samples")
