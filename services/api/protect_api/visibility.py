"""What a member may see (decision D186): the membership's scope, resolved to the entities and
devices it covers, and the SQL filters every project read applies. A scope names groups (with
everything below them), single entities and single devices; an entity in scope brings the
device tracking it today; nothing outside the scope exists for that member. No scope means the
whole project.
"""

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement, Select

from shared.models import DeviceEntityAssignment, Entity, Group, ProjectMembership, User
from shared.timeutil import utc_now

SCOPE_KEYS = ("groups", "entities", "devices")


def group_and_subgroups(group_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """The group's id and the ids of every group below it, however deep, for filters on a
    parent group (a recursive query)."""
    tree = select(Group.id).where(Group.id == group_id).cte("group_tree", recursive=True)
    below = aliased(Group)
    tree = tree.union_all(select(below.id).where(below.parent_id == tree.c.id))
    return select(tree.c.id)


def groups_and_subgroups(group_ids: list[uuid.UUID]) -> Select[tuple[uuid.UUID]]:
    """The same for several groups at once."""
    tree = select(Group.id).where(Group.id.in_(group_ids)).cte("groups_tree", recursive=True)
    below = aliased(Group)
    tree = tree.union_all(select(below.id).where(below.parent_id == tree.c.id))
    return select(tree.c.id)


@dataclass(frozen=True, slots=True)
class Visibility:
    """The resolved scope: None in a field means no limit on that kind."""

    group_ids: frozenset[uuid.UUID] | None = None
    entity_ids: frozenset[uuid.UUID] | None = None
    device_ids: frozenset[uuid.UUID] | None = None

    @property
    def limited(self) -> bool:
        return self.entity_ids is not None

    def entities(self, column: Any) -> ColumnElement[bool]:
        """Rows whose entity is in scope."""
        if self.entity_ids is None:
            return true()
        return cast(ColumnElement[bool], column.in_(self.entity_ids))

    def devices(self, column: Any) -> ColumnElement[bool]:
        """Rows whose device is in scope."""
        if self.device_ids is None:
            return true()
        return cast(ColumnElement[bool], column.in_(self.device_ids))

    def rows(self, entity_column: Any, device_column: Any) -> ColumnElement[bool]:
        """Records with an entity or a device: visible when either is in scope."""
        if not self.limited:
            return true()
        return or_(
            entity_column.in_(self.entity_ids or ()),
            device_column.in_(self.device_ids or ()),
        )

    def entity_visible(self, entity_id: uuid.UUID | None) -> bool:
        return self.entity_ids is None or (entity_id is not None and entity_id in self.entity_ids)

    def device_visible(self, device_id: uuid.UUID | None) -> bool:
        return self.device_ids is None or (device_id is not None and device_id in self.device_ids)

    def narrow(
        self, entities: list[uuid.UUID], devices: list[uuid.UUID]
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        """A caller's own selection cut to the scope. A selection (either list) keeps only
        what is in scope, so asking for something outside it yields nothing; no selection at
        all means everything in scope, so both lists become the scope itself."""
        if not self.limited:
            return entities, devices
        if not entities and not devices:
            return sorted(self.entity_ids or (), key=str), sorted(self.device_ids or (), key=str)
        return (
            [i for i in entities if i in (self.entity_ids or ())],
            [i for i in devices if i in (self.device_ids or ())],
        )


EVERYTHING = Visibility()


def _ids(scope: dict[str, Any] | None, key: str) -> list[uuid.UUID]:
    values = (scope or {}).get(key) or []
    out: list[uuid.UUID] = []
    for value in values:
        try:
            out.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return out


def scope_is_empty(scope: dict[str, Any] | None) -> bool:
    return not scope or not any(_ids(scope, key) for key in SCOPE_KEYS)


async def resolve_visibility(
    session: AsyncSession, project_id: uuid.UUID, scope: dict[str, Any] | None
) -> Visibility:
    """The scope as concrete ids, inside the project: the named groups with everything below
    them, the entities in those groups and the single entities, the single devices and the
    devices tracking a visible entity today."""
    if scope_is_empty(scope):
        return EVERYTHING
    group_ids: set[uuid.UUID] = set()
    wanted_groups = _ids(scope, "groups")
    if wanted_groups:
        group_ids = set(
            await session.scalars(
                select(Group.id).where(
                    Group.project_id == project_id,
                    Group.id.in_(groups_and_subgroups(wanted_groups)),
                )
            )
        )
    entity_ids: set[uuid.UUID] = set()
    wanted_entities = _ids(scope, "entities")
    if wanted_entities or group_ids:
        conditions = []
        if wanted_entities:
            conditions.append(Entity.id.in_(wanted_entities))
        if group_ids:
            conditions.append(Entity.group_id.in_(group_ids))
        entity_ids = set(
            await session.scalars(
                select(Entity.id).where(Entity.project_id == project_id, or_(*conditions))
            )
        )
    device_ids: set[uuid.UUID] = set(_ids(scope, "devices"))
    if entity_ids:
        device_ids |= set(
            await session.scalars(
                select(DeviceEntityAssignment.device_id).where(
                    DeviceEntityAssignment.entity_id.in_(entity_ids),
                    DeviceEntityAssignment.validity.op("@>")(utc_now()),
                )
            )
        )
    return Visibility(
        group_ids=frozenset(group_ids),
        entity_ids=frozenset(entity_ids),
        device_ids=frozenset(device_ids),
    )


async def visibility_for(session: AsyncSession, user: User, project_id: uuid.UUID) -> Visibility:
    """The caller's visibility in a project, for endpoints that are not under the project
    route: everything for a server admin or an unlimited member."""
    if user.is_superuser:
        return EVERYTHING
    scope = await session.scalar(
        select(ProjectMembership.scope).where(
            ProjectMembership.user_id == user.id, ProjectMembership.project_id == project_id
        )
    )
    return await resolve_visibility(session, project_id, scope)
