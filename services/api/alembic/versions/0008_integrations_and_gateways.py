"""Integrations, integration deliveries, gateways and polling cursors (architecture 18 and 20,
phase 8, decisions D60, D61 and D66).

Revision: 0008
Revises: 0007
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(default: str = "'{}'::jsonb") -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "config",
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Non-secret settings",
        ),
        sa.Column(
            "credentials_encrypted",
            sa.LargeBinary(),
            nullable=True,
            comment="Fernet-encrypted JSON, never returned by the API",
        ),
        sa.Column(
            "object_types",
            _jsonb(),
            server_default=sa.text('\'["position", "event"]\'::jsonb'),
            nullable=False,
            comment="position, event, measurement",
        ),
        sa.Column(
            "entity_ids",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Empty means all",
        ),
        sa.Column(
            "device_ids",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Empty means all",
        ),
        sa.Column(
            "event_types",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Empty means all",
        ),
        sa.Column(
            "metric_keys",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Empty means all",
        ),
        sa.Column("min_severity", sa.String(length=16), server_default="info", nullable=False),
        sa.Column(
            "max_object_age_seconds",
            sa.Integer(),
            server_default=sa.text("86400"),
            nullable=False,
            comment="Live objects older than this are not forwarded; backfill ignores it",
        ),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "backfill",
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Progress of the last backfill: status, from, to, queued, started_at, finished_at",
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "min_severity IN ('info', 'warning', 'critical')", name="ck_integrations_min_severity"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_integrations_project_name"),
    )
    op.create_index("ix_integrations_project_id", "integrations", ["project_id"], unique=False)
    op.create_index(
        "ix_integrations_connector_key", "integrations", ["connector_key"], unique=False
    )

    op.create_table(
        "integration_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.String(length=16), nullable=False),
        sa.Column(
            "object_id",
            sa.String(length=64),
            nullable=False,
            comment="Position or measurement id, or event uuid",
        ),
        sa.Column("object_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("object_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(length=16), server_default="live", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Null once the delivery is final",
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "external_id",
            sa.String(length=256),
            nullable=True,
            comment="The target's id for the sent object, when it returns one",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "request", _jsonb(), nullable=True, comment="The rendered payload of the last attempt"
        ),
        sa.Column("response", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'skipped')",
            name="ck_integration_deliveries_status",
        ),
        sa.CheckConstraint(
            "object_type IN ('position', 'event', 'measurement')",
            name="ck_integration_deliveries_object_type",
        ),
        sa.CheckConstraint(
            "origin IN ('live', 'backfill', 'retry', 'test')",
            name="ck_integration_deliveries_origin",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "object_type",
            "object_id",
            "object_version",
            name="uq_integration_deliveries_object",
        ),
    )
    op.create_index(
        "ix_integration_deliveries_due",
        "integration_deliveries",
        ["status", "next_attempt_at", "integration_id"],
        unique=False,
    )
    op.create_index(
        "ix_integration_deliveries_integration_created",
        "integration_deliveries",
        ["integration_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_integration_deliveries_project_created",
        "integration_deliveries",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_geospatial_table(
        "gateways",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="unknown", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last reception or gateway event",
        ),
        sa.Column("last_stats_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "stats",
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Latest counters the platform reports: rx_packets, tx_packets, tx_errors",
        ),
        sa.Column(
            "attributes",
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Provider diagnostics, never part of the canonical schema",
        ),
        sa.Column(
            "name_override",
            sa.String(length=200),
            nullable=True,
            comment="Set by an administrator, wins over the platform name",
        ),
        *_timestamps(),
        sa.CheckConstraint("status IN ('online', 'offline', 'unknown')", name="ck_gateways_status"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_source_id", "external_id", name="uq_gateways_source_external_id"),
    )
    op.create_index("ix_gateways_data_source_id", "gateways", ["data_source_id"], unique=False)
    op.create_geospatial_index(
        "idx_gateways_geom",
        "gateways",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )

    op.create_table(
        "data_source_cursors",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("state", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("data_source_id"),
    )


def downgrade() -> None:
    op.drop_table("data_source_cursors")
    op.drop_geospatial_index(
        "idx_gateways_geom", table_name="gateways", postgresql_using="gist", column_name="geom"
    )
    op.drop_index("ix_gateways_data_source_id", table_name="gateways")
    op.drop_geospatial_table("gateways")
    op.drop_index("ix_integration_deliveries_project_created", table_name="integration_deliveries")
    op.drop_index(
        "ix_integration_deliveries_integration_created", table_name="integration_deliveries"
    )
    op.drop_index("ix_integration_deliveries_due", table_name="integration_deliveries")
    op.drop_table("integration_deliveries")
    op.drop_index("ix_integrations_connector_key", table_name="integrations")
    op.drop_index("ix_integrations_project_id", table_name="integrations")
    op.drop_table("integrations")
