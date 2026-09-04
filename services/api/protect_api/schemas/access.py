import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from protect_api.schemas.common import ORMModel
from shared.enums import Role


class OrganizationCreate(BaseModel):
    """A grouping of projects for server admins (decision D92), not a security boundary."""

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern="^[a-z0-9][a-z0-9-]{1,98}$")


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern="^[a-z0-9][a-z0-9-]{1,98}$")


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    project_count: int = 0


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern="^[a-z0-9][a-z0-9-]{1,98}$")
    description: str | None = None
    timezone: str = "UTC"
    settings: dict[str, Any] = Field(default_factory=dict)
    organization_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    timezone: str | None = None
    settings: dict[str, Any] | None = None
    archived_at: datetime | None = None
    organization_id: uuid.UUID | None = None


class ProjectRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    name: str
    slug: str
    description: str | None
    timezone: str
    settings: dict[str, Any]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectWithRole(ProjectRead):
    role: str


class MemberRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    created_at: datetime


class MemberCreate(BaseModel):
    email: EmailStr
    role: Role


class MemberUpdate(BaseModel):
    role: Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role


class ServerAdminInvitationCreate(BaseModel):
    email: EmailStr


class InvitationRead(ORMModel):
    id: uuid.UUID
    email: str
    project_id: uuid.UUID | None
    role: str | None
    server_admin: bool
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime
    mail_sent: bool = False


class UserAdminRead(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login_at: datetime | None


class AuditRead(ORMModel):
    id: int
    time: datetime
    actor_type: str
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    action: str
    object_type: str
    object_id: str | None
    details: dict[str, Any]
    request_id: str | None
