"""Ingestion: source deliveries, out-of-line payloads, webhook tokens.

Revision: 0002
Revises: 0001
Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "canonical_type",
            sa.String(length=16),
            nullable=False,
            comment="position, measurement, state, event",
        ),
        sa.Column("canonical_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_id", sa.BigInteger(), nullable=False),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acquisition_channel", sa.String(length=16), nullable=False),
        sa.Column("first", sa.Boolean(), nullable=False, comment="Created the canonical row"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "acquisition_channel IN ('lorawan', 'webble', 'log_file', 'iridium', 'cellular', 'api', 'other')",
            name="ck_source_deliveries_channel",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_source_deliveries_canonical_event",
        "source_deliveries",
        ["canonical_type", "canonical_id", "source_event_id"],
        unique=True,
    )
    op.create_index(
        "ix_source_deliveries_source_event", "source_deliveries", ["source_event_id"], unique=False
    )

    op.alter_column(
        "source_events",
        "payload",
        existing_type=sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        comment="Inline up to PAYLOAD_INLINE_MAX_BYTES, else null with an object reference",
    )
    op.add_column(
        "source_events",
        sa.Column(
            "payload_object_key",
            sa.String(length=512),
            nullable=True,
            comment="MinIO key in the uploads bucket for payloads stored out of line",
        ),
    )
    op.add_column("source_events", sa.Column("payload_size", sa.Integer(), nullable=True))
    op.add_column("source_events", sa.Column("payload_sha256", sa.String(length=64), nullable=True))

    op.add_column(
        "data_sources",
        sa.Column(
            "webhook_token_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 of the bearer token for HTTP push sources (D34)",
        ),
    )
    op.create_index(
        op.f("ix_data_sources_webhook_token_hash"),
        "data_sources",
        ["webhook_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    # Rows whose payload lives in MinIO cannot be represented by 0001; they are deleted.
    op.execute("DELETE FROM source_events WHERE payload IS NULL")
    op.drop_index(op.f("ix_data_sources_webhook_token_hash"), table_name="data_sources")
    op.drop_column("data_sources", "webhook_token_hash")
    op.drop_column("source_events", "payload_sha256")
    op.drop_column("source_events", "payload_size")
    op.drop_column("source_events", "payload_object_key")
    op.alter_column(
        "source_events",
        "payload",
        existing_type=sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        comment=None,
    )
    op.drop_index("ix_source_deliveries_source_event", table_name="source_deliveries")
    op.drop_index("uq_source_deliveries_canonical_event", table_name="source_deliveries")
    op.drop_table("source_deliveries")
