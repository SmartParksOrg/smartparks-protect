"""The device's own Bluetooth address (phase 30, decision D252), so a neighbour's scan can be
matched to the device that made it.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "ble_mac",
            sa.String(length=17),
            nullable=True,
            comment="The device's Bluetooth address, printed high octet first (decision D252): "
            "from the device itself, a command's answer or a person. A neighbour's scan reports "
            "its last three octets, which is how a contact is matched to the device that made it",
        ),
    )
    # a scan carries only the last three octets, so that suffix is what a resolver looks up
    op.execute(
        "CREATE INDEX ix_devices_ble_mac_suffix ON devices (right(lower(ble_mac), 8)) "
        "WHERE ble_mac IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_devices_ble_mac_suffix", table_name="devices")
    op.drop_column("devices", "ble_mac")
