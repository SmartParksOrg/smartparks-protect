"""Analyze: export jobs (architecture 14, decision D39) and saved Data Explorer views (D42)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import ExportDataset, ExportFormat, ExportStatus
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class ExportJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """One export: what was asked (`parameters`), what was produced (object, size, hash) and
    what is needed to reproduce it (`metadata`: metric definitions, units, timezone, version)."""

    __tablename__ = "export_jobs"
    __table_args__ = (
        Index("ix_export_jobs_project_created", "project_id", "created_at"),
        Index("ix_export_jobs_status", "status"),
        enum_check("status", ExportStatus, "ck_export_jobs_status"),
        enum_check("dataset", ExportDataset, "ck_export_jobs_dataset"),
        enum_check("format", ExportFormat, "ck_export_jobs_format"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="Filters, layout, timezone: everything the run reads"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Snapshot for reproducibility: metrics with units, version, counts",
    )
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("export_jobs.id", ondelete="SET NULL"), comment="Reproduced from"
    )
    progress_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    object_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="When the object may be removed"
    )


class SavedView(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A Data Explorer configuration saved per project (decision D42)."""

    __tablename__ = "saved_views"
    __table_args__ = (Index("uq_saved_views_project_name", "project_id", "name", unique=True),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    view: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="Filters, chart type, columns; shape by schema_version"
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
