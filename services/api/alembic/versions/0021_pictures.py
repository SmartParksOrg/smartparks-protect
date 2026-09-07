"""Profile pictures of entities and devices (decision D110): the object key in the pictures
bucket and when it was set, so a browser cache refreshes after a change.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("entities", "devices"):
        op.add_column(
            table,
            sa.Column(
                "picture_key",
                sa.String(length=200),
                nullable=True,
                comment="Object key of the profile picture in the pictures bucket (D110)",
            ),
        )
        op.add_column(
            table, sa.Column("picture_updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    for table in ("entities", "devices"):
        op.drop_column(table, "picture_updated_at")
        op.drop_column(table, "picture_key")
