"""The first sighting of identities a platform's device list made (decision D393, Tim,
2026-11-13: Create and reprocess from Needs attention took 17 to 80 s on dev).

A device list sync makes identities without `first_seen_at`, and ingest never filled it when
their first message came, so 552 identities on dev had none and the create dialogs looked it up
over every chunk of the source events. Ingest stamps it now; this fills the identities that have
events from their earliest one, one indexed lookup each (about 1 s for 552 identities on dev).
Identities without events stay empty until their first message.

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE external_identities i
        SET first_seen_at = (
            SELECT min(s.ingested_at) FROM source_events s
            WHERE s.data_source_id = i.data_source_id
              AND s.external_id = i.external_id
              AND s.external_identity_id = i.id
        )
        WHERE i.first_seen_at IS NULL
        """
    )


def downgrade() -> None:
    pass  # the filled sightings are true; nothing to undo
