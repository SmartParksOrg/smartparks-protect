"""The Bluetooth scan metrics in the registry (Tim, 2026-09-18).

`ble_contacts` is one sample per scan window: how many devices the scan saw, zero included, so a
scanner's activity draws as a line and a person can tell a reader that looked and saw nothing
from one that was not looking. `human_presence` the decoder had been registering by itself as
`uncategorized`, which is where an unknown key lands; both belong in the registry with their
words.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from alembic import op
from shared.metrics.seeds import METRIC_SEEDS, seed_sql

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels = None
depends_on = None

KEYS = ("ble_contacts", "human_presence")


def upgrade() -> None:
    # the whole seed statement, which leaves every existing row as it is; a key already
    # registered automatically keeps its measurements and gains nothing, so it is corrected here
    op.execute(seed_sql())
    for key in KEYS:
        seed = next(m for m in METRIC_SEEDS if m.key == key)
        op.execute(
            f"UPDATE metrics SET label = '{seed.label}', category = '{seed.category}', "
            f"description = '{seed.description.replace("'", "''")}' "
            f"WHERE key = '{key}' AND category = 'uncategorized'"
        )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in KEYS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
