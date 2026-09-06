"""Entity groups: folders of entities inside a project (decision D98, ADR 0020)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
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
    """Two levels (decision D98): a parent is a top-level group of this project, and a group
    that has subgroups cannot become a subgroup itself."""
    if parent_id is None:
        return
    if group is not None and parent_id == group.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A group cannot be its own parent"
        )
    parent = await project_group(session, context, parent_id)
    if parent.parent_id is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Groups are two levels deep: the parent must be a top-level group",
        )
    if group is not None:
        children = await session.scalar(
            select(func.count()).select_from(Group).where(Group.parent_id == group.id)
        )
        if children:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A group with subgroups cannot become a subgroup; move its subgroups first",
            )


def group_read(group: Group, entity_count: int = 0) -> EntityGroupRead:
    read = EntityGroupRead.model_validate(group)
    read.entity_count = entity_count
    return read


@router.get("", response_model=list[EntityGroupRead])
async def list_groups(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[EntityGroupRead]:
    """Every group of the project with the number of entities directly in it, parents first,
    then by sort order and name. Small enough to never page."""
    counts = {
        group_id: count
        for group_id, count in (
            await session.execute(
                select(Entity.group_id, func.count())
                .where(Entity.project_id == context.project.id, Entity.group_id.is_not(None))
                .group_by(Entity.group_id)
            )
        ).all()
    }
    groups = (
        await session.scalars(
            select(Group)
            .where(Group.project_id == context.project.id)
            .order_by(Group.parent_id.is_not(None), Group.sort_order, Group.name)
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
    """Deleting a group leaves its entities ungrouped and removes its subgroups the same way;
    the entities themselves stay."""
    group = await project_group(session, context, group_id)
    subgroup_ids = list(
        (await session.scalars(select(Group.id).where(Group.parent_id == group.id))).all()
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
