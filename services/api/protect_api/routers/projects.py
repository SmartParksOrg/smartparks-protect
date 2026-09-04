"""Projects, members, invitations and the project audit log."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import (
    ProjectContext,
    get_project_context,
    require_permission,
    require_server_admin,
)
from protect_api.mailer import get_mailer
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.access import (
    AuditRead,
    InvitationCreate,
    InvitationRead,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    ProjectWithRole,
)
from shared.config import get_settings
from shared.database import get_session
from shared.models import AuditLog, Invitation, Project, ProjectMembership, User
from shared.permissions import Permission

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=PageResponse[ProjectWithRole])
async def list_projects(
    page: Page = Depends(page),
    organization_id: uuid.UUID | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[ProjectWithRole]:
    """Projects the caller can open, with the caller's role. Server admins see all projects.
    `organization_id` narrows the list to one grouping (decision D92)."""
    if user.is_superuser:
        statement = select(Project)
        if organization_id is not None:
            statement = statement.where(Project.organization_id == organization_id)
        rows, next_cursor = await paginate(session, Project.id, statement, page)
        items = [
            ProjectWithRole(**ProjectRead.model_validate(p).model_dump(), role="server-admin")
            for p in rows
        ]
        return PageResponse(items=items, next_cursor=next_cursor)
    statement = (
        select(Project)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .where(ProjectMembership.user_id == user.id)
    )
    if organization_id is not None:
        statement = statement.where(Project.organization_id == organization_id)
    rows, next_cursor = await paginate(session, Project.id, statement, page)
    membership_rows = await session.execute(
        select(ProjectMembership.project_id, ProjectMembership.role).where(
            ProjectMembership.user_id == user.id
        )
    )
    roles: dict[uuid.UUID, str] = {row[0]: row[1] for row in membership_rows.all()}
    items = [
        ProjectWithRole(**ProjectRead.model_validate(p).model_dump(), role=roles[p.id])
        for p in rows
    ]
    return PageResponse(items=items, next_cursor=next_cursor)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = Project(**body.model_dump())
    session.add(project)
    await flush_or_409(session, "Project")
    await record_audit(
        session,
        user=user,
        action="project.created",
        object_type="project",
        object_id=str(project.id),
        project_id=project.id,
        details={"name": project.name},
    )
    await session.commit()
    return project


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(context: ProjectContext = Depends(get_project_context)) -> Project:
    return context.project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    body: ProjectUpdate,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> Project:
    if body.organization_id != context.project.organization_id and not context.is_server_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a server admin moves a project between organizations"
        )
    changed = apply_patch(context.project, body)
    await flush_or_409(session, "Project")
    await record_audit(
        session,
        user=context.user,
        action="project.updated",
        object_type="project",
        object_id=str(context.project.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return context.project


def _member_read(membership: ProjectMembership, user: User) -> MemberRead:
    return MemberRead(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.get("/{project_id}/members", response_model=PageResponse[MemberRead])
async def list_members(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[MemberRead]:
    statement = select(ProjectMembership).where(ProjectMembership.project_id == context.project.id)
    rows, next_cursor = await paginate(session, ProjectMembership.id, statement, page)
    users = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_([m.user_id for m in rows])))
        ).all()
    }
    return PageResponse(
        items=[_member_read(m, users[m.user_id]) for m in rows], next_cursor=next_cursor
    )


@router.post(
    "/{project_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED
)
async def add_member(
    body: MemberCreate,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    """Add an existing account. Someone without an account gets an invitation instead."""
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No account with this email; send an invitation"
        )
    membership = ProjectMembership(
        user_id=user.id,
        project_id=context.project.id,
        role=body.role,
        added_by_user_id=context.user.id,
    )
    session.add(membership)
    await flush_or_409(session, "Membership")
    await record_audit(
        session,
        user=context.user,
        action="member.added",
        object_type="membership",
        object_id=str(membership.id),
        project_id=context.project.id,
        details={"user_id": str(user.id), "role": body.role},
    )
    await session.commit()
    return _member_read(membership, user)


@router.patch("/{project_id}/members/{membership_id}", response_model=MemberRead)
async def update_member(
    membership_id: uuid.UUID,
    body: MemberUpdate,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> MemberRead:
    membership = await get_or_404(session, ProjectMembership, membership_id, "Membership")
    if membership.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    changed = apply_patch(membership, body)
    await record_audit(
        session,
        user=context.user,
        action="member.updated",
        object_type="membership",
        object_id=str(membership.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    user = await get_or_404(session, User, membership.user_id, "User")
    return _member_read(membership, user)


@router.delete("/{project_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    membership = await get_or_404(session, ProjectMembership, membership_id, "Membership")
    if membership.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    await session.delete(membership)
    await record_audit(
        session,
        user=context.user,
        action="member.removed",
        object_type="membership",
        object_id=str(membership.id),
        project_id=context.project.id,
        details={"user_id": str(membership.user_id)},
    )
    await session.commit()


async def create_invitation_row(
    session: AsyncSession,
    *,
    email: str,
    project: Project | None,
    role: str | None,
    server_admin: bool,
    invited_by: User,
) -> InvitationRead:
    invitation = Invitation(
        email=email.lower(),
        project_id=project.id if project else None,
        role=role,
        server_admin=server_admin,
        token=secrets.token_urlsafe(32),
        invited_by_user_id=invited_by.id,
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().invitation_lifetime_hours),
    )
    session.add(invitation)
    await session.flush()
    await record_audit(
        session,
        user=invited_by,
        action="invitation.created",
        object_type="invitation",
        object_id=str(invitation.id),
        project_id=invitation.project_id,
        details={"email": invitation.email, "role": role, "server_admin": server_admin},
    )
    await session.commit()
    sent = await get_mailer().send_invitation(
        invitation.email,
        invitation.token,
        project_name=project.name if project else None,
        invited_by=invited_by.full_name or invited_by.email,
    )
    return InvitationRead(
        **InvitationRead.model_validate(invitation).model_dump(exclude={"mail_sent"}),
        mail_sent=sent,
    )


@router.get("/{project_id}/invitations", response_model=PageResponse[InvitationRead])
async def list_invitations(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[InvitationRead]:
    statement = select(Invitation).where(Invitation.project_id == context.project.id)
    rows, next_cursor = await paginate(session, Invitation.id, statement, page)
    return PageResponse(
        items=[InvitationRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post(
    "/{project_id}/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED
)
async def invite_member(
    body: InvitationCreate,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> InvitationRead:
    return await create_invitation_row(
        session,
        email=body.email,
        project=context.project,
        role=body.role,
        server_admin=False,
        invited_by=context.user,
    )


@router.delete("/{project_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    invitation = await get_or_404(session, Invitation, invitation_id, "Invitation")
    if invitation.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    if invitation.used_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Invitation already used")
    await session.delete(invitation)
    await record_audit(
        session,
        user=context.user,
        action="invitation.revoked",
        object_type="invitation",
        object_id=str(invitation.id),
        project_id=context.project.id,
        details={"email": invitation.email},
    )
    await session.commit()


@router.get("/{project_id}/audit", response_model=list[AuditRead])
async def project_audit(
    limit: int = 100,
    before: int | None = None,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> list[AuditLog]:
    """Newest first, keyset on id. `before` is the id of the oldest entry already shown."""
    limit = max(1, min(limit, 500))
    statement = select(AuditLog).where(AuditLog.project_id == context.project.id)
    if before is not None:
        statement = statement.where(AuditLog.id < before)
    rows = await session.scalars(statement.order_by(AuditLog.id.desc()).limit(limit))
    return list(rows)
