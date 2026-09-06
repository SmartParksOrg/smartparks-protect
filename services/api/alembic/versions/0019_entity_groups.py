"""Entity groups (phase 15, decision D98, ADR 0020): folders of entities per project, two
levels deep, and the group of an entity.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(),
            nullable=True,
            comment="A top-level group has none; a subgroup's parent is a top-level group",
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "color", sa.String(length=7), nullable=True, comment="#rrggbb, for the map layer"
        ),
        sa.Column("icon_key", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["parent_id"], ["entity_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "parent_id",
            "name",
            name="uq_entity_groups_parent_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_entity_groups_project_id", "entity_groups", ["project_id"])
    op.create_index("ix_entity_groups_parent_id", "entity_groups", ["parent_id"])
    op.add_column(
        "entities",
        sa.Column(
            "group_id",
            sa.Uuid(),
            nullable=True,
            comment="At most one group (decision D98); a deleted group leaves it ungrouped",
        ),
    )
    op.create_foreign_key(
        "fk_entities_group_id",
        "entities",
        "entity_groups",
        ["group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_entities_group_id", "entities", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_entities_group_id", table_name="entities")
    op.drop_constraint("fk_entities_group_id", "entities", type_="foreignkey")
    op.drop_column("entities", "group_id")
    op.drop_index("ix_entity_groups_parent_id", table_name="entity_groups")
    op.drop_index("ix_entity_groups_project_id", table_name="entity_groups")
    op.drop_table("entity_groups")
