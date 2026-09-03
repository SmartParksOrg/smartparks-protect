"""Entities, features, devices, assignments, data sources, external identities, metrics."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import DeviceStatus, EntityGroup, EntityStatus, FeatureType, ValueType
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class EntityType(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Animal, vehicle, gate, weather station and so on. Admins add rows, not migrations (D6)."""

    __tablename__ = "entity_types"
    __table_args__ = (enum_check("group_key", EntityGroup, "ck_entity_types_group"),)

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    group_key: Mapped[str] = mapped_column(String(32), nullable=False)
    icon_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="JSON schema"
    )
    description: Mapped[str | None] = mapped_column(Text)


class Entity(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """The real-world object being monitored. Devices are linked through assignments."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_entities_project_name"),
        enum_check("status", EntityStatus, "ck_entities_status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entity_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    icon_key: Mapped[str | None] = mapped_column(String(128), comment="Overrides the type icon")
    geom: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True),
        comment="Static location for infrastructure; tracked entities use current state",
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class Feature(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Sites, zones, geofences and routes with geometry."""

    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_features_project_name"),
        enum_check("feature_type", FeatureType, "ck_features_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True), nullable=False
    )
    icon_key: Mapped[str | None] = mapped_column(String(128))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class DeviceType(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Family metadata: which driver decodes it and what it can do."""

    __tablename__ = "device_types"

    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    driver_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    icon_key: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="device.sensor"
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    default_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Device(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Physical hardware. Server level: no project column, membership is an assignment."""

    __tablename__ = "devices"
    __table_args__ = (enum_check("status", DeviceStatus, "ck_devices_status"),)

    device_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("device_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    serial_number: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="inventory")
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notes: Mapped[str | None] = mapped_column(Text)


class DeviceProjectAssignment(UuidPrimaryKeyMixin, Base):
    """Which project owned the device during `validity`. Ranges never overlap per device."""

    __tablename__ = "device_project_assignments"
    __table_args__ = (
        ExcludeConstraint(
            ("device_id", "="),
            ("validity", "&&"),
            name="ex_device_project_assignments_no_overlap",
            using="gist",
        ),
        Index("ix_device_project_assignments_project", "project_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    validity: Mapped[Any] = mapped_column(
        TSTZRANGE, nullable=False, comment="[start, end), end null while current"
    )
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DeviceEntityAssignment(UuidPrimaryKeyMixin, Base):
    """Which entity the device monitored during `validity`. A device monitors one entity at a time;
    an entity may carry several devices."""

    __tablename__ = "device_entity_assignments"
    __table_args__ = (
        ExcludeConstraint(
            ("device_id", "="),
            ("validity", "&&"),
            name="ex_device_entity_assignments_no_overlap",
            using="gist",
        ),
        Index("ix_device_entity_assignments_entity", "entity_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    validity: Mapped[Any] = mapped_column(TSTZRANGE, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DataSource(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """An external platform account: a ChirpStack instance, a KPN account, a Traccar server."""

    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="Non-secret settings"
    )
    credentials_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, comment="Fernet-encrypted JSON, never returned by the API"
    )
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="Architecture 8.2"
    )
    link_templates: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="OPEN_DEVICE and so on"
    )
    retention_days: Mapped[int | None] = mapped_column(comment="Raw event retention override")


class DataSourceProjectScope(Base):
    """Optional scoping of a data source to projects (architecture 28.8)."""

    __tablename__ = "data_source_project_scopes"

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    auto_assign: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="Assign unknown devices from this source to the project automatically",
    )


class ExternalIdentity(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Provider identifier (DevEUI, Traccar id, IMEI) resolved to a device. `device_id` is null
    while the identity is unknown; the SourceEvents are kept and shown in Needs Attention."""

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id", "external_id", name="uq_external_identities_source_external_id"
        ),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="dev_eui")
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))


class Metric(Base):
    """Semantic metric registry (architecture 10.2). The key is the primary key."""

    __tablename__ = "metrics"
    __table_args__ = (enum_check("value_type", ValueType, "ck_metrics_value_type"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), comment="Canonical unit, null if none")
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
