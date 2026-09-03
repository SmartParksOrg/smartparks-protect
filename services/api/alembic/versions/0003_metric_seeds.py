"""Metric registry seeds (architecture 10.2).

Revision: 0003
Revises: 0002
Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op
from shared.metrics.seeds import METRIC_SEEDS, seed_sql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(seed_sql())


def downgrade() -> None:
    # Only rows nobody measured against can go; the rest stay because measurements reference them.
    keys = ", ".join(f"'{m.key}'" for m in METRIC_SEEDS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
