"""Fence lines and traps (phase 32, decisions D263 to D266).

A fence line is a feature type of its own; which Fence monitor entity stands on which line and
the line's current reading are two small tables; the Fence monitor and Trap entity types join
the catalogue on servers that already hold it; and `fence_voltage` is corrected to volts, which
is what the FenceEdge reports (the seed said kV).

Revision ID: 0047
Revises: 0046
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels = None
depends_on = None

BEFORE = "('site', 'zone', 'geofence', 'route')"
AFTER = "('site', 'zone', 'geofence', 'route', 'fence')"
TYPES = (
    ("fence_monitor", "Fence monitor", "infrastructure.fence_sensor"),
    ("trap", "Trap", "event.trap"),
)


def upgrade() -> None:
    op.drop_constraint("ck_features_type", "features", type_="check")
    op.create_check_constraint("ck_features_type", "features", f"feature_type IN {AFTER}")
    op.create_table(
        "fence_monitors",
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feature_id",
            sa.Uuid(),
            sa.ForeignKey("features.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    op.create_table(
        "fence_status",
        sa.Column(
            "feature_id",
            sa.Uuid(),
            sa.ForeignKey("features.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column(
            "sections",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "monitors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for key, label, icon in TYPES:
        op.execute(
            f"""
            INSERT INTO entity_types (key, label, group_key, icon_key, attribute_schema, parent_id)
            VALUES (
                '{key}', '{label}', 'equipment', '{icon}', '{{}}'::jsonb,
                (SELECT id FROM entity_types WHERE key = 'equipment')
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    op.execute(
        "UPDATE metrics SET unit = 'V', description = 'Electric fence peak voltage' "
        "WHERE key = 'fence_voltage'"
    )
    op.execute(
        """
        INSERT INTO metrics (key, label, unit, value_type, category, description)
        VALUES
            ('fence_pulse_count', 'Fence pulses', NULL, 'numeric', 'infrastructure',
             'Pulses counted in one fence sampling window'),
            ('fence_energy', 'Fence pulse energy', NULL, 'numeric', 'infrastructure',
             'Average pulse energy of a fence measurement, in the device''s own units')
        ON CONFLICT (key) DO UPDATE SET label = EXCLUDED.label, category = EXCLUDED.category,
            description = EXCLUDED.description
        WHERE metrics.category = 'uncategorized'
        """
    )


def downgrade() -> None:
    op.drop_table("fence_status")
    op.drop_table("fence_monitors")
    op.execute("DELETE FROM features WHERE feature_type = 'fence'")
    op.drop_constraint("ck_features_type", "features", type_="check")
    op.create_check_constraint("ck_features_type", "features", f"feature_type IN {BEFORE}")
    for key, _, _ in TYPES:
        op.execute(
            f"DELETE FROM entity_types WHERE key = '{key}' "
            "AND NOT EXISTS (SELECT 1 FROM entities WHERE entity_type_id = entity_types.id)"
        )
    op.execute("UPDATE metrics SET unit = 'kV' WHERE key = 'fence_voltage'")
