"""An entity is integrated with a target from its own page (decision D412, Tim, 2026-11-21:
what a target needs to know differs per entity, so the choices belong on the entity).

`integration_subjects` holds one row per integration and entity: what the user chose for the
entity on the target (its species there), how far its history is, and the target's id of what
Protect registered. It replaces `integrations.connector_state` of migration 0063, which kept
the registered animals in one document per integration and was on the dev server for a few
hours with nothing in it.

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels = None
depends_on = None

STATES = ("history_requested", "sending_history", "registered", "held", "failed")


def upgrade() -> None:
    op.create_table(
        "integration_subjects",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "integration_id",
            sa.Uuid(),
            sa.ForeignKey("integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id", sa.Uuid(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "settings",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="What the user chose for this entity on the target, such as its species there",
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("detail", sa.Text(), comment="Why it is held or failed"),
        sa.Column(
            "history_from",
            sa.DateTime(timezone=True),
            comment="From when its old data is sent; none sends none",
        ),
        sa.Column("history_queued", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("history_started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "external_id",
            sa.String(200),
            comment="The target's id of what Protect registered, kept so a second attempt "
            "makes no second one",
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("integration_id", "entity_id", name="uq_integration_subjects_entity"),
        sa.CheckConstraint(
            "state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")",
            name="ck_integration_subjects_state",
        ),
    )
    op.create_index(
        "ix_integration_subjects_integration_id", "integration_subjects", ["integration_id"]
    )
    op.create_index("ix_integration_subjects_entity_id", "integration_subjects", ["entity_id"])
    op.drop_column("integrations", "connector_state")


def downgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("connector_state", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.drop_table("integration_subjects")
