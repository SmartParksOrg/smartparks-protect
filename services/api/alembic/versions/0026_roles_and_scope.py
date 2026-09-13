"""Roles, custom roles and a member's scope (decisions D185 to D187): the `project_roles`
table, `role_id` and `scope` on memberships and invitations, and the role checks widened to the
operator and analyst roles.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels = None
depends_on = None

ROLES_NOW = "('project-viewer', 'project-operator', 'project-analyst', 'project-admin')"
ROLES_BEFORE = "('project-viewer', 'project-admin')"


def upgrade() -> None:
    op.create_table(
        "project_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "permissions", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_roles_name"),
    )
    op.create_index("ix_project_roles_project_id", "project_roles", ["project_id"])
    for table in ("project_memberships", "invitations"):
        op.add_column(
            table,
            sa.Column(
                "role_id",
                sa.Uuid(),
                sa.ForeignKey("project_roles.id", ondelete="SET NULL"),
                nullable=True,
                comment="A custom role; wins over the built-in role when set",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "scope",
                postgresql.JSONB(),
                nullable=True,
                comment="What the member sees: groups, entities, devices; null for everything",
            ),
        )
    op.create_index("ix_project_memberships_role_id", "project_memberships", ["role_id"])
    op.drop_constraint("ck_project_memberships_role", "project_memberships", type_="check")
    op.create_check_constraint(
        "ck_project_memberships_role", "project_memberships", f"role IN {ROLES_NOW}"
    )
    op.drop_constraint("ck_invitations_role", "invitations", type_="check")
    op.create_check_constraint("ck_invitations_role", "invitations", f"role IN {ROLES_NOW}")


def downgrade() -> None:
    op.execute(
        "UPDATE project_memberships SET role = 'project-viewer' "
        "WHERE role IN ('project-operator', 'project-analyst')"
    )
    op.execute(
        "UPDATE invitations SET role = 'project-viewer' "
        "WHERE role IN ('project-operator', 'project-analyst')"
    )
    op.drop_constraint("ck_invitations_role", "invitations", type_="check")
    op.create_check_constraint("ck_invitations_role", "invitations", f"role IN {ROLES_BEFORE}")
    op.drop_constraint("ck_project_memberships_role", "project_memberships", type_="check")
    op.create_check_constraint(
        "ck_project_memberships_role", "project_memberships", f"role IN {ROLES_BEFORE}"
    )
    op.drop_index("ix_project_memberships_role_id", table_name="project_memberships")
    for table in ("invitations", "project_memberships"):
        op.drop_column(table, "scope")
        op.drop_column(table, "role_id")
    op.drop_index("ix_project_roles_project_id", table_name="project_roles")
    op.drop_table("project_roles")
