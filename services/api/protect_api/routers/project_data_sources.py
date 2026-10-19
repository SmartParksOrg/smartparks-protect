"""The data sources a project's members may name (decision D337): a project admin links an
identity, a DevEUI on a network, to a device of the project and needs the sources by name; the
sources' settings and credentials stay with the server admin under `/data-sources`."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import ProjectContext, require_permission
from protect_api.schemas.domain import DataSourceBrief
from shared.database import get_session
from shared.models import DataSource
from shared.permissions import Permission

router = APIRouter(prefix="/projects/{project_id}/data-sources", tags=["data sources"])


@router.get("", response_model=list[DataSourceBrief])
async def list_project_data_sources(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[DataSourceBrief]:
    """Every data source of the server by name and adapter, for a member of the project: the
    choice when an identity is linked to a device of the project. Nothing of a source's
    settings or credentials."""
    rows = (await session.scalars(select(DataSource).order_by(DataSource.name))).all()
    return [
        DataSourceBrief(id=r.id, name=r.name, adapter_key=r.adapter_key, enabled=r.enabled)
        for r in rows
    ]
