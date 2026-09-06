"""Site-wide search (decision D99): one bounded endpoint over what the caller may see, behind
the command palette. Lists keep their own search boxes; this one answers "where is X"."""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Row, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from protect_api.auth.users import current_active_user
from protect_api.deps import accessible_project_ids
from shared.database import get_session
from shared.models import (
    DataSource,
    DataSourceProjectScope,
    Device,
    DeviceProjectAssignment,
    Entity,
    ExternalIdentity,
    Feature,
    Gateway,
    Project,
    User,
)
from shared.timeutil import utc_now

router = APIRouter(prefix="/search", tags=["search"])

MAX_PER_KIND = 50


class SearchHit(BaseModel):
    id: uuid.UUID
    name: str
    subtitle: str | None = None
    project_id: uuid.UUID | None = Field(
        default=None, description="The project the hit belongs to, for the link"
    )


class SearchResponse(BaseModel):
    query: str
    entities: list[SearchHit]
    devices: list[SearchHit]
    features: list[SearchHit]
    gateways: list[SearchHit]
    data_sources: list[SearchHit] = Field(
        default_factory=list, description="Server admins only; empty for everyone else"
    )
    projects: list[SearchHit]


def _in_projects(
    statement: Select[Any],
    column: InstrumentedAttribute[uuid.UUID],
    projects: list[uuid.UUID] | None,
) -> Select[Any]:
    return statement if projects is None else statement.where(column.in_(projects))


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(min_length=1, max_length=200, description="Name contains, case-insensitive"),
    limit: int = Query(10, ge=1, le=MAX_PER_KIND, description="Per kind"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    """Entities, devices (by name, serial or external id), features, gateways, data sources
    (server admins) and projects whose name contains `q`, inside what the caller may see."""
    pattern = f"%{q.strip()}%"
    projects = await accessible_project_ids(user, session)
    now = utc_now()

    project_rows = (
        await session.execute(
            _in_projects(
                select(Project.id, Project.name, Project.description)
                .where(Project.name.ilike(pattern))
                .order_by(Project.name),
                Project.id,
                projects,
            ).limit(limit)
        )
    ).all()
    entity_rows = (
        await session.execute(
            _in_projects(
                select(Entity.id, Entity.name, Entity.project_id)
                .where(Entity.name.ilike(pattern))
                .order_by(Entity.name),
                Entity.project_id,
                projects,
            ).limit(limit)
        )
    ).all()
    feature_rows = (
        await session.execute(
            _in_projects(
                select(Feature.id, Feature.name, Feature.feature_type, Feature.project_id)
                .where(Feature.name.ilike(pattern))
                .order_by(Feature.name),
                Feature.project_id,
                projects,
            ).limit(limit)
        )
    ).all()

    identity_match = (
        select(ExternalIdentity.device_id)
        .where(ExternalIdentity.external_id.ilike(pattern))
        .scalar_subquery()
    )
    current = (
        select(DeviceProjectAssignment.device_id, DeviceProjectAssignment.project_id)
        .where(DeviceProjectAssignment.validity.op("@>")(now))
        .subquery()
    )
    device_statement = (
        select(Device.id, Device.name, Device.serial_number, current.c.project_id)
        .outerjoin(current, current.c.device_id == Device.id)
        .where(
            or_(
                Device.name.ilike(pattern),
                Device.serial_number.ilike(pattern),
                Device.id.in_(identity_match),
            )
        )
        .order_by(Device.name)
    )
    if projects is not None:
        device_statement = device_statement.where(current.c.project_id.in_(projects))
    device_rows = (await session.execute(device_statement.limit(limit))).all()

    gateway_statement = (
        select(
            Gateway.id, Gateway.external_id, Gateway.name, Gateway.name_override, DataSource.name
        )
        .join(DataSource, DataSource.id == Gateway.data_source_id)
        .where(
            or_(
                Gateway.external_id.ilike(pattern),
                Gateway.name.ilike(pattern),
                Gateway.name_override.ilike(pattern),
            )
        )
        .order_by(Gateway.external_id)
    )
    if projects is not None:
        scoped = select(DataSourceProjectScope.data_source_id).where(
            DataSourceProjectScope.project_id.in_(projects)
        )
        gateway_statement = gateway_statement.where(Gateway.data_source_id.in_(scoped))
    gateway_rows = (await session.execute(gateway_statement.limit(limit))).all()

    source_rows: Sequence[Row[Any]] = []
    if user.is_superuser:
        source_rows = (
            await session.execute(
                select(DataSource.id, DataSource.name, DataSource.adapter_key)
                .where(DataSource.name.ilike(pattern))
                .order_by(DataSource.name)
                .limit(limit)
            )
        ).all()

    wanted = {r.project_id for r in entity_rows} | {r.project_id for r in feature_rows}
    wanted |= {r.project_id for r in device_rows if r.project_id}
    names = {
        pid: name
        for pid, name in (
            await session.execute(select(Project.id, Project.name).where(Project.id.in_(wanted)))
        ).all()
    }
    return SearchResponse(
        query=q,
        entities=[
            SearchHit(
                id=r.id, name=r.name, subtitle=names.get(r.project_id), project_id=r.project_id
            )
            for r in entity_rows
        ],
        devices=[
            SearchHit(
                id=r.id,
                name=r.name,
                subtitle=", ".join(
                    x
                    for x in (r.serial_number, names.get(r.project_id) if r.project_id else None)
                    if x
                )
                or None,
                project_id=r.project_id,
            )
            for r in device_rows
        ],
        features=[
            SearchHit(
                id=r.id,
                name=r.name,
                subtitle=f"{r.feature_type}, {names.get(r.project_id, '')}".rstrip(", "),
                project_id=r.project_id,
            )
            for r in feature_rows
        ],
        gateways=[
            SearchHit(id=r[0], name=r[3] or r[2] or r[1], subtitle=f"{r[1]}, {r[4]}")
            for r in gateway_rows
        ],
        data_sources=[SearchHit(id=r.id, name=r.name, subtitle=r.adapter_key) for r in source_rows],
        projects=[
            SearchHit(id=r.id, name=r.name, subtitle=r.description, project_id=r.id)
            for r in project_rows
        ],
    )
