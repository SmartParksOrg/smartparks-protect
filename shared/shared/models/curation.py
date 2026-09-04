"""Data corrections and bulk curation jobs (architecture 28, decisions D80 to D82).

A correction is an overlay on one canonical record: which field, the value before, the value
after, why, who and when, and its status in the chain of corrections on that field. A job
groups the corrections of one bulk transformation with its selection, preview and impact.
Source events and raw payloads are never touched (architecture 28.15).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import (
    CorrectionStatus,
    CurationField,
    CurationJobStatus,
    CurationReason,
    CurationTarget,
)
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class CurationJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "curation_jobs"
    __table_args__ = (
        Index("ix_curation_jobs_project_created", "project_id", "created_at"),
        enum_check("status", CurationJobStatus, "ck_curation_jobs_status"),
        enum_check("target_type", CurationTarget, "ck_curation_jobs_target"),
        enum_check("reason_code", CurationReason, "ck_curation_jobs_reason"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="previewed")
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    device_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    entity_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    metric_keys: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    time_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transformation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    replay_rules: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    preview: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    impact: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reverted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class DataCorrection(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_corrections"
    __table_args__ = (
        Index("ix_data_corrections_project_status_created", "project_id", "status", "created_at"),
        Index("ix_data_corrections_target", "target_type", "target_id", "target_time"),
        Index("ix_data_corrections_job", "curation_job_id"),
        enum_check("status", CorrectionStatus, "ck_data_corrections_status"),
        enum_check("target_type", CurationTarget, "ck_data_corrections_target"),
        enum_check("field", CurationField, "ck_data_corrections_field"),
        enum_check("reason_code", CurationReason, "ck_data_corrections_reason"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="SET NULL"),
        comment="Project of the record when the correction was made",
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="The record's original time (its key)"
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="SET NULL")
    )
    metric_key: Mapped[str | None] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(16), nullable=False)
    original_value: Mapped[Any] = mapped_column(
        JSONB, nullable=False, comment="The effective value before this correction"
    )
    corrected_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    impact: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
        comment="Attribution before and after, deliveries flagged",
    )
    curation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("curation_jobs.id", ondelete="SET NULL")
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("data_corrections.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revert_comment: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
