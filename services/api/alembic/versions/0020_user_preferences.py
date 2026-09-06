"""Per-user interface preferences (phase 15): the map's layer choices per project and, later,
the detail level (decision D105). The frontend owns the keys.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="What the person chose in the interface (map layers per project, detail "
            "level); the frontend owns the keys",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
