"""Entity groups: folders of entities inside a project (decision D98, ADR 0020)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import (
    ProjectContext,
    ScopeContext,
    require_permission,
    require_scope_permission,
)
from protect_api.routers.entities import group_and_subgroups
from protect_api.schemas.domain import EntityGroupCreate, EntityGroupRead, EntityGroupUpdate
from shared.database import get_session
from shared.models import Entity, Group
from shared.permissions import Permission

router = APIRouter(prefix="/projects/{project_id}/groups", tags=["entities"])


async def project_group(
    session: AsyncSession, context: ProjectContext, group_id: uuid.UUID
) -> Group:
    group = await get_or_404(session, Group, group_id, "Group")
    if group.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


async def check_parent(
    session: AsyncSession,
    context: ProjectContext,
    parent_id: uuid.UUID | None,
    group: Group | None,
) -> None:
    """Groups nest as deep as needed (decision D98, amended): the parent is a group of this
    project and not the group itself or one below it, so the tree stays a tree."""
    if parent_id is None:
        return
    await project_group(session, context, parent_id)
    if group is None:
        return
    below = set((await session.scalars(group_and_subgroups(group.id))).all())
    if parent_id in below:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A group cannot move into itself or into one of its own subgroups",
        )


def group_read(group: Group, entity_count: int = 0) -> EntityGroupRead:
    read = EntityGroupRead.model_validate(group)
    read.entity_count = entity_count
    return read


@router.get("", response_model=list[EntityGroupRead])
async def list_groups(
    context: ScopeContext = Depends(require_scope_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[EntityGroupRead]:
    """Every group of the project with the number of entities directly in it, by sort order
    and name; the reader builds the tree from `parent_id`. Small enough to never page."""
    counts = {
        group_id: count
        for group_id, count in (
            await session.execute(
                select(Entity.group_id, func.count())
                .where(context.where(Entity.project_id), Entity.group_id.is_not(None))
                .group_by(Entity.group_id)
            )
        ).all()
    }
    groups = (
        await session.scalars(
            select(Group)
            .where(context.where(Group.project_id))
            .order_by(Group.sort_order, Group.name)
        )
    ).all()
    return [group_read(g, int(counts.get(g.id, 0))) for g in groups]


@router.post("", response_model=EntityGroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: EntityGroupCreate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityGroupRead:
    await check_parent(session, context, body.parent_id, None)
    group = Group(project_id=context.project.id, **body.model_dump())
    session.add(group)
    await flush_or_409(session, "Group")
    await record_audit(
        session,
        user=context.user,
        action="entity_group.created",
        object_type="entity_group",
        object_id=str(group.id),
        project_id=context.project.id,
        details={"name": group.name, "parent_id": str(body.parent_id) if body.parent_id else None},
    )
    await session.commit()
    return group_read(group)


@router.patch("/{group_id}", response_model=EntityGroupRead)
async def update_group(
    group_id: uuid.UUID,
    body: EntityGroupUpdate,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> EntityGroupRead:
    group = await project_group(session, context, group_id)
    if "parent_id" in body.model_fields_set:
        await check_parent(session, context, body.parent_id, group)
    changed = apply_patch(group, body)
    await flush_or_409(session, "Group")
    await record_audit(
        session,
        user=context.user,
        action="entity_group.updated",
        object_type="entity_group",
        object_id=str(group.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    count = await session.scalar(
        select(func.count()).select_from(Entity).where(Entity.group_id == group.id)
    )
    return group_read(group, int(count or 0))


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.ENTITIES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Deleting a group leaves its entities ungrouped and removes every group below it the
    same way; the entities themselves stay."""
    group = await project_group(session, context, group_id)
    tree = list((await session.scalars(group_and_subgroups(group.id))).all())
    subgroup_ids = [g for g in tree if g != group.id]
    ungrouped = await session.scalar(
        select(func.count()).select_from(Entity).where(Entity.group_id.in_(tree))
    )
    ungrouped = await session.scalar(
        select(func.count())
        .select_from(Entity)
        .where(Entity.group_id.in_([group.id, *subgroup_ids]))
    )
    await session.delete(group)
    await flush_or_409(session, "Group")
    await record_audit(
        session,
        user=context.user,
        action="entity_group.deleted",
        object_type="entity_group",
        object_id=str(group.id),
        project_id=context.project.id,
        details={
            "name": group.name,
            "subgroups": len(subgroup_ids),
            "entities_ungrouped": int(ungrouped or 0),
        },
    )
    await session.commit()
