"""Eight metrics the OpenCollar driver writes, in the registry with their words (phase 32, F10).

The driver writes `gnss_pdop` (GNSS position, port 2), `lr_satellites` and `charging_voltage`
(status, port 4), `flash_used_percent` and `flash_messages` (flash status, port 14),
`clock_offset` (device timestamp, port 18) and `switch_active` and `switch_count` (external
switch, ports 19 and 20). No seed defined them, so the decoder registered each one by itself as
`uncategorized` (decision D102). A key already registered that way keeps its measurements and
is corrected here; a key an administrator already curated is left as it is.

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from alembic import op
from shared.metrics.seeds import METRIC_SEEDS, seed_sql

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels = None
depends_on = None

KEYS = (
    "switch_active",
    "switch_count",
    "lr_satellites",
    "gnss_pdop",
    "flash_used_percent",
    "flash_messages",
    "charging_voltage",
    "clock_offset",
)


def _literal(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(seed_sql())
    for key in KEYS:
        seed = next(m for m in METRIC_SEEDS if m.key == key)
        op.execute(
            f"UPDATE metrics SET label = {_literal(seed.label)}, unit = {_literal(seed.unit)}, "
            f"category = {_literal(seed.category)}, description = {_literal(seed.description)} "
            f"WHERE key = '{key}' AND category = 'uncategorized'"
        )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in KEYS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
