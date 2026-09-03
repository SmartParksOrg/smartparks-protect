"""Events, alerts, rules and rule versions. Rules are filled in during phase 5."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import AlertStatus, Severity
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class Rule(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_rules_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class RuleVersion(UuidPrimaryKeyMixin, Base):
    """Immutable rule document. Every event references the version that produced it."""

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_versions_rule_version"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Event(UuidPrimaryKeyMixin, Base):
    """A domain fact: geofence exit, possible immobility, species detection."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_project_time", "project_id", "time"),
        Index("ix_events_entity_time", "entity_id", "time"),
        Index("ix_events_type_time", "event_type", "time"),
        enum_check("severity", Severity, "ck_events_severity"),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rule_versions.id", ondelete="SET NULL")
    )
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    source_event_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Alert(UuidPrimaryKeyMixin, Base):
    """An event that needs a person. Separate object from the event (architecture 16)."""

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_project_status", "project_id", "status"),
        enum_check("status", AlertStatus, "ck_alerts_status"),
        enum_check("severity", Severity, "ck_alerts_severity"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
