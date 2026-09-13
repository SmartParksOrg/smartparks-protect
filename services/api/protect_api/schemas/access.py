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


class MemberScope(BaseModel):
    """What a member sees (decision D186): groups with everything below them, single entities
    and single devices; an empty scope means the whole project."""

    groups: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    entities: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    devices: list[uuid.UUID] = Field(default_factory=list, max_length=500)

    @property
    def empty(self) -> bool:
        return not (self.groups or self.entities or self.devices)


class ProjectWithRole(ProjectRead):
    role: str
    #: The caller's permission keys in the project (decision D188), the interface's gates.
    permissions: list[str] = Field(default_factory=list)
    #: Whether a scope limits what the caller sees.
    scope_limited: bool = False


class ProjectRoleRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    permissions: list[str]
    members: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=50)


class ProjectRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=50)


class MemberRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    role_id: uuid.UUID | None = None
    role_name: str = ""
    permissions: list[str] = Field(default_factory=list)
    scope: MemberScope | None = None
    created_at: datetime


class MemberCreate(BaseModel):
    email: EmailStr
    role: Role = Role.PROJECT_VIEWER
    role_id: uuid.UUID | None = None
    scope: MemberScope | None = None


class MemberUpdate(BaseModel):
    role: Role | None = None
    #: A custom role; null clears it so the built-in role applies again.
    role_id: uuid.UUID | None = None
    #: The scope; null or an empty scope means the whole project.
    scope: MemberScope | None = None


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role = Role.PROJECT_VIEWER
    role_id: uuid.UUID | None = None
    scope: MemberScope | None = None


class InvitationMembership(BaseModel):
    """One membership an invitation creates at registration (decision D190)."""

    project_id: uuid.UUID
    role: Role = Role.PROJECT_VIEWER
    role_id: uuid.UUID | None = None
    scope: MemberScope | None = None


class ServerInvitationCreate(BaseModel):
    """A server admin's invitation: server admin or not, and memberships in any projects."""

    email: EmailStr
    server_admin: bool = False
    memberships: list[InvitationMembership] = Field(default_factory=list, max_length=100)


class InvitationRead(ORMModel):
    id: uuid.UUID
    email: str
    project_id: uuid.UUID | None
    role: str | None
    role_id: uuid.UUID | None = None
    scope: MemberScope | None = None
    memberships: list[InvitationMembership] | None = None
    server_admin: bool
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime
    mail_sent: bool = False
    #: Why the mail was not sent, and the registration link to share by hand instead.
    mail_reason: str | None = None
    registration_link: str | None = None


class UserAdminRead(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login_at: datetime | None


class ServerInvitationResult(BaseModel):
    """What a server admin's invitation did: an invitation mailed (or its link to share), or
    for an address that already has an account, the memberships added straight away."""

    invitation: InvitationRead | None = None
    user_id: uuid.UUID | None = None
    added_projects: list[str] = Field(default_factory=list)


class UserAdminMembership(BaseModel):
    """One of a person's memberships as the server admin's user page shows it (D189)."""

    membership_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    role: Role
    role_id: uuid.UUID | None = None
    role_name: str = ""
    permissions: list[str] = Field(default_factory=list)
    scope: MemberScope | None = None
    created_at: datetime


class UserAdminDetail(UserAdminRead):
    memberships: list[UserAdminMembership] = Field(default_factory=list)


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
