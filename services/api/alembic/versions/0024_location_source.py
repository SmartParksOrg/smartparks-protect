"""The location source of an entity and a device (decision D164): whether the current position
follows the device's own fixes, the network's locations, or the device with the network as a
fallback after a period; and on both current states the kind of the position shown and the
time of the newest device fix, so a network estimate never hides a later fix.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("entities", "devices"):
        op.add_column(
            table,
            sa.Column(
                "location_source",
                sa.String(length=24),
                nullable=False,
                server_default="device",
                comment="device, network or device_else_network (D164)",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "location_fallback_hours",
                sa.Integer(),
                nullable=False,
                server_default="24",
                comment="Hours without a device fix before a network location stands in",
            ),
        )
    for table in ("device_current_state", "entity_current_state"):
        op.add_column(
            table,
            sa.Column(
                "latest_position_kind",
                sa.String(length=16),
                nullable=True,
                comment="device or network: what the latest position is (D164)",
            ),
        )
        op.add_column(
            table,
            sa.Column("latest_fix_time", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for table in ("device_current_state", "entity_current_state"):
        op.drop_column(table, "latest_fix_time")
        op.drop_column(table, "latest_position_kind")
    for table in ("entities", "devices"):
        op.drop_column(table, "location_fallback_hours")
        op.drop_column(table, "location_source")
