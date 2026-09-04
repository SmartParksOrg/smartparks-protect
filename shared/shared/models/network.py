"""Gateways (architecture 20, decision D66) and polling cursors of data sources."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import ConnectivityStatus
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class Gateway(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """A gateway of one data source, identified by the provider's gateway id. Rows appear from
    receptions and gateway events and are completed by a sync against the platform. Server
    level: a gateway serves whichever projects' devices it hears."""

    __tablename__ = "gateways"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="uq_gateways_source_external_id"),
        enum_check("status", ConnectivityStatus, "ck_gateways_status"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    altitude_m: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Last reception or gateway event"
    )
    last_stats_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Latest counters the platform reports: rx_packets, tx_packets, tx_errors",
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Provider diagnostics, never part of the canonical schema",
    )
    name_override: Mapped[str | None] = mapped_column(
        String(200), comment="Set by an administrator, wins over the platform name"
    )


class DataSourceCursor(Base):
    """Where a polling connector is: opaque per adapter. Separate from `data_sources` so a
    cursor update does not restart the connector."""

    __tablename__ = "data_source_cursors"

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
