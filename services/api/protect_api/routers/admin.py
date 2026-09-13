"""Server administration: accounts, server admin invitations, the global audit log."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.manager import UserManager
from protect_api.auth.users import get_user_manager
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.routers.projects import create_invitation_row
from protect_api.schemas.access import (
    AuditRead,
    InvitationRead,
    MemberScope,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
    ServerAdminInvitationCreate,
    UserAdminDetail,
    UserAdminMembership,
    UserAdminRead,
)
from protect_api.visibility import scope_is_empty
from shared.database import get_session
from shared.enums import Role
from shared.models import (
    AuditLog,
    Invitation,
    Organization,
    Project,
    ProjectMembership,
    ProjectRole,
    User,
)
from shared.permissions import BUILTIN_ROLE_LABELS, permissions_for

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_server_admin)])


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    is_superuser: bool | None = None
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=200)


@router.get("/users", response_model=PageResponse[UserAdminRead])
async def list_users(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[UserAdminRead]:
    rows, next_cursor = await paginate(session, User.id, select(User), page)
    return PageResponse(
        items=[UserAdminRead.model_validate(u) for u in rows], next_cursor=next_cursor
    )


async def _user_detail(session: AsyncSession, user: User) -> UserAdminDetail:
    """The account with its memberships across projects: project, role (built in or custom),
    the keys that role grants, and the scope (decision D189)."""
    rows = (
        await session.execute(
            select(ProjectMembership, Project.name)
            .join(Project, Project.id == ProjectMembership.project_id)
            .where(ProjectMembership.user_id == user.id)
            .order_by(Project.name)
        )
    ).all()
    custom_ids = {m.role_id for m, _ in rows if m.role_id is not None}
    custom = (
        {
            r.id: r
            for r in (
                await session.scalars(select(ProjectRole).where(ProjectRole.id.in_(custom_ids)))
            ).all()
        }
        if custom_ids
        else {}
    )
    memberships = []
    for m, project_name in rows:
        role = custom.get(m.role_id) if m.role_id is not None else None
        permissions = permissions_for(
            Role(m.role),
            server_admin=False,
            custom=list(role.permissions) if role and role.project_id == m.project_id else None,
        )
        memberships.append(
            UserAdminMembership(
                membership_id=m.id,
                project_id=m.project_id,
                project_name=project_name,
                role=Role(m.role),
                role_id=role.id if role else None,
                role_name=role.name if role else BUILTIN_ROLE_LABELS[Role(m.role)],
                permissions=sorted(permissions),
                scope=None if scope_is_empty(m.scope) else MemberScope(**(m.scope or {})),
                created_at=m.created_at,
            )
        )
    return UserAdminDetail(
        **UserAdminRead.model_validate(user).model_dump(), memberships=memberships
    )


@router.get("/users/{user_id}", response_model=UserAdminDetail)
async def get_user(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> UserAdminDetail:
    return await _user_detail(session, await get_or_404(session, User, user_id, "User"))


@router.post("/users/{user_id}/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def send_password_reset(
    user_id: uuid.UUID,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> dict[str, str]:
    """Mail the person a password reset link, the same one they get from the sign-in page."""
    user = await get_or_404(session, User, user_id, "User")
    if not user.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "The account is not active")
    await user_manager.forgot_password(user)
    await record_audit(
        session,
        user=admin,
        action="user.password_reset_sent",
        object_type="user",
        object_id=str(user.id),
        details={"email": user.email},
    )
    await session.commit()
    return {"status": "sent"}


@router.patch("/users/{user_id}", response_model=UserAdminDetail)
async def update_user(
    user_id: uuid.UUID,
    body: UserAdminUpdate,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> UserAdminDetail:
    user = await get_or_404(session, User, user_id, "User")
    if user.id == admin.id and body.is_superuser is False:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot remove your own server admin flag"
        )
    if body.email is not None:
        body = body.model_copy(update={"email": body.email.lower()})
    changed = apply_patch(user, body)
    await flush_or_409(session, "User")
    await record_audit(
        session,
        user=admin,
        action="user.updated",
        object_type="user",
        object_id=str(user.id),
        details=changed,
    )
    await session.commit()
    return await _user_detail(session, user)


@router.get("/invitations", response_model=PageResponse[InvitationRead])
async def list_server_invitations(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[InvitationRead]:
    rows, next_cursor = await paginate(session, Invitation.id, select(Invitation), page)
    return PageResponse(
        items=[InvitationRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post("/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
async def invite_server_admin(
    body: ServerAdminInvitationCreate,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> InvitationRead:
    return await create_invitation_row(
        session, email=body.email, project=None, role=None, server_admin=True, invited_by=admin
    )


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_server_invitation(
    invitation_id: uuid.UUID,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    invitation = await get_or_404(session, Invitation, invitation_id, "Invitation")
    if invitation.used_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Invitation already used")
    await session.delete(invitation)
    await record_audit(
        session,
        user=admin,
        action="invitation.revoked",
        object_type="invitation",
        object_id=str(invitation.id),
        details={"email": invitation.email},
    )
    await session.commit()


@router.get("/audit", response_model=list[AuditRead])
async def server_audit(
    limit: int = 100, before: int | None = None, session: AsyncSession = Depends(get_session)
) -> list[AuditLog]:
    limit = max(1, min(limit, 500))
    statement = select(AuditLog)
    if before is not None:
        statement = statement.where(AuditLog.id < before)
    return list(await session.scalars(statement.order_by(AuditLog.id.desc()).limit(limit)))


# Organizations: a grouping of projects for server admins (decision D92). Membership and
# permissions stay per project; an organization carries no rights of its own.


async def _organization_read(session: AsyncSession, organization: Organization) -> OrganizationRead:
    count = await session.scalar(
        select(func.count()).select_from(Project).where(Project.organization_id == organization.id)
    )
    return OrganizationRead(
        **{k: getattr(organization, k) for k in ("id", "name", "slug", "created_at", "updated_at")},
        project_count=int(count or 0),
    )


@router.get("/organizations", response_model=list[OrganizationRead])
async def list_organizations(
    session: AsyncSession = Depends(get_session),
) -> list[OrganizationRead]:
    rows = await session.scalars(select(Organization).order_by(Organization.name))
    return [await _organization_read(session, organization) for organization in rows]


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    organization = Organization(name=body.name, slug=body.slug)
    session.add(organization)
    await flush_or_409(session, "organization")
    await record_audit(
        session,
        user=admin,
        action="organization.created",
        object_type="organization",
        object_id=str(organization.id),
        details=body.model_dump(),
    )
    await session.commit()
    return await _organization_read(session, organization)


@router.patch("/organizations/{organization_id}", response_model=OrganizationRead)
async def update_organization(
    organization_id: uuid.UUID,
    body: OrganizationUpdate,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    organization = await get_or_404(session, Organization, organization_id, "organization")
    changes = apply_patch(organization, body)
    await flush_or_409(session, "organization")
    await record_audit(
        session,
        user=admin,
        action="organization.updated",
        object_type="organization",
        object_id=str(organization.id),
        details=changes,
    )
    await session.commit()
    return await _organization_read(session, organization)


@router.delete("/organizations/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: uuid.UUID,
    admin: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Deleting a grouping leaves its projects without an organization."""
    organization = await get_or_404(session, Organization, organization_id, "organization")
    await record_audit(
        session,
        user=admin,
        action="organization.deleted",
        object_type="organization",
        object_id=str(organization.id),
        details={"name": organization.name, "slug": organization.slug},
    )
    await session.delete(organization)
    await session.commit()
