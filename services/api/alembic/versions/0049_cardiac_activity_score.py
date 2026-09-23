"""The cardiac tag's activity is a score (phase 35, decision D287).

`cmdq_activity_average` was seeded by 0048 as a number whose meaning was not published; it is
the implant's own accelerometer score from 0 to 255. The description is changed only where it
still reads as seeded, so a server whose administrator wrote their own keeps it.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels = None
depends_on = None

KEY = "cmdq_activity_average"
BEFORE = (
    "Sent by the cardiac tag; its meaning and unit are not published (IRNAS issue 389). Not "
    "the collar's own accelerometer activity"
)
AFTER = (
    "The implant's own accelerometer score, unitless from 0 to 255: high while the animal is "
    "awake and moving, low in its sleep. A 0 is the implant's hourly fault, not a reading "
    "(D287). Not the device's own accelerometer activity"
)


def _swap(old: str, new: str) -> None:
    quoted_old = old.replace("'", "''")
    quoted_new = new.replace("'", "''")
    op.execute(
        f"UPDATE metrics SET description = '{quoted_new}' "
        f"WHERE key = '{KEY}' AND description = '{quoted_old}'"
    )


def upgrade() -> None:
    _swap(BEFORE, AFTER)


def downgrade() -> None:
    _swap(AFTER, BEFORE)
