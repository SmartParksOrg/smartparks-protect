"""A run is private to the person who ran it unless shared with the project.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Visible to the project's members, not only to the person who ran it",
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "shared")
