"""Export jobs accept the records dataset (phase 20, decision D144).

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None

DATASETS_OLD = (
    "('source_events', 'positions', 'measurements', 'aggregates', "
    "'movebank_events', 'movebank_reference')"
)
DATASETS_NEW = (
    "('source_events', 'positions', 'measurements', 'aggregates', "
    "'movebank_events', 'movebank_reference', 'records')"
)


def upgrade() -> None:
    op.drop_constraint("ck_export_jobs_dataset", "export_jobs", type_="check")
    op.create_check_constraint(
        "ck_export_jobs_dataset", "export_jobs", f"dataset IN {DATASETS_NEW}"
    )


def downgrade() -> None:
    # A records job cannot exist under the old constraint; its file, if any, stays in the
    # bucket until the retention sweep of a later upgrade.
    op.execute(sa.text("DELETE FROM export_jobs WHERE dataset = 'records'"))
    op.drop_constraint("ck_export_jobs_dataset", "export_jobs", type_="check")
    op.create_check_constraint(
        "ck_export_jobs_dataset", "export_jobs", f"dataset IN {DATASETS_OLD}"
    )
