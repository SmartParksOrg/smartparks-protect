"""Raw device log files as managed assets (architecture 25.6, decision D77).

A row is one file retrieved from a device: uploaded by a person, or received from the browser
after a WebBLE sync (then the "file" is the notification frames the browser saw, stored in the
same line format the public BLE app exports). Every frame of the file is a SourceEvent on the
built-in data source of its channel; the row keeps the file, its status and the counts.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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

from shared.enums import AcquisitionChannel, LogFileStatus
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class DeviceLogFile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_log_files"
    __table_args__ = (
        UniqueConstraint("device_id", "sha256", name="uq_device_log_files_device_sha256"),
        Index("ix_device_log_files_device_uploaded", "device_id", "uploaded_at"),
        Index("ix_device_log_files_status", "status"),
        enum_check("status", LogFileStatus, "ck_device_log_files_status"),
        enum_check("acquisition_channel", AcquisitionChannel, "ck_device_log_files_channel"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="SET NULL"),
        comment="Project the device was assigned to when the file arrived",
    )
    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        comment="The built-in data source of the channel (log_file or webble)",
    )
    acquisition_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="Key in the device log files bucket"
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ble_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="When the browser read the frames from the device"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    frames_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    frames_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="Malformed frames"
    )
    records_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    records_new: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="Canonical rows created"
    )
    records_duplicate: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="Known through another path"
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Earliest canonical device time in the file"
    )
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware_version: Mapped[str | None] = mapped_column(
        String(64), comment="From a status record in the file"
    )
    decoder_version: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
