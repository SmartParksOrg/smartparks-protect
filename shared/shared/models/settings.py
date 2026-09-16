"""Device settings as Protect knows them (decisions D228 to D231): one row per device and
setting of the type's catalogue, the newest value seen with where it came from (a frame the
device sent, a WebBLE read, a command Protect sent, a person's entry), so the device page and
the analyses read the same thing."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin

SETTING_SOURCES = ("frame", "ble", "command", "manual")
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
        String(16), nullable=False, comment="frame, ble, command or manual"
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
