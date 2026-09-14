"""Analysis runs and their result geometries (docs/ANALYTICS_PHASE1_PLAN.md, section 6): the
tables of the analysis subsystem, apart from the core's, regenerable from the core data.

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels = None
depends_on = None

STATUSES = "('queued', 'running', 'completed', 'failed', 'cancelled')"
MODULES = "('movement', 'grazing')"


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("method_version", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("input_count", sa.Integer(), nullable=True),
        sa.Column("excluded_count", sa.Integer(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_analysis_runs_status"),
        sa.CheckConstraint(f"module IN {MODULES}", name="ck_analysis_runs_module"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_run_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_runs_project_created", "analysis_runs", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_analysis_runs_project_module_status",
        "analysis_runs",
        ["project_id", "module", "status"],
    )
    op.create_index(
        "ix_analysis_runs_expires",
        "analysis_runs",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_geospatial_table(
        "analysis_geometries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("level", sa.Float(), nullable=True),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column(
            "geom",
            Geometry(
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_geospatial_index(
        "idx_analysis_geometries_geom",
        "analysis_geometries",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index("ix_analysis_geometries_run_kind", "analysis_geometries", ["run_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_analysis_geometries_run_kind", table_name="analysis_geometries")
    op.drop_geospatial_index(
        "idx_analysis_geometries_geom",
        table_name="analysis_geometries",
        postgresql_using="gist",
        column_name="geom",
    )
    op.drop_geospatial_table("analysis_geometries")
    op.drop_index("ix_analysis_runs_expires", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_project_module_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_project_created", table_name="analysis_runs")
    op.drop_table("analysis_runs")
