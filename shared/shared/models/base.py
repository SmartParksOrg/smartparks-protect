"""Shared column helpers for the ORM models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base

__all__ = ["Base", "TimestampMixin", "UuidPrimaryKeyMixin", "enum_check", "utc_now"]


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class UuidPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=utc_now
    )


def enum_check(column: str, enum: type[StrEnum], name: str) -> CheckConstraint:
    """Check constraint that keeps a text column inside the values of a StrEnum."""
    values = ", ".join(f"'{value}'" for value in enum)
    return CheckConstraint(f"{column} IN ({values})", name=name)
