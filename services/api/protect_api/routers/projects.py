"""Projects, members, invitations and the project audit log."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
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
    MemberScope,
    MemberUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectRoleCreate,
    ProjectRoleRead,
    ProjectRoleUpdate,
    ProjectUpdate,
    ProjectWithRole,
)
from protect_api.visibility import scope_is_empty
from shared.analysis import project_modules
from shared.config import get_settings
from shared.database import get_session
from shared.enums import Role
from shared.models import (
    AuditLog,
    Device,
    DeviceProjectAssignment,
    Entity,
    Group,
    Invitation,
    Project,
    ProjectMembership,
    ProjectRole,
    User,
)
from shared.notifications.email import allowed_recipient
from shared.permissions import (
    BUILTIN_ROLE_LABELS,
    Permission,
    normalise_permissions,
    permissions_for,
)

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
            ProjectWithRole(
                **ProjectRead.model_validate(p).model_dump(),
                role="server-admin",
                permissions=sorted(permissions_for(None, server_admin=True)),
                analysis_modules=project_modules(get_settings(), p.settings),
            )
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
    memberships = {
        m.project_id: m
        for m in (
            await session.scalars(
                select(ProjectMembership).where(ProjectMembership.user_id == user.id)
            )
        ).all()
    }
    custom_ids = {m.role_id for m in memberships.values() if m.role_id is not None}
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
    items = []
    for p in rows:
        m = memberships[p.id]
        role = custom.get(m.role_id) if m.role_id is not None else None
        permissions = permissions_for(
            Role(m.role),
            server_admin=False,
            custom=list(role.permissions) if role and role.project_id == p.id else None,
        )
        items.append(
            ProjectWithRole(
                **ProjectRead.model_validate(p).model_dump(),
                role=m.role,
                permissions=sorted(permissions),
                scope_limited=not scope_is_empty(m.scope),
                analysis_modules=project_modules(get_settings(), p.settings),
            )
        )
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


def _member_read(
    membership: ProjectMembership, user: User, custom: ProjectRole | None
) -> MemberRead:
    permissions = permissions_for(
        Role(membership.role),
        server_admin=False,
        custom=list(custom.permissions) if custom is not None else None,
    )
    scope = None if scope_is_empty(membership.scope) else MemberScope(**(membership.scope or {}))
    return MemberRead(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=Role(membership.role),
        role_id=custom.id if custom is not None else None,
        role_name=custom.name if custom is not None else BUILTIN_ROLE_LABELS[Role(membership.role)],
        permissions=sorted(permissions),
        scope=scope,
        created_at=membership.created_at,
    )


async def _custom_roles(
    session: AsyncSession, project_id: uuid.UUID, ids: set[uuid.UUID | None]
) -> dict[uuid.UUID, ProjectRole]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.scalars(
        select(ProjectRole).where(ProjectRole.project_id == project_id, ProjectRole.id.in_(wanted))
    )
    return {r.id: r for r in rows}


async def _check_role_id(
    session: AsyncSession, project_id: uuid.UUID, role_id: uuid.UUID | None
) -> ProjectRole | None:
    if role_id is None:
        return None
    role = await session.get(ProjectRole, role_id)
    if role is None or role.project_id != project_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown role for this project")
    return role


async def _check_scope(
    session: AsyncSession, project_id: uuid.UUID, scope: MemberScope | None
) -> dict[str, list[str]] | None:
    """The scope as stored, every id checked against the project: groups and entities of the
    project, devices assigned to it now or before. An empty scope is stored as null."""
    if scope is None or scope.empty:
        return None
    if scope.groups:
        found = set(
            await session.scalars(
                select(Group.id).where(Group.project_id == project_id, Group.id.in_(scope.groups))
            )
        )
        if found != set(scope.groups):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A group is not of this project"
            )
    if scope.entities:
        found = set(
            await session.scalars(
                select(Entity.id).where(
                    Entity.project_id == project_id, Entity.id.in_(scope.entities)
                )
            )
        )
        if found != set(scope.entities):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "An entity is not of this project"
            )
    if scope.devices:
        found = set(
            await session.scalars(
                select(DeviceProjectAssignment.device_id)
                .join(Device, Device.id == DeviceProjectAssignment.device_id)
                .where(
                    DeviceProjectAssignment.project_id == project_id,
                    DeviceProjectAssignment.device_id.in_(scope.devices),
                )
            )
        )
        if found != set(scope.devices):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A device was never assigned to this project"
            )
    return {
        "groups": [str(i) for i in scope.groups],
        "entities": [str(i) for i in scope.entities],
        "devices": [str(i) for i in scope.devices],
    }


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
    custom = await _custom_roles(session, context.project.id, {m.role_id for m in rows})
    return PageResponse(
        items=[_member_read(m, users[m.user_id], custom.get(m.role_id)) for m in rows],
        next_cursor=next_cursor,
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
    custom = await _check_role_id(session, context.project.id, body.role_id)
    scope = await _check_scope(session, context.project.id, body.scope)
    membership = ProjectMembership(
        user_id=user.id,
        project_id=context.project.id,
        role=body.role,
        role_id=custom.id if custom else None,
        scope=scope,
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
        details={
            "user_id": str(user.id),
            "role": body.role,
            "role_id": str(custom.id) if custom else None,
            "scope": scope,
        },
    )
    await session.commit()
    return _member_read(membership, user, custom)


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
    fields = body.model_dump(exclude_unset=True)
    changed: dict[str, object] = {}
    if "role" in fields and body.role is not None and membership.role != body.role:
        membership.role = body.role
        changed["role"] = body.role
    if "role_id" in fields:
        custom = await _check_role_id(session, context.project.id, body.role_id)
        new_id = custom.id if custom else None
        if membership.role_id != new_id:
            membership.role_id = new_id
            changed["role_id"] = str(new_id) if new_id else None
    if "scope" in fields:
        scope = await _check_scope(session, context.project.id, body.scope)
        if membership.scope != scope:
            membership.scope = scope
            changed["scope"] = scope
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
    custom_role = await _check_role_id(session, context.project.id, membership.role_id)
    return _member_read(membership, user, custom_role)


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
    role_id: uuid.UUID | None = None,
    scope: dict[str, list[str]] | None = None,
    memberships: list[dict[str, Any]] | None = None,
    project_names: list[str] | None = None,
) -> InvitationRead:
    """One invitation row and its mail. A project invitation names `project`; a server admin's
    invitation may carry `memberships` (checked by the caller) and the names of their projects
    for the mail (decision D190)."""
    invitation = Invitation(
        email=email.lower(),
        project_id=project.id if project else None,
        role=role,
        role_id=role_id,
        scope=scope,
        memberships=memberships,
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
        details={
            "email": invitation.email,
            "role": role,
            "role_id": str(role_id) if role_id else None,
            "scope": scope,
            "memberships": memberships,
            "server_admin": server_admin,
        },
    )
    await session.commit()
    sent = await get_mailer().send_invitation(
        invitation.email,
        invitation.token,
        project_names=[project.name] if project else list(project_names or []),
        invited_by=invited_by.full_name or invited_by.email,
    )
    _allowed, reason = allowed_recipient(invitation.email)
    return InvitationRead(
        **InvitationRead.model_validate(invitation).model_dump(
            exclude={"mail_sent", "mail_reason", "registration_link"}
        ),
        mail_sent=sent,
        mail_reason=None if sent else reason,
        registration_link=None
        if sent
        else f"{get_settings().public_url}/register?token={invitation.token}",
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
    custom = await _check_role_id(session, context.project.id, body.role_id)
    scope = await _check_scope(session, context.project.id, body.scope)
    return await create_invitation_row(
        session,
        email=body.email,
        project=context.project,
        role=body.role,
        server_admin=False,
        invited_by=context.user,
        role_id=custom.id if custom else None,
        scope=scope,
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


# Custom roles (decisions D185, D187)


def _role_read(role: ProjectRole, members: int) -> ProjectRoleRead:
    return ProjectRoleRead(
        id=role.id,
        project_id=role.project_id,
        name=role.name,
        description=role.description,
        permissions=sorted(role.permissions),
        members=members,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _permission_keys(keys: list[str]) -> list[str]:
    try:
        return sorted(normalise_permissions(keys))
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


@router.get("/{project_id}/roles", response_model=list[ProjectRoleRead])
async def list_roles(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectRoleRead]:
    """The project's custom roles with how many members hold each; the built-in roles come
    from `GET /permissions`."""
    roles = (
        await session.scalars(
            select(ProjectRole)
            .where(ProjectRole.project_id == context.project.id)
            .order_by(ProjectRole.name)
        )
    ).all()
    counts: dict[uuid.UUID | None, int] = {
        row[0]: int(row[1])
        for row in (
            await session.execute(
                select(ProjectMembership.role_id, func.count())
                .where(ProjectMembership.project_id == context.project.id)
                .group_by(ProjectMembership.role_id)
            )
        ).all()
    }
    return [_role_read(r, int(counts.get(r.id, 0))) for r in roles]


@router.post(
    "/{project_id}/roles", response_model=ProjectRoleRead, status_code=status.HTTP_201_CREATED
)
async def create_role(
    body: ProjectRoleCreate,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectRoleRead:
    role = ProjectRole(
        project_id=context.project.id,
        name=body.name.strip(),
        description=body.description,
        permissions=_permission_keys(body.permissions),
    )
    session.add(role)
    await flush_or_409(session, "Role")
    await record_audit(
        session,
        user=context.user,
        action="role.created",
        object_type="project_role",
        object_id=str(role.id),
        project_id=context.project.id,
        details={"name": role.name, "permissions": role.permissions},
    )
    await session.commit()
    return _role_read(role, 0)


@router.patch("/{project_id}/roles/{role_id}", response_model=ProjectRoleRead)
async def update_role(
    role_id: uuid.UUID,
    body: ProjectRoleUpdate,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ProjectRoleRead:
    role = await get_or_404(session, ProjectRole, role_id, "Role")
    if role.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    fields = body.model_dump(exclude_unset=True)
    changed: dict[str, object] = {}
    if "name" in fields and body.name is not None:
        role.name = body.name.strip()
        changed["name"] = role.name
    if "description" in fields:
        role.description = body.description
        changed["description"] = body.description
    if "permissions" in fields and body.permissions is not None:
        role.permissions = _permission_keys(body.permissions)
        changed["permissions"] = role.permissions
    await flush_or_409(session, "Role")
    await record_audit(
        session,
        user=context.user,
        action="role.updated",
        object_type="project_role",
        object_id=str(role.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    members = await session.scalar(
        select(func.count())
        .select_from(ProjectMembership)
        .where(ProjectMembership.role_id == role.id)
    )
    return _role_read(role, int(members or 0))


@router.delete("/{project_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.MEMBERS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    """A role in use cannot be deleted: give its members another role first."""
    role = await get_or_404(session, ProjectRole, role_id, "Role")
    if role.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    members = await session.scalar(
        select(func.count())
        .select_from(ProjectMembership)
        .where(ProjectMembership.role_id == role.id)
    )
    if members:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{members} member(s) hold this role")
    await session.delete(role)
    await record_audit(
        session,
        user=context.user,
        action="role.deleted",
        object_type="project_role",
        object_id=str(role.id),
        project_id=context.project.id,
        details={"name": role.name},
    )
    await session.commit()
