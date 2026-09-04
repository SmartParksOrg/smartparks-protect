"""Backup and recovery runs (architecture 28, phase 10).

Revision: 0010
Revises: 0009
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=True, comment="pgBackRest backup label"),
        sa.Column("host", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('database_full', 'database_incr', 'object_mirror', 'integrity_check', "
            "'restore_test')",
            name="ck_backup_runs_kind",
        ),
        sa.CheckConstraint("status IN ('ok', 'failed', 'skipped')", name="ck_backup_runs_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backup_runs_kind_started", "backup_runs", ["kind", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_kind_started", table_name="backup_runs")
    op.drop_table("backup_runs")
