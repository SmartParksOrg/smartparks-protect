"""Export jobs accept the GeoParquet format (decision D312).

Revision ID: 0051
Revises: 0050
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels = None
depends_on = None

FORMATS_OLD = "('csv', 'xlsx', 'json', 'geojson', 'gpx')"
FORMATS_NEW = "('csv', 'xlsx', 'json', 'geojson', 'gpx', 'parquet')"


def upgrade() -> None:
    op.drop_constraint("ck_export_jobs_format", "export_jobs", type_="check")
    op.create_check_constraint("ck_export_jobs_format", "export_jobs", f"format IN {FORMATS_NEW}")


def downgrade() -> None:
    # A GeoParquet job cannot exist under the old constraint; its file, if any, stays in the
    # bucket until the retention sweep of a later upgrade.
    op.execute(sa.text("DELETE FROM export_jobs WHERE format = 'parquet'"))
    op.drop_constraint("ck_export_jobs_format", "export_jobs", type_="check")
    op.create_check_constraint("ck_export_jobs_format", "export_jobs", f"format IN {FORMATS_OLD}")
