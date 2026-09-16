"""Device settings as Protect knows them (decisions D228 to D231): the newest value per device
and setting with its source, status and time.

Revision ID: 0038
Revises: 0037
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_settings",
        sa.Column(
            "device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "key",
            sa.String(length=64),
            nullable=False,
            comment="The setting's name in the driver's catalogue",
        ),
        sa.Column("setting_id", sa.Integer(), nullable=True, comment="The catalogue id"),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="The decoded value: a number, a boolean, a string",
        ),
        sa.Column(
            "raw_hex",
            sa.String(length=128),
            nullable=True,
            comment="The bytes as the device sent them",
        ),
        sa.Column(
            "source", sa.String(length=16), nullable=False, comment="frame, ble, command or manual"
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="observed",
            nullable=False,
            comment="observed (the device said so) or sent (a command not yet confirmed by a frame)",
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("commands.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.PrimaryKeyConstraint("device_id", "key"),
    )
    op.create_index("ix_device_settings_observed", "device_settings", ["device_id", "observed_at"])


def downgrade() -> None:
    op.drop_index("ix_device_settings_observed", table_name="device_settings")
    op.drop_table("device_settings")
