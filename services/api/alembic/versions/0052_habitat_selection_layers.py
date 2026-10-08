"""The habitat selection module (phase 41, decisions D313 to D318): the run row's module check
admits its key, a project's uploaded raster layers, and the cache of the rasters a provider
answered.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels = None
depends_on = None

BEFORE = (
    "('movement', 'grazing', 'device_performance', 'contact_tracing', 'cardiac', 'vehicle_use')"
)
AFTER = (
    "('movement', 'grazing', 'device_performance', 'contact_tracing', 'cardiac', 'vehicle_use', "
    "'habitat_selection')"
)


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {AFTER}")
    op.create_table(
        "project_layers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "name", sa.String(64), nullable=False, comment="The band name the run reads it under"
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column(
            "kind",
            sa.String(16),
            nullable=False,
            comment="continuous or categorical (decision D317)",
        ),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("epsg", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "pixel_m",
            sa.Float(),
            nullable=False,
            comment="The pixel size in metres, from the header",
        ),
        sa.Column(
            "extent",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="west, south, east, north in the layer's own CRS",
        ),
        sa.Column("nodata", sa.Float(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('continuous', 'categorical')", name="ck_project_layers_kind"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_layers_project_name"),
    )
    op.create_index("ix_project_layers_project_id", "project_layers", ["project_id"])
    op.create_table(
        "environment_rasters",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("layer", sa.String(64), nullable=False),
        sa.Column("area_hash", sa.String(64), nullable=False),
        sa.Column("epsg", sa.Integer(), nullable=False),
        sa.Column("resolution_m", sa.Float(), nullable=False),
        sa.Column(
            "period",
            sa.String(32),
            nullable=False,
            comment="`from/to` dates, or `static` for a layer without time",
        ),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "layer",
            "area_hash",
            "epsg",
            "resolution_m",
            "period",
            name="uq_environment_rasters_key",
        ),
    )
    op.create_index("ix_environment_rasters_area_hash", "environment_rasters", ["area_hash"])


def downgrade() -> None:
    # The files in the analysis layers bucket stay; nothing refers to them afterwards.
    op.drop_index("ix_environment_rasters_area_hash", table_name="environment_rasters")
    op.drop_table("environment_rasters")
    op.drop_index("ix_project_layers_project_id", table_name="project_layers")
    op.drop_table("project_layers")
    op.execute("DELETE FROM analysis_runs WHERE module = 'habitat_selection'")
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {BEFORE}")
