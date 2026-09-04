"""Column comment on command_executions.source without a provider name (provider boundary).

Revision: 0007
Revises: 0006
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "api, automation, adapter:<key>, device, expiry"
OLD = "api, automation, adapter:chirpstack, device, expiry"


def upgrade() -> None:
    op.alter_column(
        "command_executions",
        "source",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        comment=NEW,
        existing_comment=OLD,
    )


def downgrade() -> None:
    op.alter_column(
        "command_executions",
        "source",
        existing_type=sa.String(length=64),
        existing_nullable=False,
        comment=OLD,
        existing_comment=NEW,
    )
