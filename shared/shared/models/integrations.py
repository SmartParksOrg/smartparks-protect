"""Outbound integrations and their deliveries (architecture 18, decisions D60 and D61).

An integration belongs to a project and names a connector (`shared.integrations.registry`).
Its filters decide which canonical objects are forwarded. Every forwarded object gets one
`integration_deliveries` row keyed on (integration, object type, object id, object version);
the row carries the retry schedule, the rendered request, the target's response and the trace.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import (
    DeliveryOrigin,
    DeliveryStatus,
    DeploymentState,
    IntegrationObjectType,
    Severity,
    SubjectState,
)
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class Integration(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_integrations_project_name"),
        enum_check("min_severity", Severity, "ck_integrations_min_severity"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="Non-secret settings"
    )
    credentials_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, comment="Fernet-encrypted JSON, never returned by the API"
    )
    object_types: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text('\'["position", "event"]\'::jsonb'),
        comment="position, event, measurement",
    )
    entity_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Empty means all"
    )
    device_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Empty means all"
    )
    event_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Empty means all"
    )
    metric_keys: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Empty means all"
    )
    min_severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    max_object_age_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("86400"),
        comment="Live objects older than this are not forwarded; backfill ignores it",
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Progress of the last backfill: status, from, to, queued, started_at, finished_at",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class IntegrationDelivery(UuidPrimaryKeyMixin, Base):
    """One canonical object sent to one integration. The unique key is the idempotency key
    (D60); `next_attempt_at` is the retry schedule (D61)."""

    __tablename__ = "integration_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "object_type",
            "object_id",
            "object_version",
            name="uq_integration_deliveries_object",
        ),
        Index("ix_integration_deliveries_due", "status", "next_attempt_at", "integration_id"),
        Index("ix_integration_deliveries_integration_created", "integration_id", "created_at"),
        Index("ix_integration_deliveries_project_created", "project_id", "created_at"),
        enum_check("status", DeliveryStatus, "ck_integration_deliveries_status"),
        enum_check("object_type", IntegrationObjectType, "ck_integration_deliveries_object_type"),
        enum_check("origin", DeliveryOrigin, "ck_integration_deliveries_origin"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    object_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Position or measurement id, or event uuid"
    )
    object_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    object_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False, server_default="live")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Null once the delivery is final"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Set when a curation changed the object after it was sent (architecture 28.10)",
    )
    stale_reason: Mapped[str | None] = mapped_column(String(128))
    external_id: Mapped[str | None] = mapped_column(
        String(256), comment="The target's id for the sent object, when it returns one"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    request: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="The rendered payload of the last attempt"
    )
    response: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IntegrationSubject(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """An entity integrated with a target that keeps a register of its own (decision D412):
    what the user chose for it there, how far its history is, and what the target calls it.
    One row per integration and entity; the integration's `entity_ids` holds the same
    entities, since that is the filter every delivery passes."""

    __tablename__ = "integration_subjects"
    __table_args__ = (
        UniqueConstraint("integration_id", "entity_id", name="uq_integration_subjects_entity"),
        enum_check("state", SubjectState, "ck_integration_subjects_state"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
        comment="What the user chose for this entity on the target, such as its species there",
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, comment="Why it is held or failed")
    history_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="From when its old data is sent; none sends none"
    )
    history_queued: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    history_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(
        String(200),
        comment="The target's id of what Protect registered, kept so a second "
        "attempt makes no second one",
    )
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class IntegrationDeployment(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A device on an integrated entity, as a deployment of its sensor on the target's animal
    (decisions D416 to D419). One row per integration, entity, device and the start of that
    assignment, so a device that comes back to an entity is a row of its own. Protect's own
    account of what it sent: the target has no call to read a sensor's past deployments."""

    __tablename__ = "integration_deployments"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "entity_id",
            "device_id",
            "starts_at",
            name="uq_integration_deployments_assignment",
        ),
        enum_check("state", DeploymentState, "ck_integration_deployments_state"),
        Index("ix_integration_deployments_device", "integration_id", "device_id"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    sensor_id: Mapped[str | None] = mapped_column(
        String(256), comment="What the target knows the device by, fixed when the row is made"
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="The start of the device's assignment"
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="The end of the assignment in Protect; none while on"
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, comment="Why it was refused or is outdated")
    animal_id: Mapped[str | None] = mapped_column(
        String(200), comment="The target's animal it was sent for"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
