"""The step an analysis run is busy with (decision D249), so the progress bar says what is
happening and not only how far it is.

Revision ID: 0040
Revises: 0039
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "progress_step",
            sa.String(length=120),
            nullable=True,
            comment="What the run is working on now, for the progress bar (D249)",
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "progress_step")
