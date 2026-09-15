"""How far the decoder is with a log file: the frames done so far.

Revision ID: 0033
Revises: 0032
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_log_files",
        sa.Column(
            "frames_done",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Frames decoded so far; equals frames_total once the file is complete",
        ),
    )
    # Files decoded before this revision are done.
    op.execute("UPDATE device_log_files SET frames_done = frames_total WHERE status = 'complete'")


def downgrade() -> None:
    op.drop_column("device_log_files", "frames_done")
