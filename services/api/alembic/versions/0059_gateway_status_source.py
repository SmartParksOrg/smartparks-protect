"""Where a gateway's status word came from, and when (decision D370, Tim, 2026-11-06: gateway
ac1f09fffe1e9c83 of LoRaNAM relayed its last uplink on 29 October and still read "online" a
week later, since a reception sets a gateway online and nothing aged that).

`gateways.status_source` says who set `status`: `platform` (the gateway list, a connection
event) or `reception` (an uplink it relayed); `status_at` says when. The reads derive the
status shown from these and `last_seen_at`: the platform's word while it is fresh, else online
only while the gateway was seen within `GATEWAY_SILENT_HOURS`, "silent" after that. Rows from
before this migration carry no source and are read by the age of their evidence.

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gateways",
        sa.Column(
            "status_source",
            sa.String(length=16),
            nullable=True,
            comment="Who set the status: platform (list, connection event) or reception (D370)",
        ),
    )
    op.add_column(
        "gateways",
        sa.Column(
            "status_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the status was set (D370)",
        ),
    )


def downgrade() -> None:
    op.drop_column("gateways", "status_at")
    op.drop_column("gateways", "status_source")
