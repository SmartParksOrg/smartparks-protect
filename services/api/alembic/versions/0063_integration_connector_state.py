"""An integration remembers what its connector registered on the target (decision D408, Tim,
2026-11-21: a project admin selects entities and they are integrated with WildlifeNL).

WildlifeNL links a reading to an animal through a deployment registered on the platform.
Protect makes the animal and the deployment itself now, and keeps the animals it made here so a
second run makes none twice. A JSON document per integration, empty for every existing row.

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column(
            "connector_state",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="The connector's own memory between calls, such as what it registered on "
            "the target (D408); never a credential",
        ),
    )


def downgrade() -> None:
    op.drop_column("integrations", "connector_state")
