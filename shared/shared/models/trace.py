"""Processing traces, steps and structured errors (architecture 26.10)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import ErrorCode, ErrorSeverity, TraceClass, TraceStatus
from shared.models.base import Base, enum_check


class ApplicationError(Base):
    __tablename__ = "application_errors"
    __table_args__ = (
        enum_check("error_code", ErrorCode, "ck_application_errors_code"),
        enum_check("severity", ErrorSeverity, "ck_application_errors_severity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_actionable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    technical_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ProcessingTrace(Base):
    """One per flow: inbound message, command, import, delivery, export. Compact traces of
    routine successful telemetry keep their steps in `compact_steps` instead of step rows."""

    __tablename__ = "processing_traces"
    __table_args__ = (
        Index("ix_processing_traces_started", "started_at"),
        Index("ix_processing_traces_root", "root_object_type", "root_object_id"),
        Index("ix_processing_traces_device_started", "device_id", "started_at"),
        Index("ix_processing_traces_status_started", "status", "started_at"),
        enum_check("status", TraceStatus, "ck_processing_traces_status"),
        enum_check("trace_class", TraceClass, "ck_processing_traces_class"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    root_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    root_object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    trace_class: Mapped[str] = mapped_column(String(16), nullable=False, server_default="routine")
    compact: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    compact_steps: Mapped[list[Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    data_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    error_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("application_errors.id", ondelete="SET NULL")
    )
    actor: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="user, client_type, client_name for commands and MCP calls"
    )


class ProcessingStep(Base):
    __tablename__ = "processing_steps"
    __table_args__ = (
        Index("ix_processing_steps_trace_sequence", "trace_id", "sequence", unique=True),
        enum_check("status", TraceStatus, "ck_processing_steps_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("processing_traces.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_ref: Mapped[str | None] = mapped_column(String(256))
    output_ref: Mapped[str | None] = mapped_column(String(256))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("application_errors.id", ondelete="SET NULL")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
