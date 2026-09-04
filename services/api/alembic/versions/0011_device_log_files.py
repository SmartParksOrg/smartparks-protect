"""Device log files and the built-in channel data sources (architecture 25, phase 11).

Revision: 0011
Revises: 0010
Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed ids so every installation has the same built-in sources (decision D77).
BUILTIN_SOURCES = (
    ("a0000000-0000-0000-0000-0000000000b1", "webble", "Browser (WebBLE)", True),
    ("a0000000-0000-0000-0000-0000000000f1", "log_file", "Log file upload", False),
)


def upgrade() -> None:
    op.create_table(
        "device_log_files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "project_id",
            sa.Uuid(),
            nullable=True,
            comment="Project the device was assigned to when the file arrived",
        ),
        sa.Column(
            "data_source_id",
            sa.Uuid(),
            nullable=False,
            comment="The built-in data source of the channel (log_file or webble)",
        ),
        sa.Column("acquisition_channel", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "object_key",
            sa.String(length=512),
            nullable=False,
            comment="Key in the device log files bucket",
        ),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "ble_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the browser read the frames from the device",
        ),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("frames_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "frames_failed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Malformed frames",
        ),
        sa.Column("records_found", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "records_new",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Canonical rows created",
        ),
        sa.Column(
            "records_duplicate",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Known through another path",
        ),
        sa.Column(
            "period_start",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Earliest canonical device time in the file",
        ),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "firmware_version",
            sa.String(length=64),
            nullable=True,
            comment="From a status record in the file",
        ),
        sa.Column("decoder_version", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
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
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'complete', 'failed')",
            name="ck_device_log_files_status",
        ),
        sa.CheckConstraint(
            "acquisition_channel IN ('lorawan', 'webble', 'log_file', 'iridium', 'cellular', "
            "'api', 'other')",
            name="ck_device_log_files_channel",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "sha256", name="uq_device_log_files_device_sha256"),
    )
    op.create_index(
        "ix_device_log_files_device_uploaded", "device_log_files", ["device_id", "uploaded_at"]
    )
    op.create_index("ix_device_log_files_status", "device_log_files", ["status"])

    sources = sa.table(
        "data_sources",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("adapter_key", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("config", postgresql.JSONB()),
        sa.column("capabilities", postgresql.JSONB()),
        sa.column("link_templates", postgresql.JSONB()),
    )
    for source_id, adapter_key, name, downlink in BUILTIN_SOURCES:
        op.execute(
            sources.insert().values(
                id=source_id,
                name=name,
                adapter_key=adapter_key,
                enabled=True,
                config={},
                capabilities={"uplink": True, "downlink": downlink},
                link_templates={},
            )
        )


def downgrade() -> None:
    op.drop_index("ix_device_log_files_status", table_name="device_log_files")
    op.drop_index("ix_device_log_files_device_uploaded", table_name="device_log_files")
    op.drop_table("device_log_files")
    # Frames on the built-in sources are dropped with the sources; nothing else references them
    # with RESTRICT. Positions and measurements keep their rows (the source id becomes null).
    for source_id, _adapter_key, _name, _downlink in BUILTIN_SOURCES:
        op.execute(
            sa.text(
                "DELETE FROM source_deliveries WHERE source_event_id IN "
                "(SELECT id FROM source_events WHERE data_source_id = CAST(:id AS uuid))"
            ).bindparams(id=source_id)
        )
        op.execute(
            sa.text(
                "DELETE FROM source_events WHERE data_source_id = CAST(:id AS uuid)"
            ).bindparams(id=source_id)
        )
        op.execute(
            sa.text("DELETE FROM data_sources WHERE id = CAST(:id AS uuid)").bindparams(
                id=source_id
            )
        )
