"""Platform expansion (phase 13): server settings, pending MCP actions, project icons,
dashboards, and the Movebank export datasets.

Revision: 0013
Revises: 0012
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATASETS_OLD = "('source_events', 'positions', 'measurements', 'aggregates')"
DATASETS_NEW = (
    "('source_events', 'positions', 'measurements', 'aggregates', 'movebank_events', "
    "'movebank_reference')"
)


def upgrade() -> None:
    op.create_table(
        "server_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "mcp_pending_actions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=256), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_pending_actions_user_expires", "mcp_pending_actions", ["user_id", "expires_at"]
    )
    op.create_table(
        "project_icons",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("svg", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_project_icons_project_key"),
    )
    op.create_index("ix_project_icons_project_id", "project_icons", ["project_id"])
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "tiles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Ordered tiles: kind, size, options",
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_dashboards_project_name"),
    )
    op.create_index("ix_dashboards_project_id", "dashboards", ["project_id"])
    op.drop_constraint("ck_export_jobs_dataset", "export_jobs", type_="check")
    op.create_check_constraint(
        "ck_export_jobs_dataset", "export_jobs", f"dataset IN {DATASETS_NEW}"
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM export_jobs WHERE dataset IN ('movebank_events', 'movebank_reference')"
        )
    )
    op.drop_constraint("ck_export_jobs_dataset", "export_jobs", type_="check")
    op.create_check_constraint(
        "ck_export_jobs_dataset", "export_jobs", f"dataset IN {DATASETS_OLD}"
    )
    op.drop_index("ix_dashboards_project_id", table_name="dashboards")
    op.drop_table("dashboards")
    op.drop_index("ix_project_icons_project_id", table_name="project_icons")
    op.drop_table("project_icons")
    op.drop_index("ix_mcp_pending_actions_user_expires", table_name="mcp_pending_actions")
    op.drop_table("mcp_pending_actions")
    op.drop_table("server_settings")
