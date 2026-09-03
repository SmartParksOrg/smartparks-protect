"""Data sources (external platform accounts) and their external identities. Server admin only in
phase 1; credentials are written, never read back."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.domain import (
    DataSourceCreate,
    DataSourceRead,
    DataSourceUpdate,
    ExternalIdentityCreate,
    ExternalIdentityRead,
    ExternalIdentityUpdate,
)
from shared.config import get_settings
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.transports.http import hash_token, new_webhook_token
from shared.database import get_session
from shared.models import (
    DataSource,
    DataSourceProjectScope,
    Device,
    ExternalIdentity,
    Project,
    User,
)
from shared.secrets import encrypt_json

router = APIRouter(
    prefix="/data-sources", tags=["data sources"], dependencies=[Depends(require_server_admin)]
)


async def _read(session: AsyncSession, source: DataSource) -> DataSourceRead:
    scopes = await session.scalars(
        select(DataSourceProjectScope.project_id).where(
            DataSourceProjectScope.data_source_id == source.id
        )
    )
    data = DataSourceRead.model_validate(source)
    data.has_credentials = source.credentials_encrypted is not None
    data.has_webhook_token = source.webhook_token_hash is not None
    if source.webhook_token_hash is not None:
        data.webhook_url = f"{get_settings().public_url}/api/v1/ingest/http/{source.id}"
    data.project_ids = list(scopes)
    return data


def _adapter_defaults(body: DataSourceCreate) -> dict[str, Any]:
    adapter = ADAPTERS.get(body.adapter_key)
    if adapter is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown adapter {body.adapter_key!r}; known: {sorted(ADAPTERS)}",
        )
    values = body.model_dump(exclude={"credentials", "project_ids"})
    if not body.capabilities:
        values["capabilities"] = adapter.default_capabilities.model_dump()
    if not body.link_templates:
        values["link_templates"] = dict(adapter.default_link_templates)
    return values


async def _set_scopes(
    session: AsyncSession, source: DataSource, project_ids: list[uuid.UUID]
) -> None:
    for project_id in project_ids:
        await get_or_404(session, Project, project_id, "Project")
    existing = (
        await session.scalars(
            select(DataSourceProjectScope).where(DataSourceProjectScope.data_source_id == source.id)
        )
    ).all()
    for scope in existing:
        if scope.project_id not in project_ids:
            await session.delete(scope)
    have = {scope.project_id for scope in existing}
    for project_id in project_ids:
        if project_id not in have:
            session.add(DataSourceProjectScope(data_source_id=source.id, project_id=project_id))


@router.get("", response_model=PageResponse[DataSourceRead])
async def list_data_sources(
    page: Page = Depends(page), session: AsyncSession = Depends(get_session)
) -> PageResponse[DataSourceRead]:
    rows, next_cursor = await paginate(session, DataSource.id, select(DataSource), page)
    return PageResponse(items=[await _read(session, r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=DataSourceRead, status_code=status.HTTP_201_CREATED)
async def create_data_source(
    body: DataSourceCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DataSourceRead:
    """HTTP push sources get a bearer token that is returned once, in this response only."""
    values = _adapter_defaults(body)
    token = new_webhook_token() if body.adapter_key == "generic_http" else None
    source = DataSource(
        credentials_encrypted=encrypt_json(body.credentials) if body.credentials else None,
        webhook_token_hash=hash_token(token) if token else None,
        **values,
    )
    session.add(source)
    await flush_or_409(session, "Data source")
    await _set_scopes(session, source, body.project_ids)
    await record_audit(
        session,
        user=user,
        action="data_source.created",
        object_type="data_source",
        object_id=str(source.id),
        details={"name": source.name, "adapter_key": source.adapter_key},
    )
    await session.commit()
    data = await _read(session, source)
    data.webhook_token = token
    return data


@router.post("/{data_source_id}/webhook-token", response_model=DataSourceRead)
async def rotate_webhook_token(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DataSourceRead:
    """Issue a new bearer token for an HTTP push source. The old one stops working at once."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    token = new_webhook_token()
    source.webhook_token_hash = hash_token(token)
    await record_audit(
        session,
        user=user,
        action="data_source.webhook_token_rotated",
        object_type="data_source",
        object_id=str(source.id),
    )
    await session.commit()
    data = await _read(session, source)
    data.webhook_token = token
    return data


