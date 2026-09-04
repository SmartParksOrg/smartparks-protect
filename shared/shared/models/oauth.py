"""OAuth clients, authorization codes and refresh tokens for AI clients (architecture 27.5,
decisions D68 to D70). Access tokens are JWTs and have no table."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import OAuthClientKind
from shared.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin, enum_check


class OAuthClient(TimestampMixin, Base):
    """A registered AI client: dynamically registered (RFC 7591) or a fetched client id metadata
    document (the client id is its URL). `document` is the metadata as registered or fetched."""

    __tablename__ = "oauth_clients"
    __table_args__ = (enum_check("kind", OAuthClientKind, "ck_oauth_clients_kind"),)

    client_id: Mapped[str] = mapped_column(String(1024), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(200))
    client_uri: Mapped[str | None] = mapped_column(Text)
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(32), nullable=False)
    client_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    client_secret_expires_at: Mapped[int | None] = mapped_column(BigInteger)
    document: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="When a metadata document was last fetched"
    )


class OAuthAuthorizationCode(UuidPrimaryKeyMixin, Base):
    """One authorization request: created at /authorize, completed by the user's consent (which
    sets `user_id` and `code`), consumed once at /token."""

    __tablename__ = "oauth_authorization_codes"
    __table_args__ = (Index("ix_oauth_authorization_codes_code", "code", unique=True),)

    client_id: Mapped[str] = mapped_column(
        String(1024), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(256), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String(128))
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Until when the consent may be given"
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OAuthRefreshToken(UuidPrimaryKeyMixin, Base):
    """Stored hashed, rotated on every use (OAuth 2.1 for public clients). A revoked or expired
    row ends the connection; the access token dies within its own lifetime."""

    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (Index("ix_oauth_refresh_tokens_user_client", "user_id", "client_id"),)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_id: Mapped[str] = mapped_column(
        String(1024), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
