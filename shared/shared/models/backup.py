"""Backup and recovery runs (architecture 28.10 and 28.11). Written by scripts/backup.sh and
scripts/restore-verify.sh through `protect_api.backup record`; read by the Backup and recovery
page and the system checks that raise alerts for failed or stale runs."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import BackupKind, BackupStatus
from shared.models.base import Base, enum_check


class BackupRun(Base):
    __tablename__ = "backup_runs"
    __table_args__ = (
        Index("ix_backup_runs_kind_started", "kind", "started_at"),
        enum_check("kind", BackupKind, "ck_backup_runs_kind"),
        enum_check("status", BackupStatus, "ck_backup_runs_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    label: Mapped[str | None] = mapped_column(String(128), comment="pgBackRest backup label")
    host: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
