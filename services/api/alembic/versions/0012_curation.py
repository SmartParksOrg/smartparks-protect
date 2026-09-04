"""Data curation: the effective value overlay on positions and measurements, corrections,
bulk jobs, stale outbound deliveries (architecture 28, phase 12, decisions D80 to D82).

Revision: 0012
Revises: 0011
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "('pending', 'active', 'reverted', 'superseded')"
JOB_STATUSES = "('previewed', 'pending', 'applying', 'applied', 'reverting', 'reverted', 'failed')"
TARGETS = "('position', 'measurement')"
FIELDS = "('time', 'coordinates', 'value', 'valid')"
REASONS = (
    "('DEVICE_FIRMWARE_BUG', 'DEVICE_CLOCK_ERROR', 'TIMEZONE_ERROR', 'GPS_OUTLIER', "
    "'CALIBRATION_ERROR', 'WRONG_ENTITY_ASSIGNMENT', 'WRONG_PROJECT_ASSIGNMENT', "
    "'CLASSIFICATION_CORRECTION', 'MANUAL_QC', 'OTHER')"
)


def _overlay(table: str, value_column: sa.Column | None) -> None:
    """Nullable overlay columns: adding them touches no existing row (decision D80). The
    partial index only holds curated rows, so it costs nothing on an uncurated table."""
    op.add_column(
        table,
        sa.Column(
            "curated_time",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Effective time when curated; null means `time`",
        ),
    )
    if value_column is not None:
        op.add_column(table, value_column)
    op.add_column(
        table, sa.Column("valid", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.add_column(
        table,
        sa.Column(
            "curated_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        table,
        sa.Column(
            "curation_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
            comment="Bumped on every correction",
        ),
    )
    op.create_index(
        f"ix_{table}_curated_time",
        table,
        ["curated_time"],
        postgresql_where=sa.text("curated_time IS NOT NULL"),
    )


def upgrade() -> None:
    _overlay(
        "positions",
        sa.Column(
            "curated_geom",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
            comment="Effective point when curated; null means `geom`",
        ),
    )
    _overlay(
        "measurements",
        sa.Column(
            "curated_value_num",
            sa.Float(),
            nullable=True,
            comment="Effective numeric value when curated; null means `value_num`",
        ),
    )
    op.add_column(
        "integration_deliveries",
        sa.Column(
            "stale_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set when a curation changed the object after it was sent (architecture 28.10)",
        ),
    )
    op.add_column(
        "integration_deliveries", sa.Column("stale_reason", sa.String(length=128), nullable=True)
    )

    op.create_table(
        "curation_jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="previewed", nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column(
            "device_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "entity_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metric_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("time_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transformation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("replay_rules", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "preview",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "impact",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("affected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("applied_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reverted_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(f"status IN {JOB_STATUSES}", name="ck_curation_jobs_status"),
        sa.CheckConstraint(f"target_type IN {TARGETS}", name="ck_curation_jobs_target"),
        sa.CheckConstraint(f"reason_code IN {REASONS}", name="ck_curation_jobs_reason"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applied_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reverted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_curation_jobs_project_created", "curation_jobs", ["project_id", "created_at"]
    )

    op.create_table(
        "data_corrections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            nullable=True,
            comment="Project of the record when the correction was made",
        ),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "target_time",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="The record's original time (its key)",
        ),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("metric_key", sa.String(length=64), nullable=True),
        sa.Column("field", sa.String(length=16), nullable=False),
        sa.Column(
            "original_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="The effective value before this correction",
        ),
        sa.Column("corrected_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "impact",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Attribution before and after, deliveries flagged",
        ),
        sa.Column("curation_job_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revert_comment", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_data_corrections_status"),
        sa.CheckConstraint(f"target_type IN {TARGETS}", name="ck_data_corrections_target"),
        sa.CheckConstraint(f"field IN {FIELDS}", name="ck_data_corrections_field"),
        sa.CheckConstraint(f"reason_code IN {REASONS}", name="ck_data_corrections_reason"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["curation_job_id"], ["curation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["data_corrections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reverted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_corrections_project_status_created",
        "data_corrections",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_data_corrections_target",
        "data_corrections",
        ["target_type", "target_id", "target_time"],
    )
    op.create_index("ix_data_corrections_job", "data_corrections", ["curation_job_id"])


def downgrade() -> None:
    op.drop_index("ix_data_corrections_job", table_name="data_corrections")
    op.drop_index("ix_data_corrections_target", table_name="data_corrections")
    op.drop_index("ix_data_corrections_project_status_created", table_name="data_corrections")
    op.drop_table("data_corrections")
    op.drop_index("ix_curation_jobs_project_created", table_name="curation_jobs")
    op.drop_table("curation_jobs")
    op.drop_column("integration_deliveries", "stale_reason")
    op.drop_column("integration_deliveries", "stale_at")
    for table, value_column in (
        ("measurements", "curated_value_num"),
        ("positions", "curated_geom"),
    ):
        op.drop_index(f"ix_{table}_curated_time", table_name=table)
        op.drop_column(table, "curation_version")
        op.drop_column(table, "curated_fields")
        op.drop_column(table, "valid")
        op.drop_column(table, value_column)
        op.drop_column(table, "curated_time")
