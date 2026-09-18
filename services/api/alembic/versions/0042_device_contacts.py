"""Bluetooth contacts as a canonical record type (phase 30, decision D252): one row per device
a device saw, resolved on the way in to the device it is, an unknown neighbour, or ambiguous.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels = None
depends_on = None

RESOLUTIONS = "('resolved', 'unknown', 'ambiguous')"


def upgrade() -> None:
    op.create_table(
        "device_contacts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "device_id", sa.Uuid(), nullable=False, comment="The device that did the scanning"
        ),
        sa.Column("project_id", sa.Uuid(), nullable=True, comment="Resolved at canonical time"),
        sa.Column("entity_id", sa.Uuid(), nullable=True, comment="Resolved at canonical time"),
        sa.Column(
            "address",
            sa.String(length=32),
            nullable=False,
            comment="The neighbour as the device names it: three octets, lowercase, aa:bb:cc",
        ),
        sa.Column(
            "rssi_dbm",
            sa.Integer(),
            nullable=True,
            comment="The strongest signal of the sighting; not a distance",
        ),
        sa.Column(
            "sightings",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
            comment="1 unless the device counted",
        ),
        sa.Column(
            "scan_kind",
            sa.String(length=16),
            server_default="single",
            nullable=False,
            comment="single or aggregated",
        ),
        sa.Column(
            "contact_device_id",
            sa.Uuid(),
            nullable=True,
            comment="The device it resolved to; null when unknown or ambiguous",
        ),
        sa.Column(
            "contact_entity_id",
            sa.Uuid(),
            nullable=True,
            comment="What that device tracked at the time of the sighting",
        ),
        sa.Column(
            "resolution",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
            comment="resolved, unknown, ambiguous",
        ),
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="The device ids an ambiguous address matched, so a person can judge",
        ),
        sa.Column("canonical_key", sa.String(length=256), nullable=False),
        sa.Column("data_source_id", sa.Uuid(), nullable=True),
        sa.Column("source_event_id", sa.BigInteger(), nullable=True),
        sa.Column("source_event_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"resolution IN {RESOLUTIONS}", name="ck_device_contacts_resolution"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "time"),
    )
    op.create_index(
        "uq_device_contacts_canonical_key",
        "device_contacts",
        ["canonical_key", "time"],
        unique=True,
    )
    op.create_index("ix_device_contacts_device_time", "device_contacts", ["device_id", "time"])
    op.create_index("ix_device_contacts_project_time", "device_contacts", ["project_id", "time"])
    op.create_index(
        "ix_device_contacts_contact_time", "device_contacts", ["contact_device_id", "time"]
    )
    op.create_index("ix_device_contacts_address_time", "device_contacts", ["address", "time"])
    # a hypertable like the other canonical rows, compressed after a week by the scanning device;
    # no retention policy, so contacts stay online as positions and measurements do
    op.execute("SELECT create_hypertable('device_contacts', by_range('time', INTERVAL '7 days'))")
    op.execute(
        "ALTER TABLE device_contacts SET (timescaledb.enable_columnstore = true, "
        "timescaledb.segmentby = 'device_id', timescaledb.orderby = 'time DESC')"
    )
    op.execute("CALL add_columnstore_policy('device_contacts', after => INTERVAL '7 days')")


def downgrade() -> None:
    op.execute("CALL remove_columnstore_policy('device_contacts', if_exists => true)")
    op.drop_index("ix_device_contacts_address_time", table_name="device_contacts")
    op.drop_index("ix_device_contacts_contact_time", table_name="device_contacts")
    op.drop_index("ix_device_contacts_project_time", table_name="device_contacts")
    op.drop_index("ix_device_contacts_device_time", table_name="device_contacts")
    op.drop_index("uq_device_contacts_canonical_key", table_name="device_contacts")
    op.drop_table("device_contacts")
