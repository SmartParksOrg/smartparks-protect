"""Cardiac monitoring from a LINQII tag (phase 34, decisions D282 to D284).

The physiology metrics the OpenCollar Edge's port 15 now writes, and the run row's module check
widened for the cardiac study. A key that had already registered itself as `uncategorized`,
which is where an unknown key lands, keeps its measurements and is given its words here.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from alembic import op
from shared.metrics.seeds import METRIC_SEEDS, seed_sql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels = None
depends_on = None

KEYS = tuple(m.key for m in METRIC_SEEDS if m.category == "physiology")

BEFORE = "('movement', 'grazing', 'device_performance', 'contact_tracing')"
AFTER = "('movement', 'grazing', 'device_performance', 'contact_tracing', 'cardiac')"


def upgrade() -> None:
    op.execute(seed_sql())
    for key in KEYS:
        seed = next(m for m in METRIC_SEEDS if m.key == key)
        unit = "NULL" if seed.unit is None else "'" + seed.unit.replace("'", "''") + "'"
        op.execute(
            f"UPDATE metrics SET label = '{seed.label.replace("'", "''")}', "
            f"unit = {unit}, category = '{seed.category}', "
            f"description = '{seed.description.replace("'", "''")}' "
            f"WHERE key = '{key}' AND category = 'uncategorized'"
        )
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {AFTER}")


def downgrade() -> None:
    op.execute("DELETE FROM analysis_runs WHERE module = 'cardiac'")
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {BEFORE}")
    keys = ", ".join(f"'{k}'" for k in KEYS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
