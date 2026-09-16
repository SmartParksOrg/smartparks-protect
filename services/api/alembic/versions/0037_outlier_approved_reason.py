"""GNSS outliers (decisions D221 to D224): the reason code of an approved outlier admitted by
the reason checks of corrections and bulk jobs.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels = None
depends_on = None

BEFORE = (
    "('DEVICE_FIRMWARE_BUG', 'DEVICE_CLOCK_ERROR', 'TIMEZONE_ERROR', 'GPS_OUTLIER', "
    "'CALIBRATION_ERROR', 'WRONG_ENTITY_ASSIGNMENT', 'WRONG_PROJECT_ASSIGNMENT', "
    "'CLASSIFICATION_CORRECTION', 'MANUAL_QC', 'OTHER')"
)
AFTER = (
    "('DEVICE_FIRMWARE_BUG', 'DEVICE_CLOCK_ERROR', 'TIMEZONE_ERROR', 'GPS_OUTLIER', "
    "'OUTLIER_APPROVED', 'CALIBRATION_ERROR', 'WRONG_ENTITY_ASSIGNMENT', "
    "'WRONG_PROJECT_ASSIGNMENT', 'CLASSIFICATION_CORRECTION', 'MANUAL_QC', 'OTHER')"
)
CHECKS = (
    ("ck_curation_jobs_reason", "curation_jobs"),
    ("ck_data_corrections_reason", "data_corrections"),
)


def upgrade() -> None:
    for name, table in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"reason_code IN {AFTER}")


def downgrade() -> None:
    op.execute(
        "UPDATE data_corrections SET reason_code = 'MANUAL_QC' WHERE reason_code = 'OUTLIER_APPROVED'"
    )
    op.execute(
        "UPDATE curation_jobs SET reason_code = 'MANUAL_QC' WHERE reason_code = 'OUTLIER_APPROVED'"
    )
    for name, table in CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"reason_code IN {BEFORE}")
