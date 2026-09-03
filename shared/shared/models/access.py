"""Users, organizations, projects, memberships, invitations and the audit log."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import ActorType, Role
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Account. Column names follow what FastAPI-Users expects."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), comment="Server admin"
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    full_name: Mapped[str | None] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Tokens issued before this moment are rejected"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant boundary, reserved and not enforced (decision D21)."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class Project(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMembership(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """One role per user per project. Server admins need no row."""

    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_project_memberships_user_project"),
        enum_check("role", Role, "ck_project_memberships_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class Invitation(UuidPrimaryKeyMixin, TimestampMixin, Base):
    """Registration is by invitation only. The token proves ownership of the email address.

    `project_id` and `role` are null for a server admin invitation. An email can hold several
    invitations over time (unlike AddaxAI Connect, where the email is unique).
    """

    __tablename__ = "invitations"
    __table_args__ = (enum_check("role", Role, "ck_invitations_role"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str | None] = mapped_column(String(32))
    server_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class AuditLog(Base):
    """Who did what to which object. Written by the API for every mutating admin action."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_project_time", "project_id", "time"),
        Index("ix_audit_log_object", "object_type", "object_id"),
        enum_check("actor_type", ActorType, "ck_audit_log_actor_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    request_id: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
