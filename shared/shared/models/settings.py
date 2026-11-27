"""Device settings as Protect knows them (decisions D228 to D231): one row per device and
setting of the type's catalogue, the newest value seen with where it came from (a frame the
device sent, a WebBLE read, a command Protect sent, a person's entry), so the device page and
the analyses read the same thing."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

SETTING_SOURCES = ("frame", "ble", "command", "manual", "file")
SETTINGS_FILE_SOURCES = ("upload", "ble")
SETTING_STATUSES = ("observed", "sent")


class DeviceSetting(TimestampMixin, Base):
    __tablename__ = "device_settings"
    __table_args__ = (Index("ix_device_settings_observed", "device_id", "observed_at"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="The setting's name in the driver's catalogue"
    )
    setting_id: Mapped[int | None] = mapped_column(Integer, comment="The catalogue id")
    value: Mapped[Any] = mapped_column(
        JSONB, nullable=False, comment="The decoded value: a number, a boolean, a string"
    )
    raw_hex: Mapped[str | None] = mapped_column(
        String(128), comment="The bytes as the device sent them"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="frame, ble, command, manual or file"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="observed",
        comment="observed (the device said so) or sent (a command not yet confirmed by a frame)",
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_id: Mapped[int | None] = mapped_column(BigInteger)
    command_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("commands.id", ondelete="SET NULL")
    )
    set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class DeviceSettingsFile(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A device's settings as one file in the format of the ble-settings-app (decisions D426
    and D428): a file a person uploaded from the app, or a snapshot Protect made from a whole
    read over Web Bluetooth. The document is kept as it came, credentials included; who may
    download those is decided on the way out (D429)."""

    __tablename__ = "device_settings_files"
    __table_args__ = (Index("ix_device_settings_files_device_created", "device_id", "created_at"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="upload (a file from the app) or ble (a snapshot)"
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="The file: setting name to value, as the app writes it; json, not jsonb, "
        "so the keys keep the file's order",
    )
    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Of the document with sorted keys"
    )
    settings_count: Mapped[int] = mapped_column(Integer, nullable=False)
    has_credentials: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="The document holds at least one credential key"
    )
    firmware_version: Mapped[str | None] = mapped_column(
        String(32), comment="The firmware the device reported when the file arrived"
    )
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="When the values were the device's: the read, or the export the browser named",
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
