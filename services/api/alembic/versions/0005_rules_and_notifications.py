"""Rules, events, alerts, automations and notifications (architecture 15 and 16, phase 5).

Revision: 0005
Revises: 0004
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    # System events and alerts have no project (architecture 26.2, backup alerts, worker health).
    op.alter_column(
        "events",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=True,
        comment="Null for system events, visible to server admins only",
    )
    op.alter_column("alerts", "project_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("rules", sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "rules",
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
            comment="Last evaluation failure; cleared when the rule fires again",
        ),
    )

    op.create_table(
        "rule_state",
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("subject_key", sa.String(length=80), nullable=False),
        sa.Column(
            "state",
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
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id", "subject_key"),
    )

    op.create_table(
        "automations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "event_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Empty means all",
        ),
        sa.Column("min_severity", sa.String(length=16), server_default="info", nullable=False),
        sa.Column("require_alert", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "entity_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rule_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "max_event_age_seconds",
            sa.Integer(),
            server_default=sa.text("21600"),
            nullable=False,
            comment="Older events are skipped, not acted on (architecture 25.8)",
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "min_severity IN ('info', 'warning', 'critical')", name="ck_automations_min_severity"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_automations_project_id"), "automations", ["project_id"])
    op.create_index(
        "uq_automations_project_name",
        "automations",
        ["project_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "notification_targets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=True, comment="Email address"),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("telegram_link_code", sa.String(length=32), nullable=True),
        sa.Column("telegram_link_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "channel IN ('email', 'telegram')", name="ck_notification_targets_channel"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_link_code"),
    )
    op.create_index(
        op.f("ix_notification_targets_project_id"), "notification_targets", ["project_id"]
    )
    op.create_index(
        "uq_notification_targets_project_name",
        "notification_targets",
        ["project_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "action_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("automation_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("action_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "response",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'skipped')",
            name="ck_action_deliveries_status",
        ),
        sa.CheckConstraint(
            "action_type IN ('notify', 'webhook', 'integration', 'command')",
            name="ck_action_deliveries_action_type",
        ),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["notification_targets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_action_deliveries_event_id"), "action_deliveries", ["event_id"])
    op.create_index(
        "ix_action_deliveries_project_created", "action_deliveries", ["project_id", "created_at"]
    )
    op.create_index("ix_action_deliveries_status", "action_deliveries", ["status"])
    op.create_index(
        "uq_action_deliveries_event_automation_index",
        "action_deliveries",
        ["event_id", "automation_id", "action_index"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_table("action_deliveries")
    op.drop_table("notification_targets")
    op.drop_table("automations")
    op.drop_table("rule_state")
    op.drop_column("rules", "last_error")
    op.drop_column("rules", "last_fired_at")
    op.execute("DELETE FROM alerts WHERE project_id IS NULL")
    op.execute("DELETE FROM events WHERE project_id IS NULL")
    op.alter_column("alerts", "project_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("events", "project_id", existing_type=sa.Uuid(), nullable=False, comment=None)
