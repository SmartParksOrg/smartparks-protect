"""The device performance analysis module (phase 28, decision D213): the run row's module
check admits its key.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels = None
depends_on = None

BEFORE = "('movement', 'grazing')"
AFTER = "('movement', 'grazing', 'device_performance')"


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {AFTER}")


def downgrade() -> None:
    op.execute("DELETE FROM analysis_runs WHERE module = 'device_performance'")
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {BEFORE}")
