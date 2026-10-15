"""Offload stations (phase 42, decisions D319 to D324): the built-in offload station source,
a tracker's LP0 address and keys per device, a gateway's link to the device it is, the Offload
station entity sub-type, the `lp0` channel on files and events, and the station statistics
metrics the OpenCollar port 23 message writes.

Revision ID: 0053
Revises: 0052
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from shared.metrics.seeds import METRIC_SEEDS, seed_sql

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels = None
depends_on = None

SOURCE_ID = "a0000000-0000-0000-0000-0000000000c1"
CHANNELS_BEFORE = "('lorawan', 'webble', 'log_file', 'iridium', 'cellular', 'api', 'other')"
CHANNELS_AFTER = "('lorawan', 'webble', 'log_file', 'iridium', 'lp0', 'cellular', 'api', 'other')"
CHANNEL_CHECKS = (
    ("device_log_files", "ck_device_log_files_channel"),
    ("source_events", "ck_source_events_channel"),
    ("source_deliveries", "ck_source_deliveries_channel"),
)
OFFLOAD_METRICS = tuple(m.key for m in METRIC_SEEDS if m.category == "offload")
ERROR_CODES_BEFORE = (
    "('CONNECTIVITY_AUTH_FAILED', 'CONNECTIVITY_UNAVAILABLE', 'DEVICE_NOT_FOUND', "
    "'DEVICE_IDENTITY_AMBIGUOUS', 'PROJECT_NOT_ASSIGNED', 'PAYLOAD_DECODE_FAILED', "
    "'TIMESTAMP_INVALID', 'CANONICALIZATION_FAILED', 'SCHEMA_VERSION_UNSUPPORTED', "
    "'RULE_EVALUATION_FAILED', 'ACTION_FAILED', 'INTEGRATION_DELIVERY_FAILED', "
    "'COMMAND_REJECTED', 'COMMAND_EXPIRED', 'FILE_PARSE_FAILED', 'EXPORT_FAILED', "
    "'INTERNAL_ERROR')"
)
ERROR_CODES_AFTER = ERROR_CODES_BEFORE[:-1] + ", 'CREDENTIALS_MISSING')"


def _channel_checks(values: str) -> None:
    for table, name in CHANNEL_CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"acquisition_channel IN {values}")


def upgrade() -> None:
    _channel_checks(CHANNELS_AFTER)
    op.drop_constraint("ck_application_errors_code", "application_errors", type_="check")
    op.create_check_constraint(
        "ck_application_errors_code", "application_errors", f"error_code IN {ERROR_CODES_AFTER}"
    )
    op.execute(
        sa.text(
            "INSERT INTO data_sources (id, name, adapter_key, enabled, config, capabilities, "
            "link_templates) VALUES (CAST(:id AS uuid), 'Offload station files', 'lp0_station', "
            "true, '{}'::jsonb, '{\"uplink\": true, \"downlink\": false}'::jsonb, '{}'::jsonb) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(id=SOURCE_ID)
    )
    op.create_table(
        "device_lp0_credentials",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column(
            "dev_addr",
            sa.String(8),
            nullable=False,
            comment="The LP0 DevAddr as printed, eight uppercase hex digits (big-endian)",
        ),
        sa.Column(
            "keys_encrypted",
            sa.LargeBinary(),
            nullable=False,
            comment="Fernet token of {app_s_key, nwk_s_key} as hex; never returned",
        ),
        sa.Column(
            "source",
            sa.String(16),
            nullable=False,
            comment="person (typed in) or device (taken from the device's own settings readback)",
        ),
        sa.Column("set_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_f_cnt",
            sa.BigInteger(),
            nullable=True,
            comment="The 32-bit frame counter of the newest frame that verified, so a frame "
            "carrying only the low 16 bits is read across a rollover as a LoRaWAN receiver "
            "reads it (firmware issue 772)",
        ),
        sa.Column(
            "last_frame_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When that frame was received by a station",
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
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["set_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("device_id"),
        sa.UniqueConstraint("dev_addr", name="uq_device_lp0_credentials_dev_addr"),
    )
    op.add_column(
        "gateways",
        sa.Column(
            "device_id",
            sa.Uuid(),
            nullable=True,
            comment="The device this gateway is, when it is one of ours: an offload station is "
            "a RangerEdge with an SD card and a gateway of the offload station source "
            "(decision D319)",
        ),
    )
    op.create_foreign_key(
        "fk_gateways_device_id_devices",
        "gateways",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_gateways_device_id", "gateways", ["device_id"])
    op.execute(
        """
        INSERT INTO entity_types (key, label, group_key, icon_key, attribute_schema, parent_id)
        VALUES (
            'offload_station', 'Offload station', 'equipment', 'device.lora_gateway', '{}'::jsonb,
            (SELECT id FROM entity_types WHERE key = 'equipment')
        )
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(seed_sql())


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in OFFLOAD_METRICS)
    op.execute(
        f"DELETE FROM metrics WHERE key IN ({keys}) "
        "AND NOT EXISTS (SELECT 1 FROM measurements WHERE measurements.metric_key = metrics.key)"
    )
    op.execute(
        "DELETE FROM entity_types WHERE key = 'offload_station' "
        "AND NOT EXISTS (SELECT 1 FROM entities WHERE entity_type_id = entity_types.id)"
    )
    op.drop_index("ix_gateways_device_id", table_name="gateways")
    op.drop_constraint("fk_gateways_device_id_devices", "gateways", type_="foreignkey")
    op.drop_column("gateways", "device_id")
    op.drop_table("device_lp0_credentials")
    for table in ("source_deliveries", "source_events", "device_log_files"):
        op.execute(sa.text(f"DELETE FROM {table} WHERE acquisition_channel = 'lp0'"))
    op.execute(
        sa.text(
            "DELETE FROM gateway_receptions WHERE data_source_id = CAST(:id AS uuid)"
        ).bindparams(id=SOURCE_ID)
    )
    op.execute(
        sa.text("DELETE FROM gateways WHERE data_source_id = CAST(:id AS uuid)").bindparams(
            id=SOURCE_ID
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM external_identities WHERE data_source_id = CAST(:id AS uuid)"
        ).bindparams(id=SOURCE_ID)
    )
    op.execute(
        sa.text("DELETE FROM data_sources WHERE id = CAST(:id AS uuid)").bindparams(id=SOURCE_ID)
    )
    op.execute("DELETE FROM application_errors WHERE error_code = 'CREDENTIALS_MISSING'")
    op.drop_constraint("ck_application_errors_code", "application_errors", type_="check")
    op.create_check_constraint(
        "ck_application_errors_code", "application_errors", f"error_code IN {ERROR_CODES_BEFORE}"
    )
    _channel_checks(CHANNELS_BEFORE)


_ = postgresql
