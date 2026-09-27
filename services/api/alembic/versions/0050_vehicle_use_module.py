"""The vehicle use analysis module (phase 39, decision D301): the run row's module check admits
its key.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels = None
depends_on = None

BEFORE = "('movement', 'grazing', 'device_performance', 'contact_tracing', 'cardiac')"
AFTER = "('movement', 'grazing', 'device_performance', 'contact_tracing', 'cardiac', 'vehicle_use')"


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {AFTER}")


def downgrade() -> None:
    op.execute("DELETE FROM analysis_runs WHERE module = 'vehicle_use'")
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {BEFORE}")
