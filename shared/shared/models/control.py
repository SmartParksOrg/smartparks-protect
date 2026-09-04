"""Commands and their lifecycle (architecture 17). A command is one semantic action for one
device, encoded by its driver and delivered by the connectivity adapter of the chosen route;
executions are the timeline of its status changes."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import CommandStatus
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class Command(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_device_created", "device_id", "created_at"),
        Index("ix_commands_project_created", "project_id", "created_at"),
        Index("ix_commands_status", "status"),
        Index("ix_commands_provider_ref", "provider_ref"),
        enum_check("status", CommandStatus, "ck_commands_status"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL")
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL")
    )
    action_key: Mapped[str] = mapped_column(String(64), nullable=False)
    driver_key: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    payload_hex: Mapped[str | None] = mapped_column(String(1024))
    f_port: Mapped[int | None] = mapped_column(Integer)
    confirmed_downlink: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    external_id: Mapped[str | None] = mapped_column(String(128))
    route: Mapped[str | None] = mapped_column(
        String(32), comment="Acquisition channel used: lorawan, webble, iridium"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="created")
    provider_ref: Mapped[str | None] = mapped_column(
        String(128), comment="The platform's id for the queued item"
    )
    provider_response: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), comment="Device confirmation"
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    automation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("automations.id", ondelete="SET NULL")
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("events.id", ondelete="SET NULL")
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transmitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommandExecution(Base):
    """One status change of a command: when, to what, reported by whom."""

    __tablename__ = "command_executions"
    __table_args__ = (
        Index("ix_command_executions_command", "command_id", "time"),
        enum_check("status", CommandStatus, "ck_command_executions_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    command_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commands.id", ondelete="CASCADE"), nullable=False
    )
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="api, automation, adapter:<key>, device, expiry"
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
