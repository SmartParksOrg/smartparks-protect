"""Hypertables and current-state tables.

Hypertables (`source_events`, `positions`, `measurements`, `gateway_receptions`,
`device_state_history`) have a composite primary key that includes the time column, as
TimescaleDB requires for unique indexes. Nothing references a hypertable with a foreign key
(TimescaleDB does not allow it); references carry the id and the time as plain columns.
"""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import AcquisitionChannel, ConnectivityStatus, IngestionMethod, ProcessingStatus
from shared.models.base import Base, enum_check

HYPERTABLES: dict[str, str] = {
    "source_events": "ingested_at",
    "positions": "time",
    "measurements": "time",
    "gateway_receptions": "time",
    "device_state_history": "time",
}


class SourceEvent(Base):
    """Immutable inbound message. Partitioned on `ingested_at` because the device time is only
    known after decoding. Provenance times are kept separately (architecture 25.3)."""

    __tablename__ = "source_events"
    __table_args__ = (
        Index("ix_source_events_source_external", "data_source_id", "external_id", "ingested_at"),
        Index("ix_source_events_device_time", "device_id", "ingested_at"),
        Index("ix_source_events_status", "processing_status", "ingested_at"),
        Index("ix_source_events_trace", "trace_id"),
        enum_check("processing_status", ProcessingStatus, "ck_source_events_status"),
        enum_check("acquisition_channel", AcquisitionChannel, "ck_source_events_channel"),
        enum_check("ingestion_method", IngestionMethod, "ck_source_events_method"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("now()")
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(256))
    external_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("external_identities.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="uplink, join, ...")
    acquisition_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    ingestion_method: Mapped[str] = mapped_column(String(16), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="received"
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="Inline up to PAYLOAD_INLINE_MAX_BYTES, else null with an object reference"
    )
    payload_object_key: Mapped[str | None] = mapped_column(
        String(512), comment="MinIO key in the uploads bucket for payloads stored out of line"
    )
    payload_size: Mapped[int | None] = mapped_column(Integer)
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    network_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    satellite_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ble_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_code: Mapped[str | None] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class SourceDelivery(Base):
    """Links a canonical row to every source event that delivered it (architecture 25.2). The
    first delivery creates the row; later ones only add a link."""

    __tablename__ = "source_deliveries"
    __table_args__ = (
        Index(
            "uq_source_deliveries_canonical_event",
            "canonical_type",
            "canonical_id",
            "source_event_id",
            unique=True,
        ),
        Index("ix_source_deliveries_source_event", "source_event_id"),
        enum_check("acquisition_channel", AcquisitionChannel, "ck_source_deliveries_channel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    canonical_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="position, measurement, state, event"
    )
    canonical_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_event_ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    acquisition_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    first: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="Created the canonical row"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Position(Base):
    """Canonical geospatial observation. `time` is the device-origin time from the driver."""

    __tablename__ = "positions"
    __table_args__ = (
        Index("uq_positions_canonical_key", "canonical_key", "time", unique=True),
        Index("ix_positions_device_time", "device_id", "time"),
        Index("ix_positions_entity_time", "entity_id", "time"),
        Index("ix_positions_project_time", "project_id", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), comment="Resolved at canonical time"
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL"), comment="Resolved at canonical time"
    )
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="gnss")
    canonical_key: Mapped[str] = mapped_column(String(256), nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False
    )
    altitude_m: Mapped[float | None] = mapped_column(Float)
    speed_mps: Mapped[float | None] = mapped_column(Float)
    heading_deg: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    satellites: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Measurement(Base):
    """Canonical time-series value. Exactly one value column is set (decision D7)."""

    __tablename__ = "measurements"
    __table_args__ = (
        Index("uq_measurements_canonical_key", "canonical_key", "time", unique=True),
        Index("ix_measurements_device_metric_time", "device_id", "metric_key", "time"),
        Index("ix_measurements_entity_metric_time", "entity_id", "metric_key", "time"),
        Index("ix_measurements_project_metric_time", "project_id", "metric_key", "time"),
        CheckConstraint(
            "num_nonnulls(value_num, value_bool, value_text, value_json) = 1",
            name="ck_measurements_one_value",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL")
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL")
    )
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metric_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("metrics.key", ondelete="RESTRICT"), nullable=False
    )
    canonical_key: Mapped[str] = mapped_column(String(256), nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)
    value_text: Mapped[str | None] = mapped_column(String(1024))
    value_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class GatewayReception(Base):
    """Per-uplink reception by one gateway (architecture 20). The gateway registry lands in
    phase 8; until then `gateway_id` is the provider identifier."""

    __tablename__ = "gateway_receptions"
    __table_args__ = (
        Index("ix_gateway_receptions_gateway_time", "gateway_id", "time"),
        Index("ix_gateway_receptions_device_time", "device_id", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rssi: Mapped[float | None] = mapped_column(Float)
    snr: Mapped[float | None] = mapped_column(Float)
    frequency_hz: Mapped[int | None] = mapped_column(BigInteger)
    channel: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class DeviceStateHistory(Base):
    """Every decoded device state, for history. The latest lives in `device_current_state`."""

    __tablename__ = "device_state_history"
    __table_args__ = (Index("ix_device_state_history_device_time", "device_id", "time"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DeviceCurrentState(Base):
    """Latest known state per device (architecture 13.2). Updated by the decoder in the same
    transaction as the canonical rows."""

    __tablename__ = "device_current_state"

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_position: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    latest_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    battery_voltage: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EntityCurrentState(Base):
    """Latest known state per entity: what the live map reads."""

    __tablename__ = "entity_current_state"
    __table_args__ = (Index("ix_entity_current_state_project", "project_id"),)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_position: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    status_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    active_alert_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ConnectivityState(Base):
    """Network view of a device per data source, separate from device health (architecture 20)."""

    __tablename__ = "connectivity_state"
    __table_args__ = (enum_check("status", ConnectivityStatus, "ck_connectivity_state_status"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    last_uplink_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_downlink_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_join_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_rssi: Mapped[float | None] = mapped_column(Float)
    last_snr: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
