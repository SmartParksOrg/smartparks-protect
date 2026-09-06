"""Air quality metrics of the OpenCollar port 21 message (firmware 7.2.0, phase 15, D100).

Revision ID: 0018
Revises: 0017
"""

from alembic import op
from shared.metrics.seeds import seed_sql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None

KEYS = (
    "air_q_iaq",
    "air_q_temperature",
    "air_q_pressure",
    "air_q_humidity",
    "air_q_raw_gas",
    "air_q_pm2_5_mass",
    "air_q_pm1_mass",
    "air_q_pm10_mass",
    "air_q_pm2_5_number",
    "air_q_pm1_number",
    "air_q_pm10_number",
    "air_q_obstructed",
)


def upgrade() -> None:
    op.execute(seed_sql())


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in KEYS)
    op.execute(f"DELETE FROM metrics WHERE key IN ({keys}) AND category = 'environment'")
