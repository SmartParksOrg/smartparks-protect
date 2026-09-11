"""Entity types with sub-types and the standard catalogue (decisions D166 and D167): a type
may hold sub-types one level deep (`parent_id`), an entity references the most specific row,
and every server gets six types with a sub-type per vendored icon, so a new site starts with
Wildlife, Elephant, Ranger, 4x4, Gate and the rest instead of an empty list.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa

from alembic import op
from shared.catalog.entity_types import seed_sql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entity_types",
        sa.Column(
            "parent_id",
            sa.Uuid(),
            nullable=True,
            comment="A sub-type's type (decision D166); one level deep",
        ),
    )
    op.create_foreign_key(
        "fk_entity_types_parent_id_entity_types",
        "entity_types",
        "entity_types",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_entity_types_parent_id", "entity_types", ["parent_id"])
    for statement in seed_sql():
        op.execute(statement)


def downgrade() -> None:
    # The seeded rows stay (entities may reference them); they become plain types again.
    op.drop_index("ix_entity_types_parent_id", table_name="entity_types")
    op.drop_constraint("fk_entity_types_parent_id_entity_types", "entity_types", type_="foreignkey")
    op.drop_column("entity_types", "parent_id")
