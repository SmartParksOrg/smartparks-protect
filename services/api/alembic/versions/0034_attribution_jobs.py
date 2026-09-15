"""Attribution jobs (decision D206): the rewrite of a device's records after an assignment
change runs in the background with its progress on this row.

Revision ID: 0034
Revises: 0033
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels = None
depends_on = None

STATUSES = "('queued', 'running', 'complete', 'failed')"


def upgrade() -> None:
    op.create_table(
        "attribution_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            nullable=True,
            comment="The project the change was made in, for the audit and the pages",
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "reason",
            sa.String(length=64),
            nullable=False,
            comment="The audit action that queued it (project_assignment.start_moved, ...)",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("time_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "records_total",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Positions and measurements in the window when the job was queued",
        ),
        sa.Column(
            "records_done",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Records rewritten so far; moves with every window",
        ),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Rows rewritten per table",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_attribution_jobs_status"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attribution_jobs_device_created", "attribution_jobs", ["device_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_attribution_jobs_device_created", table_name="attribution_jobs")
    op.drop_table("attribution_jobs")
