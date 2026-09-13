"""An invitation for several projects at once (decision D190): the `memberships` list on
invitations, beside the single project, role, custom role and scope of a project invitation.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column("memberships", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invitations", "memberships")
