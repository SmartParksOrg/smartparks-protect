"""Events, alerts, rules, rule state, automations, notification targets and action deliveries
(architecture 15 and 16, phase 5)."""

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

from shared.enums import (
    ActionType,
    AlertStatus,
    DeliveryStatus,
    NotificationChannel,
    Severity,
)
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
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(
        Text, comment="Last evaluation failure; cleared when the rule fires again"
    )


class RuleState(Base):
    """Per rule and subject (entity or device) memory of the stateful evaluator: whether the
    condition is active, since when it holds, last fired, which geofences the subject was in."""

    __tablename__ = "rule_state"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True
    )
    subject_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        comment="Null for system events, visible to server admins only",
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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE")
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


class Automation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A configured reaction to events: which events, which actions (architecture 16). Project
    automations react to project events; server-level automations (project null) to system
    events."""

    __tablename__ = "automations"
    __table_args__ = (
        Index(
            "uq_automations_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        enum_check("min_severity", Severity, "ck_automations_min_severity"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    event_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), comment="Empty means all"
    )
    min_severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    require_alert: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    entity_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    rule_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    max_event_age_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("21600"),
        comment="Older events are skipped, not acted on (architecture 25.8)",
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class NotificationTarget(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Where a notification action delivers: an email address or a Telegram chat. Project
    targets belong to one project; server-level targets (project null) receive system alerts."""

    __tablename__ = "notification_targets"
    __table_args__ = (
        Index(
            "uq_notification_targets_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        enum_check("channel", NotificationChannel, "ck_notification_targets_channel"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[str | None] = mapped_column(String(320), comment="Email address")
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    telegram_link_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    telegram_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class ActionDelivery(UuidPrimaryKeyMixin, Base):
    """One action of one automation for one event: status, attempts, response, trace. The unique
    key makes a re-delivered bus message idempotent."""

    __tablename__ = "action_deliveries"
    __table_args__ = (
        Index(
            "uq_action_deliveries_event_automation_index",
            "event_id",
            "automation_id",
            "action_index",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_action_deliveries_project_created", "project_id", "created_at"),
        Index("ix_action_deliveries_status", "status"),
        enum_check("status", DeliveryStatus, "ck_action_deliveries_status"),
        enum_check("action_type", ActionType, "ck_action_deliveries_action_type"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("alerts.id", ondelete="SET NULL")
    )
    automation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("automations.id", ondelete="SET NULL")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE")
    )
    action_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("notification_targets.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    response: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
