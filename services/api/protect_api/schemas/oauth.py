import uuid
from datetime import datetime

from pydantic import BaseModel


class ScopeInfo(BaseModel):
    key: str
    description: str


class ConsentInfo(BaseModel):
    """What the consent page shows. `client_host` is the host of a client id metadata document,
    the name the user must judge by (the document is self-asserted)."""

    request_id: uuid.UUID
    client_id: str
    client_name: str | None
    client_uri: str | None
    client_host: str | None
    registration: str
    redirect_uri: str
    redirect_host: str
    loopback_redirect: bool
    scopes: list[ScopeInfo]
    expires_at: datetime


class ConsentDecision(BaseModel):
    redirect_to: str


class ConnectionRead(BaseModel):
    client_id: str
    client_name: str | None
    client_uri: str | None
    client_host: str | None
    registration: str
    scopes: list[str]
    first_authorized_at: datetime
    last_used_at: datetime | None
    active_tokens: int


class ConnectionRevoke(BaseModel):
    client_id: str
