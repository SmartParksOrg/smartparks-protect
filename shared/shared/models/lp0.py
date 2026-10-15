"""A tracker's LP0 address and keys (phase 42, decision D320).

Provisioned per device like its DevEUI: the address in the clear (it is also the device's
identity on the built-in offload station source), the two session keys as one encrypted
document (`shared/secrets.py`), never returned by the API. The pipeline reads them to verify and
decrypt the frames an offload station stored for the device.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class DeviceLp0Credentials(TimestampMixin, Base):
    __tablename__ = "device_lp0_credentials"

    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    dev_addr: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        unique=True,
        comment="The LP0 DevAddr as printed, eight uppercase hex digits (big-endian)",
    )
    keys_encrypted: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Fernet token of {app_s_key, nwk_s_key} as hex; never returned",
    )
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="person (typed in) or device (taken from the device's own settings readback)",
    )
    set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_f_cnt: Mapped[int | None] = mapped_column(
        BigInteger,
        comment="The 32-bit frame counter of the newest frame that verified, so a frame "
        "carrying only the low 16 bits is read across a rollover as a LoRaWAN receiver "
        "reads it (firmware issue 772)",
    )
    last_frame_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="When that frame was received by a station"
    )
