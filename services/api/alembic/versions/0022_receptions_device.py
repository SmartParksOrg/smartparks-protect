"""Gateway receptions stored while their identity was unknown carry no device, and linking the
identity never gave them one, so the gateway layer and the coverage missed every uplink from
before the device existed. Give them the device their source event has now; from here on the
link happens when the identity is linked (decision D121).

Revision ID: 0022
Revises: 0021
"""

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE gateway_receptions r
        SET device_id = e.device_id
        FROM source_events e
        WHERE r.device_id IS NULL
          AND e.id = r.source_event_id
          AND e.ingested_at = r.source_event_ingested_at
          AND e.device_id IS NOT NULL
        """
    )


def downgrade() -> None:
    pass  # the links are right either way
