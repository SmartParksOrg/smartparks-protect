"""Foundation: access control, domain, time series, events, traces.

Extensions, every table, hypertables with compression and retention policies. Hand edited after
autogenerate: extensions and TimescaleDB statements are explicit steps.

Revision: 0001
Revises:
Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HYPERTABLES = (
    ("source_events", "ingested_at", "7 days"),
    ("positions", "time", "7 days"),
    ("measurements", "time", "7 days"),
    ("gateway_receptions", "time", "7 days"),
    ("device_state_history", "time", "30 days"),
)
COMPRESSION = (
    ("source_events", "ingested_at", "data_source_id"),
    ("positions", "time", "device_id"),
    ("measurements", "time", "device_id"),
    ("gateway_receptions", "time", "gateway_id"),
    ("device_state_history", "time", "device_id"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")  # uuid equality in GiST exclusions
    op.create_table(
        "application_errors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("user_actionable", sa.Boolean(), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "technical_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "error_code IN ('CONNECTIVITY_AUTH_FAILED', 'CONNECTIVITY_UNAVAILABLE', 'DEVICE_NOT_FOUND', 'DEVICE_IDENTITY_AMBIGUOUS', 'PROJECT_NOT_ASSIGNED', 'PAYLOAD_DECODE_FAILED', 'TIMESTAMP_INVALID', 'CANONICALIZATION_FAILED', 'SCHEMA_VERSION_UNSUPPORTED', 'RULE_EVALUATION_FAILED', 'ACTION_FAILED', 'INTEGRATION_DELIVERY_FAILED', 'COMMAND_REJECTED', 'COMMAND_EXPIRED', 'FILE_PARSE_FAILED', 'EXPORT_FAILED', 'INTERNAL_ERROR')",
            name="ck_application_errors_code",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'error', 'critical')", name="ck_application_errors_severity"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_application_errors_error_code"), "application_errors", ["error_code"], unique=False
    )
    op.create_table(
        "data_sources",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("adapter_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
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
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Architecture 8.2",
        ),
        sa.Column(
            "link_templates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="OPEN_DEVICE and so on",
        ),
        sa.Column(
            "retention_days", sa.Integer(), nullable=True, comment="Raw event retention override"
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        op.f("ix_data_sources_adapter_key"), "data_sources", ["adapter_key"], unique=False
    )
    op.create_table(
        "device_types",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("driver_key", sa.String(length=64), nullable=False),
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column(
            "icon_key", sa.String(length=128), server_default="device.sensor", nullable=False
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "default_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        op.f("ix_device_types_driver_key"), "device_types", ["driver_key"], unique=False
    )
    op.create_table(
        "entity_types",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("group_key", sa.String(length=32), nullable=False),
        sa.Column("icon_key", sa.String(length=128), nullable=False),
        sa.Column(
            "attribute_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="JSON schema",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "group_key IN ('tracked', 'infrastructure', 'environmental', 'equipment', 'site')",
            name="ck_entity_types_group",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "metrics",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "unit", sa.String(length=32), nullable=True, comment="Canonical unit, null if none"
        ),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "value_type IN ('numeric', 'boolean', 'text', 'json')", name="ck_metrics_value_type"
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(op.f("ix_metrics_category"), "metrics", ["category"], unique=False)
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Server admin",
        ),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Tokens issued before this moment are rejected",
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "devices",
        sa.Column("device_type_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("serial_number", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="inventory", nullable=False),
        sa.Column("firmware_version", sa.String(length=64), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('active', 'inventory', 'repair', 'retired')", name="ck_devices_status"
        ),
        sa.ForeignKeyConstraint(["device_type_id"], ["device_types.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("serial_number"),
    )
    op.create_index(op.f("ix_devices_device_type_id"), "devices", ["device_type_id"], unique=False)
    op.create_table(
        "projects",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system', 'mcp')", name="ck_audit_log_actor_type"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_object", "audit_log", ["object_type", "object_id"], unique=False)
    op.create_index("ix_audit_log_project_time", "audit_log", ["project_id", "time"], unique=False)
    op.create_index(op.f("ix_audit_log_time"), "audit_log", ["time"], unique=False)
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False)
    op.create_table(
        "connectivity_state",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="unknown", nullable=False),
        sa.Column("last_uplink_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_downlink_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_join_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rssi", sa.Float(), nullable=True),
        sa.Column("last_snr", sa.Float(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('online', 'offline', 'unknown')", name="ck_connectivity_state_status"
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id", "data_source_id"),
    )
    op.create_table(
        "data_source_project_scopes",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "auto_assign",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Assign unknown devices from this source to the project automatically",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("data_source_id", "project_id"),
    )
    op.create_geospatial_table(
        "device_current_state",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_position_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "latest_position",
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
        sa.Column(
            "latest_state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("battery_voltage", sa.Float(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_table(
        "device_project_assignments",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "validity",
            postgresql.TSTZRANGE(),
            nullable=False,
            comment="[start, end), end null while current",
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("device_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_device_project_assignments_no_overlap",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_device_project_assignments_device_id"),
        "device_project_assignments",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        "ix_device_project_assignments_project",
        "device_project_assignments",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "device_state_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_index(
        "ix_device_state_history_device_time",
        "device_state_history",
        ["device_id", "time"],
        unique=False,
    )
    op.create_geospatial_table(
        "entities",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "icon_key", sa.String(length=128), nullable=True, comment="Overrides the type icon"
        ),
        sa.Column(
            "geom",
            Geometry(
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
            comment="Static location for infrastructure; tracked entities use current state",
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')", name="ck_entities_status"
        ),
        sa.ForeignKeyConstraint(["entity_type_id"], ["entity_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_entities_project_name"),
    )
    op.create_geospatial_index(
        "idx_entities_geom",
        "entities",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_entities_entity_type_id"), "entities", ["entity_type_id"], unique=False
    )
    op.create_index(op.f("ix_entities_project_id"), "entities", ["project_id"], unique=False)
    op.create_table(
        "external_identities",
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("identity_type", sa.String(length=32), server_default="dev_eui", nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("ignored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "data_source_id", "external_id", name="uq_external_identities_source_external_id"
        ),
    )
    op.create_index(
        op.f("ix_external_identities_data_source_id"),
        "external_identities",
        ["data_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_identities_device_id"), "external_identities", ["device_id"], unique=False
    )
    op.create_geospatial_table(
        "features",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("feature_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
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
        sa.Column("icon_key", sa.String(length=128), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "feature_type IN ('site', 'zone', 'geofence', 'route')", name="ck_features_type"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_features_project_name"),
    )
    op.create_geospatial_index(
        "idx_features_geom",
        "features",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(op.f("ix_features_project_id"), "features", ["project_id"], unique=False)
    op.create_table(
        "gateway_receptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gateway_id", sa.String(length=64), nullable=False),
        sa.Column("rssi", sa.Float(), nullable=True),
        sa.Column("snr", sa.Float(), nullable=True),
        sa.Column("frequency_hz", sa.BigInteger(), nullable=True),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_index(
        "ix_gateway_receptions_device_time",
        "gateway_receptions",
        ["device_id", "time"],
        unique=False,
    )
    op.create_index(
        "ix_gateway_receptions_gateway_time",
        "gateway_receptions",
        ["gateway_id", "time"],
        unique=False,
    )
    op.create_table(
        "invitations",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("server_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "role IN ('project-viewer', 'project-admin')", name="ck_invitations_role"
        ),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index(op.f("ix_invitations_email"), "invitations", ["email"], unique=False)
    op.create_index(op.f("ix_invitations_project_id"), "invitations", ["project_id"], unique=False)
    op.create_table(
        "processing_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("root_object_type", sa.String(length=64), nullable=False),
        sa.Column("root_object_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("trace_class", sa.String(length=16), server_default="routine", nullable=False),
        sa.Column("compact", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("compact_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        sa.Column("error_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "actor",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="user, client_type, client_name for commands and MCP calls",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'success', 'skipped', 'duplicate', 'retrying', 'failed', 'dead_letter')",
            name="ck_processing_traces_status",
        ),
        sa.CheckConstraint(
            "trace_class IN ('routine', 'failed', 'command', 'audit')",
            name="ck_processing_traces_class",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["error_id"], ["application_errors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_traces_device_started",
        "processing_traces",
        ["device_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_processing_traces_root",
        "processing_traces",
        ["root_object_type", "root_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_processing_traces_started", "processing_traces", ["started_at"], unique=False
    )
    op.create_index(
        "ix_processing_traces_status_started",
        "processing_traces",
        ["status", "started_at"],
        unique=False,
    )
    op.create_table(
        "project_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint(
            "role IN ('project-viewer', 'project-admin')", name="ck_project_memberships_role"
        ),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_memberships_user_project"),
    )
    op.create_index(
        op.f("ix_project_memberships_project_id"),
        "project_memberships",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_project_memberships_user_id"), "project_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "rules",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_rules_project_name"),
    )
    op.create_index(op.f("ix_rules_project_id"), "rules", ["project_id"], unique=False)
    op.create_table(
        "device_entity_assignments",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("validity", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        postgresql.ExcludeConstraint(
            (sa.column("device_id"), "="),
            (sa.column("validity"), "&&"),
            using="gist",
            name="ex_device_entity_assignments_no_overlap",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_device_entity_assignments_device_id"),
        "device_entity_assignments",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        "ix_device_entity_assignments_entity",
        "device_entity_assignments",
        ["entity_id"],
        unique=False,
    )
    op.create_geospatial_table(
        "entity_current_state",
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_position_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "latest_position",
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
        sa.Column(
            "status_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("active_alert_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    op.create_geospatial_index(
        "idx_entity_current_state_latest_position",
        "entity_current_state",
        ["latest_position"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        "ix_entity_current_state_project", "entity_current_state", ["project_id"], unique=False
    )
    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("value_text", sa.String(length=1024), nullable=True),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "num_nonnulls(value_num, value_bool, value_text, value_json) = 1",
            name="ck_measurements_one_value",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["metric_key"], ["metrics.key"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_index(
        "ix_measurements_device_metric_time",
        "measurements",
        ["device_id", "metric_key", "time"],
        unique=False,
    )
    op.create_index(
        "ix_measurements_entity_metric_time",
        "measurements",
        ["entity_id", "metric_key", "time"],
        unique=False,
    )
    op.create_index(
        "ix_measurements_project_metric_time",
        "measurements",
        ["project_id", "metric_key", "time"],
        unique=False,
    )
    op.create_index(
        "uq_measurements_canonical_key", "measurements", ["canonical_key", "time"], unique=True
    )
    op.create_geospatial_table(
        "positions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True, comment="Resolved at canonical time"),
        sa.Column("entity_id", sa.Uuid(), nullable=True, comment="Resolved at canonical time"),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_type", sa.String(length=32), server_default="gnss", nullable=False),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("speed_mps", sa.Float(), nullable=True),
        sa.Column("heading_deg", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("satellites", sa.Integer(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_geospatial_index(
        "idx_positions_geom",
        "positions",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index("ix_positions_device_time", "positions", ["device_id", "time"], unique=False)
    op.create_index("ix_positions_entity_time", "positions", ["entity_id", "time"], unique=False)
    op.create_index("ix_positions_project_time", "positions", ["project_id", "time"], unique=False)
    op.create_index(
        "uq_positions_canonical_key", "positions", ["canonical_key", "time"], unique=True
    )
    op.create_table(
        "processing_steps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_ref", sa.String(length=256), nullable=True),
        sa.Column("output_ref", sa.String(length=256), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'success', 'skipped', 'duplicate', 'retrying', 'failed', 'dead_letter')",
            name="ck_processing_steps_status",
        ),
        sa.ForeignKeyConstraint(["error_id"], ["application_errors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trace_id"], ["processing_traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_steps_trace_sequence",
        "processing_steps",
        ["trace_id", "sequence"],
        unique=True,
    )
    op.create_table(
        "rule_versions",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version", name="uq_rule_versions_rule_version"),
    )
    op.create_index(op.f("ix_rule_versions_rule_id"), "rule_versions", ["rule_id"], unique=False)
    op.create_table(
        "source_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("data_source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=256), nullable=True),
        sa.Column("external_identity_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, comment="uplink, join, ..."),
        sa.Column("acquisition_channel", sa.String(length=16), nullable=False),
        sa.Column("ingestion_method", sa.String(length=16), nullable=False),
        sa.Column(
            "processing_status", sa.String(length=16), server_default="received", nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "provider_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("network_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("satellite_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ble_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "acquisition_channel IN ('lorawan', 'webble', 'log_file', 'iridium', 'cellular', 'api', 'other')",
            name="ck_source_events_channel",
        ),
        sa.CheckConstraint(
            "ingestion_method IN ('mqtt', 'webhook', 'polling', 'websocket', 'browser_sync', 'file_upload')",
            name="ck_source_events_method",
        ),
        sa.CheckConstraint(
            "processing_status IN ('received', 'processed', 'duplicate', 'failed', 'unassigned', 'ignored')",
            name="ck_source_events_status",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["external_identity_id"], ["external_identities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", "ingested_at"),
    )
    op.create_index(
        "ix_source_events_device_time", "source_events", ["device_id", "ingested_at"], unique=False
    )
    op.create_index(
        "ix_source_events_source_external",
        "source_events",
        ["data_source_id", "external_id", "ingested_at"],
        unique=False,
    )
    op.create_index(
        "ix_source_events_status",
        "source_events",
        ["processing_status", "ingested_at"],
        unique=False,
    )
    op.create_index("ix_source_events_trace", "source_events", ["trace_id"], unique=False)
    op.create_geospatial_table(
        "events",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="info", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
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
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("rule_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name="ck_events_severity"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_version_id"], ["rule_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_geospatial_index(
        "idx_events_geom",
        "events",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index("ix_events_entity_time", "events", ["entity_id", "time"], unique=False)
    op.create_index("ix_events_project_time", "events", ["project_id", "time"], unique=False)
    op.create_index("ix_events_type_time", "events", ["event_type", "time"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name="ck_alerts_severity"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name="ck_alerts_status"
        ),
        sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_event_id"), "alerts", ["event_id"], unique=False)
    op.create_index("ix_alerts_project_status", "alerts", ["project_id", "status"], unique=False)

    # TimescaleDB: hypertables from the first migration (decision D3). Compression after 7 days
    # segmented by device, raw source events kept 2 years by default (decision D8). Positions and
    # measurements have no retention policy: they stay online (architecture 13.6).
    for table, column, chunk in HYPERTABLES:
        op.execute(f"SELECT create_hypertable('{table}', by_range('{column}', INTERVAL '{chunk}'))")
    for table, column, segment in COMPRESSION:
        op.execute(
            f"ALTER TABLE {table} SET (timescaledb.enable_columnstore = true, "
            f"timescaledb.segmentby = '{segment}', timescaledb.orderby = '{column} DESC')"
        )
        op.execute(f"CALL add_columnstore_policy('{table}', after => INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('source_events', INTERVAL '730 days')")


def downgrade() -> None:
    op.drop_index("ix_alerts_project_status", table_name="alerts")
    op.drop_index(op.f("ix_alerts_event_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_events_type_time", table_name="events")
    op.drop_index("ix_events_project_time", table_name="events")
    op.drop_index("ix_events_entity_time", table_name="events")
    op.drop_geospatial_index(
        "idx_events_geom", table_name="events", postgresql_using="gist", column_name="geom"
    )
    op.drop_geospatial_table("events")
    op.drop_index("ix_source_events_trace", table_name="source_events")
    op.drop_index("ix_source_events_status", table_name="source_events")
    op.drop_index("ix_source_events_source_external", table_name="source_events")
    op.drop_index("ix_source_events_device_time", table_name="source_events")
    op.drop_table("source_events")
    op.drop_index(op.f("ix_rule_versions_rule_id"), table_name="rule_versions")
    op.drop_table("rule_versions")
    op.drop_index("ix_processing_steps_trace_sequence", table_name="processing_steps")
    op.drop_table("processing_steps")
    op.drop_index("uq_positions_canonical_key", table_name="positions")
    op.drop_index("ix_positions_project_time", table_name="positions")
    op.drop_index("ix_positions_entity_time", table_name="positions")
    op.drop_index("ix_positions_device_time", table_name="positions")
    op.drop_geospatial_index(
        "idx_positions_geom", table_name="positions", postgresql_using="gist", column_name="geom"
    )
    op.drop_geospatial_table("positions")
    op.drop_index("uq_measurements_canonical_key", table_name="measurements")
    op.drop_index("ix_measurements_project_metric_time", table_name="measurements")
    op.drop_index("ix_measurements_entity_metric_time", table_name="measurements")
    op.drop_index("ix_measurements_device_metric_time", table_name="measurements")
    op.drop_table("measurements")
    op.drop_index("ix_entity_current_state_project", table_name="entity_current_state")
    op.drop_geospatial_index(
        "idx_entity_current_state_latest_position",
        table_name="entity_current_state",
        postgresql_using="gist",
        column_name="latest_position",
    )
    op.drop_geospatial_table("entity_current_state")
    op.drop_index("ix_device_entity_assignments_entity", table_name="device_entity_assignments")
    op.drop_index(
        op.f("ix_device_entity_assignments_device_id"), table_name="device_entity_assignments"
    )
    op.drop_table("device_entity_assignments")
    op.drop_index(op.f("ix_rules_project_id"), table_name="rules")
    op.drop_table("rules")
    op.drop_index(op.f("ix_project_memberships_user_id"), table_name="project_memberships")
    op.drop_index(op.f("ix_project_memberships_project_id"), table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_index("ix_processing_traces_status_started", table_name="processing_traces")
    op.drop_index("ix_processing_traces_started", table_name="processing_traces")
    op.drop_index("ix_processing_traces_root", table_name="processing_traces")
    op.drop_index("ix_processing_traces_device_started", table_name="processing_traces")
    op.drop_table("processing_traces")
    op.drop_index(op.f("ix_invitations_project_id"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_email"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_gateway_receptions_gateway_time", table_name="gateway_receptions")
    op.drop_index("ix_gateway_receptions_device_time", table_name="gateway_receptions")
    op.drop_table("gateway_receptions")
    op.drop_index(op.f("ix_features_project_id"), table_name="features")
    op.drop_geospatial_index(
        "idx_features_geom", table_name="features", postgresql_using="gist", column_name="geom"
    )
    op.drop_geospatial_table("features")
    op.drop_index(op.f("ix_external_identities_device_id"), table_name="external_identities")
    op.drop_index(op.f("ix_external_identities_data_source_id"), table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_index(op.f("ix_entities_project_id"), table_name="entities")
    op.drop_index(op.f("ix_entities_entity_type_id"), table_name="entities")
    op.drop_geospatial_index(
        "idx_entities_geom", table_name="entities", postgresql_using="gist", column_name="geom"
    )
    op.drop_geospatial_table("entities")
    op.drop_index("ix_device_state_history_device_time", table_name="device_state_history")
    op.drop_table("device_state_history")
    op.drop_index("ix_device_project_assignments_project", table_name="device_project_assignments")
    op.drop_index(
        op.f("ix_device_project_assignments_device_id"), table_name="device_project_assignments"
    )
    op.drop_table("device_project_assignments")
    op.drop_geospatial_table("device_current_state")
    op.drop_table("data_source_project_scopes")
    op.drop_table("connectivity_state")
    op.drop_index(op.f("ix_audit_log_user_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_time"), table_name="audit_log")
    op.drop_index("ix_audit_log_project_time", table_name="audit_log")
    op.drop_index("ix_audit_log_object", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("projects")
    op.drop_index(op.f("ix_devices_device_type_id"), table_name="devices")
    op.drop_table("devices")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("organizations")
    op.drop_index(op.f("ix_metrics_category"), table_name="metrics")
    op.drop_table("metrics")
    op.drop_table("entity_types")
    op.drop_index(op.f("ix_device_types_driver_key"), table_name="device_types")
    op.drop_table("device_types")
    op.drop_index(op.f("ix_data_sources_adapter_key"), table_name="data_sources")
    op.drop_table("data_sources")
    op.drop_index(op.f("ix_application_errors_error_code"), table_name="application_errors")
    op.drop_table("application_errors")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS postgis CASCADE")
