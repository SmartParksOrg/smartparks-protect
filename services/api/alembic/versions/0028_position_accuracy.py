"""The accuracy of the position shown (decision D193): `latest_accuracy_m` on both current
states, so the map can draw an accuracy circle and the panels can warn when a location is
imprecise.

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("device_current_state", "entity_current_state"):
        op.add_column(
            table,
            sa.Column(
                "latest_accuracy_m",
                sa.Float(),
                nullable=True,
                comment="Accuracy in metres of the position shown, when the source gave one",
            ),
        )


def downgrade() -> None:
    for table in ("device_current_state", "entity_current_state"):
        op.drop_column(table, "latest_accuracy_m")
