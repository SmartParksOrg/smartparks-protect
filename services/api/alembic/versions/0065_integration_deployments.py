"""A device on an integrated entity is a deployment of its sensor on the target (decisions
D416 to D419, Tim, 2026-11-22: when a device moves to another entity in Protect, WildlifeNL
must move its sensor to the other animal, after a person confirmed it).

`integration_deployments` holds one row per integration, entity, device and the start of
that assignment: Protect's own account of what it sent, since the target cannot list a
sensor's past deployments. The integration worker makes a `pending` row for every device on
an integrated entity that has none; a person confirms it (`sent`) or declines it.

Nothing is filled in: an entity integrated before this migration gets its rows from the
worker as pending changes, so a person confirms what the target has.

Revision ID: 0065
Revises: 0064
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels = None
depends_on = None

STATES = ("pending", "sent", "refused", "declined")


def upgrade() -> None:
    op.create_table(
        "integration_deployments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "integration_id",
            sa.Uuid(),
            sa.ForeignKey("integrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id", sa.Uuid(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "sensor_id",
            sa.String(256),
            comment="What the target knows the device by, fixed when the row is made",
        ),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="The start of the device's assignment",
        ),
        sa.Column(
            "ends_at",
            sa.DateTime(timezone=True),
            comment="The end of the assignment in Protect; none while on",
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), comment="Why it was refused or is outdated"),
        sa.Column("animal_id", sa.String(200), comment="The target's animal it was sent for"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "integration_id",
            "entity_id",
            "device_id",
            "starts_at",
            name="uq_integration_deployments_assignment",
        ),
        sa.CheckConstraint(
            "state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")",
            name="ck_integration_deployments_state",
        ),
    )
    op.create_index(
        "ix_integration_deployments_integration_id", "integration_deployments", ["integration_id"]
    )
    op.create_index(
        "ix_integration_deployments_entity_id", "integration_deployments", ["entity_id"]
    )
    op.create_index(
        "ix_integration_deployments_device",
        "integration_deployments",
        ["integration_id", "device_id"],
    )


def downgrade() -> None:
    op.drop_table("integration_deployments")
