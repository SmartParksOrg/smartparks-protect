"""A WildlifeNL integration forwards a device's status messages as readings without a
location (decision D421, Tim, 2026-11-22: the data without a latitude and longitude is needed
too). The connector now says what such an integration forwards: positions, and the status
message's temperature with its accelerometer riding along. The integrations made before carry
"position" alone, so they get the same here.

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE integrations
        SET object_types = '["position", "measurement"]'::jsonb,
            metric_keys = '["device_temperature", "temperature"]'::jsonb
        WHERE connector_key = 'wildlifenl'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE integrations
        SET object_types = '["position"]'::jsonb, metric_keys = '[]'::jsonb
        WHERE connector_key = 'wildlifenl'
        """
    )
