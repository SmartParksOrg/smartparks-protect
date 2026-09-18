"""A Bluetooth scanner is a kind of equipment (Tim, 2026-09-18).

Migration 0025 seeded the catalogue and does nothing on a server that has already run it, so a
sub-type added afterwards needs its own migration. The closest the catalogue had was "Stationary
radio" and "Sensor", and neither says what a reader on a post actually does: it listens for the
tags on animals, or for the phones people carry, and it has a place set by hand because it does
not move (decisions D257, D260 and D261).

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels = None
depends_on = None

KEY = "scanner"


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO entity_types (key, label, group_key, icon_key, attribute_schema, parent_id)
        VALUES (
            'scanner', 'Bluetooth scanner', 'equipment', 'device.scanner', '{}'::jsonb,
            (SELECT id FROM entity_types WHERE key = 'equipment')
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # only when nothing was put under it; an entity someone made is not this migration's to remove
    op.execute(
        """
        DELETE FROM entity_types
        WHERE key = 'scanner'
          AND NOT EXISTS (SELECT 1 FROM entities WHERE entity_type_id = entity_types.id)
        """
    )