@router.get("/{data_source_id}", response_model=DataSourceRead)
async def get_data_source(
    data_source_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DataSourceRead:
    return await _read(
        session, await get_or_404(session, DataSource, data_source_id, "Data source")
    )


@router.patch("/{data_source_id}", response_model=DataSourceRead)
async def update_data_source(
    data_source_id: uuid.UUID,
    body: DataSourceUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DataSourceRead:
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    changed = apply_patch(source, body, exclude={"credentials", "project_ids"})
    if body.credentials is not None:
        source.credentials_encrypted = encrypt_json(body.credentials)
        changed["credentials"] = "replaced"
    if body.project_ids is not None:
        await _set_scopes(session, source, body.project_ids)
        changed["project_ids"] = [str(p) for p in body.project_ids]
    await flush_or_409(session, "Data source")
    await record_audit(
        session,
        user=user,
        action="data_source.updated",
        object_type="data_source",
        object_id=str(source.id),
        details=changed,
    )
    await session.commit()
    return await _read(session, source)


@router.delete("/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_source(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    await session.delete(source)
    await flush_or_409(session, "Data source")
    await record_audit(
        session,
        user=user,
        action="data_source.deleted",
        object_type="data_source",
        object_id=str(source.id),
        details={"name": source.name},
    )
    await session.commit()


@router.get("/{data_source_id}/identities", response_model=PageResponse[ExternalIdentityRead])
async def list_identities(
    data_source_id: uuid.UUID,
    page: Page = Depends(page),
    unresolved: bool = False,
    session: AsyncSession = Depends(get_session),
) -> PageResponse[ExternalIdentityRead]:
    await get_or_404(session, DataSource, data_source_id, "Data source")
    statement = select(ExternalIdentity).where(ExternalIdentity.data_source_id == data_source_id)
    if unresolved:
        statement = statement.where(
            ExternalIdentity.device_id.is_(None), ExternalIdentity.ignored.is_(False)
        )
    rows, next_cursor = await paginate(session, ExternalIdentity.id, statement, page)
    return PageResponse(
        items=[ExternalIdentityRead.model_validate(r) for r in rows], next_cursor=next_cursor
    )


@router.post(
    "/{data_source_id}/identities",
    response_model=ExternalIdentityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_identity(
    data_source_id: uuid.UUID,
    body: ExternalIdentityCreate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> ExternalIdentity:
    if body.data_source_id != data_source_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "data_source_id does not match the path"
        )
    await get_or_404(session, DataSource, data_source_id, "Data source")
    identity = ExternalIdentity(**body.model_dump())
    session.add(identity)
    await flush_or_409(session, "External identity")
    await record_audit(
        session,
        user=user,
        action="external_identity.created",
        object_type="external_identity",
        object_id=str(identity.id),
        details={"external_id": identity.external_id},
    )
    await session.commit()
    return identity


@router.patch("/{data_source_id}/identities/{identity_id}", response_model=ExternalIdentityRead)
async def update_identity(
    data_source_id: uuid.UUID,
    identity_id: uuid.UUID,
    body: ExternalIdentityUpdate,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> ExternalIdentity:
    """Link an identity to a device, change its type, or ignore it."""
    identity = await get_or_404(session, ExternalIdentity, identity_id, "External identity")
    if identity.data_source_id != data_source_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "External identity not found")
    if body.device_id is not None:
        await get_or_404(session, Device, body.device_id, "Device")
    changed = apply_patch(identity, body)
    await flush_or_409(session, "External identity")
    await record_audit(
        session,
        user=user,
        action="external_identity.updated",
        object_type="external_identity",
        object_id=str(identity.id),
        details=changed,
    )
    await session.commit()
    return identity
