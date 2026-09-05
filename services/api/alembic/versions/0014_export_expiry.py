"""Export jobs can be expired: the file removed after its retention (architecture 14).

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None

STATUSES_OLD = "('queued', 'running', 'done', 'failed')"
STATUSES_NEW = "('queued', 'running', 'done', 'failed', 'expired')"


def upgrade() -> None:
    op.drop_constraint("ck_export_jobs_status", "export_jobs", type_="check")
    op.create_check_constraint("ck_export_jobs_status", "export_jobs", f"status IN {STATUSES_NEW}")


def downgrade() -> None:
    # An expired job has no file; as a failed job it keeps its parameters for reproduce.
    op.execute(sa.text("UPDATE export_jobs SET status = 'failed' WHERE status = 'expired'"))
    op.drop_constraint("ck_export_jobs_status", "export_jobs", type_="check")
    op.create_check_constraint("ck_export_jobs_status", "export_jobs", f"status IN {STATUSES_OLD}")
