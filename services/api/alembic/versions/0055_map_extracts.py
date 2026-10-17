"""The offline map of a project's area for Protect Field (phase 43 P3; Field's decision D4):
one PMTiles extract per project, cut from a Protomaps planet build by the export worker and kept
in MinIO; the row holds the box, the zoom, the build, the file's key, size and digest, or the
reason the last attempt failed.

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "map_extracts",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("west", sa.Float(), nullable=False),
        sa.Column("south", sa.Float(), nullable=False),
        sa.Column("east", sa.Float(), nullable=False),
        sa.Column("north", sa.Float(), nullable=False),
        sa.Column("max_zoom", sa.SmallInteger(), nullable=False),
        sa.Column(
            "source", sa.Text(), nullable=True, comment="The planet build the extract was cut from"
        ),
        sa.Column("build", sa.String(32), nullable=True, comment="The build's date, YYYYMMDD"),
        sa.Column("object_key", sa.String(512), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'failed')", name="ck_map_extracts_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("map_extracts")
