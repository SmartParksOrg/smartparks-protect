"""PDF reports of analysis runs (decision D211): where the report stands and where its file is.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "report_status",
            sa.String(length=16),
            nullable=True,
            comment="queued, running, ready or failed; null when no report was asked for",
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "report_key",
            sa.String(length=512),
            nullable=True,
            comment="The PDF in the exports bucket",
        ),
    )
    op.add_column("analysis_runs", sa.Column("report_error", sa.Text(), nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("report_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "report_at")
    op.drop_column("analysis_runs", "report_error")
    op.drop_column("analysis_runs", "report_key")
    op.drop_column("analysis_runs", "report_status")
