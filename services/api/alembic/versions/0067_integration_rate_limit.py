"""An integration waits as a whole when its target answers 429 (decision D424, Tim, 2026-11-22:
SP051567's history to WildlifeNL took ages and the worker knocked every two seconds while the
platform asked it to wait). `rate_limited_until` holds the moment the target may be called
again. Three partial indexes: live objects that are due, so they go before a long history; the
queued old objects of an entity; and the sent objects of an integration by their time, for the
pace that tells how long a history still needs.

Revision ID: 0067
Revises: 0066
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column(
            "rate_limited_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="The target answered 429: nothing is sent to it before this moment (D424)",
        ),
    )
    op.create_index(
        "ix_integration_deliveries_live_due",
        "integration_deliveries",
        ["integration_id", "next_attempt_at"],
        postgresql_where=sa.text("status = 'queued' AND origin <> 'backfill'"),
    )
    op.create_index(
        "ix_integration_deliveries_backfill_queued",
        "integration_deliveries",
        ["integration_id", "entity_id"],
        postgresql_where=sa.text("status = 'queued' AND origin = 'backfill'"),
    )
    op.create_index(
        "ix_integration_deliveries_integration_delivered",
        "integration_deliveries",
        ["integration_id", "delivered_at"],
        postgresql_where=sa.text("delivered_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_integration_deliveries_integration_delivered", "integration_deliveries")
    op.drop_index("ix_integration_deliveries_backfill_queued", "integration_deliveries")
    op.drop_index("ix_integration_deliveries_live_due", "integration_deliveries")
    op.drop_column("integrations", "rate_limited_until")
