"""Attribution jobs (decision D206): the rewrite of a device's records after an assignment
change, run by the export service in windows with its progress on the row, so a page can say
how far it is and the request that changed the assignment returns at once."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import AttributionJobStatus
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class AttributionJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attribution_jobs"
    __table_args__ = (
        Index("ix_attribution_jobs_device_created", "device_id", "created_at"),
        enum_check("status", AttributionJobStatus, "ck_attribution_jobs_status"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="SET NULL"),
        comment="The project the change was made in, for the audit and the pages",
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="The audit action that queued it (project_assignment.start_moved, ...)",
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    time_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    records_total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Positions and measurements in the window when the job was queued",
    )
    records_done: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Records rewritten so far; moves with every window",
    )
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Rows rewritten per table",
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
