"""Access control dependencies.

- `require_server_admin`: the user flag `is_superuser`.
- `require_project_role(role)`: membership in the `{project_id}` of the path with at least that
  role. Server admins pass everywhere.
- `require_permission(key)`: the fine-grained variant; the role's permission set must contain it.

Every dependency returns a `ProjectContext` so endpoints know the caller's role and permissions
without a second query. A project that does not exist is a 404 for everyone, so that the
existence of projects is not leaked through 403 versus 404.
"""

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.auth.users import current_active_user
from shared.database import get_session
from shared.enums import Role
from shared.models import Project, ProjectMembership, User
from shared.permissions import Permission, permissions_for

ROLE_RANK = {Role.PROJECT_VIEWER: 1, Role.PROJECT_ADMIN: 2}


@dataclass(frozen=True, slots=True)
class ProjectContext:
    user: User
    project: Project
    role: Role | None
    permissions: frozenset[Permission]

    @property
    def is_server_admin(self) -> bool:
        return self.user.is_superuser


ALL_PROJECTS = "all"


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """One project, or every project for a server admin (decision D115, the reserved project
    id `all`). Endpoints that support the scope take this instead of `ProjectContext` and
    filter with `where`; every other `/projects/{project_id}` endpoint keeps a UUID parameter,
    so `all` is a 422 there."""

    user: User
    project: Project | None
    role: Role | None
    permissions: frozenset[Permission]

    @property
    def is_all(self) -> bool:
        return self.project is None

    @property
    def is_server_admin(self) -> bool:
        return self.user.is_superuser

    @property
    def project_id(self) -> uuid.UUID | None:
        return None if self.project is None else self.project.id

    def where(self, column: Any, *, unassigned: bool = False) -> Any:
        """The project filter: one project, or any project at all (never the system scope of
        events without a project). With `unassigned`, the all scope takes data that belongs to
        no project as well (decision D120: a server admin sees inventory devices and their
        positions until they are attributed, architecture 28.11)."""
        if self.project is not None:
            return column == self.project.id
        return true() if unassigned else column.is_not(None)


async def get_scope_context(
    project_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ScopeContext:
    if project_id == ALL_PROJECTS:
        if not user.is_superuser:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "All projects is for server admins")
        return ScopeContext(
            user=user, project=None, role=None, permissions=permissions_for(None, server_admin=True)
        )
    try:
        parsed = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "project_id must be a UUID or all"
        ) from None
    context = await get_project_context(parsed, user, session)
    return ScopeContext(
        user=context.user,
        project=context.project,
        role=context.role,
        permissions=context.permissions,
    )


def require_scope_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, ScopeContext]]:
    async def dependency(context: ScopeContext = Depends(get_scope_context)) -> ScopeContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {permission} required")
        return context

    return dependency


async def require_server_admin(user: User = Depends(current_active_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Server admin access required")
    return user


async def get_project_context(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectContext:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    role_value = await session.scalar(
        select(ProjectMembership.role).where(
            ProjectMembership.user_id == user.id, ProjectMembership.project_id == project_id
        )
    )
    role = Role(role_value) if role_value is not None else None
    if role is None and not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this project")
    return ProjectContext(
        user=user,
        project=project,
        role=role,
        permissions=permissions_for(role, server_admin=user.is_superuser),
    )


def require_project_role(
    minimum: Role,
) -> Callable[..., Coroutine[Any, Any, ProjectContext]]:
    async def dependency(context: ProjectContext = Depends(get_project_context)) -> ProjectContext:
        if context.is_server_admin:
            return context
        if context.role is None or ROLE_RANK[context.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role {minimum} required")
        return context

    return dependency


def require_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, ProjectContext]]:
    async def dependency(context: ProjectContext = Depends(get_project_context)) -> ProjectContext:
        if permission not in context.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permission {permission} required")
        return context

    return dependency


async def accessible_project_ids(user: User, session: AsyncSession) -> list[uuid.UUID] | None:
    """Projects the user may read. None means all (server admin)."""
    if user.is_superuser:
        return None
    rows = await session.scalars(
        select(ProjectMembership.project_id).where(ProjectMembership.user_id == user.id)
    )
    return list(rows)
