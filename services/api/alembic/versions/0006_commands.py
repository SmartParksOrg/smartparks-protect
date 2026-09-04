"""Commands and command executions (architecture 17, phase 6).

Revision: 0006
Revises: 0005
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "'created', 'encoded', 'submitted', 'accepted_by_network', 'queued', 'scheduled', "
    "'transmitted', 'acknowledged', 'confirmed_by_device', 'failed', 'expired'"
)


def upgrade() -> None:
    op.create_table(
        "commands",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("action_key", sa.String(length=64), nullable=False),
        sa.Column("driver_key", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("payload_hex", sa.String(length=1024), nullable=True),
        sa.Column("f_port", sa.Integer(), nullable=True),
        sa.Column(
            "confirmed_downlink", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column(
            "route",
            sa.String(length=32),
            nullable=True,
            comment="Acquisition channel used: lorawan, webble, iridium",
        ),
        sa.Column("status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column(
            "provider_ref",
            sa.String(length=128),
            nullable=True,
            comment="The platform's id for the queued item",
        ),
        sa.Column(
            "provider_response",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Device confirmation",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "actor",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("automation_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transmitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_commands_status"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commands_device_created", "commands", ["device_id", "created_at"])
    op.create_index("ix_commands_project_created", "commands", ["project_id", "created_at"])
    op.create_index("ix_commands_status", "commands", ["status"])
    op.create_index("ix_commands_provider_ref", "commands", ["provider_ref"])

    op.create_table(
        "command_executions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column(
            "time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            comment="api, automation, adapter:chirpstack, device, expiry",
        ),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_command_executions_status"),
        sa.ForeignKeyConstraint(["command_id"], ["commands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_command_executions_command", "command_executions", ["command_id", "time"])


def downgrade() -> None:
    op.drop_table("command_executions")
    op.drop_table("commands")
