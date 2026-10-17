"""What Protect keeps for Protect Go, the companion for the place without a connection
(phase 43, decision D331): the offline map of a project's area, one extract per project."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base


class MapExtract(Base):
    """A PMTiles extract of the project's area, cut from a Protomaps planet build by the export
    worker and kept in MinIO (phase 43 P3; Protect Go's decision D4). One row per project: the
    newest extract, or the one being made, or the reason the last attempt failed."""

    __tablename__ = "map_extracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'failed')", name="ck_map_extracts_status"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    west: Mapped[float] = mapped_column(Float, nullable=False)
    south: Mapped[float] = mapped_column(Float, nullable=False)
    east: Mapped[float] = mapped_column(Float, nullable=False)
    north: Mapped[float] = mapped_column(Float, nullable=False)
    max_zoom: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str | None] = mapped_column(
        Text, comment="The planet build the extract was cut from"
    )
    build: Mapped[str | None] = mapped_column(String(32), comment="The build's date, YYYYMMDD")
    object_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
