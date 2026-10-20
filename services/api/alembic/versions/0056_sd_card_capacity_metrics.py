"""The two SD card figures of an offload station's report, version 2 and later (the firmware
branch of 2026-10-20, decision D345): the card's size in whole MB and its free share in whole
percent, seeded as metrics of the `offload` category so the trends, the explorer and the rules
read them; the decoder would register them as `uncategorized` otherwise.

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

from alembic import op
from shared.metrics.seeds import seed_sql

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels = None
depends_on = None

SD_METRICS = ("lp0_sd_capacity_mb", "lp0_sd_free_percent")


def upgrade() -> None:
    op.execute(seed_sql())


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in SD_METRICS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
