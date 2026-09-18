"""The contact tracing analysis module (phase 31): the run row's module check admits its key.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels = None
depends_on = None

BEFORE = "('movement', 'grazing', 'device_performance')"
AFTER = "('movement', 'grazing', 'device_performance', 'contact_tracing')"


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {AFTER}")


def downgrade() -> None:
    op.execute("DELETE FROM analysis_runs WHERE module = 'contact_tracing'")
    op.drop_constraint("ck_analysis_runs_module", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_module", "analysis_runs", f"module IN {BEFORE}")
