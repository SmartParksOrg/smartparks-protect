"""Settings files per device (decisions D426 and D428, Tim, 2026-11-27: Protect as the central
place for a device's settings, working with the files the ble-settings-app exports and
imports). One row per file: an upload from the app or a snapshot of a whole read over Web
Bluetooth, the document in the row since a file is about 5 kB of JSON, as json
so the keys keep the order of the file.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_settings_files",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "device_id", sa.Uuid(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            comment="upload (a file from the app) or ble (a snapshot)",
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "document",
            sa.JSON(),
            nullable=False,
            comment="The file: setting name to value, as the app writes it; json, not jsonb, "
            "so the keys keep the file's order",
        ),
        sa.Column(
            "sha256",
            sa.String(length=64),
            nullable=False,
            comment="Of the document with sorted keys",
        ),
        sa.Column("settings_count", sa.Integer(), nullable=False),
        sa.Column(
            "has_credentials",
            sa.Boolean(),
            nullable=False,
            comment="The document holds at least one credential key",
        ),
        sa.Column(
            "firmware_version",
            sa.String(length=32),
            nullable=True,
            comment="The firmware the device reported when the file arrived",
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the values were the device's: the read, or the export the browser named",
        ),
        sa.Column(
            "uploaded_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_device_settings_files_device_created",
        "device_settings_files",
        ["device_id", "created_at"],
    )
    op.alter_column("device_settings", "source", comment="frame, ble, command, manual or file")


def downgrade() -> None:
    op.alter_column("device_settings", "source", comment="frame, ble, command or manual")
    op.drop_index("ix_device_settings_files_device_created", "device_settings_files")
    op.drop_table("device_settings_files")
