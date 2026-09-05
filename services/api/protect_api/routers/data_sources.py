"""Data sources (external platform accounts) and their external identities. Server admin only in
phase 1; credentials are written, never read back."""

import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
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
from protect_api.schemas.integrations import CursorReset, GatewaySyncResult
from shared.config import get_settings
from shared.connectivity.registry import ADAPTERS, channels_of, describe_adapter
from shared.connectivity.state import read_api_test, read_connector, report_api_test
from shared.connectivity.transports.http import hash_token, new_webhook_token
from shared.database import get_session
from shared.ingest import apply_gateway_update, data_source_context
from shared.models import (
    DataSource,
    DataSourceCursor,
    DataSourceProjectScope,
    Device,
    ExternalIdentity,
    Project,
    SourceEvent,
    User,
)
from shared.secrets import encrypt_json
from shared.timeutil import utc_now
from shared.trace import ApplicationError

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
        data.webhook_token_in_query = bool(
            getattr(ADAPTERS.get(source.adapter_key), "webhook_token_in_query", False)
        )
    data.builtin = bool(getattr(ADAPTERS.get(source.adapter_key), "builtin", False))
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


@router.get("/adapters", response_model=list[dict[str, Any]])
async def list_adapters() -> list[dict[str, Any]]:
    """Every registered adapter with its configuration shape, so the frontend and API clients
    build data sources without knowing any provider by name."""
    return [describe_adapter(adapter) for adapter in ADAPTERS.values()]


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
    token = new_webhook_token() if getattr(ADAPTERS[body.adapter_key], "push", False) else None
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
    if token and data.webhook_token_in_query and data.webhook_url:
        data.webhook_url = f"{data.webhook_url}?token={token}"
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
    if data.webhook_token_in_query and data.webhook_url:
        data.webhook_url = f"{data.webhook_url}?token={token}"
    return data


@router.get("/{data_source_id}/cursor", response_model=dict[str, Any])
async def get_cursor(
    data_source_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Where a polling connector is."""
    await get_or_404(session, DataSource, data_source_id, "Data source")
    row = await session.get(DataSourceCursor, data_source_id)
    return dict(row.state) if row is not None else {}


@router.post("/{data_source_id}/cursor", response_model=dict[str, Any])
async def reset_cursor(
    data_source_id: uuid.UUID,
    body: CursorReset,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Rescan from an instant (or from the adapter's default window when empty). The
    connector picks the new cursor up at its next poll; records it already stored are
    deduplicated by their canonical keys."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    adapter = ADAPTERS.get(source.adapter_key)
    if adapter is None or not getattr(adapter, "polling", False):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "this data source's adapter does not poll"
        )
    state: dict[str, Any] = {
        "since": body.since.isoformat() if body.since else None,
        "reset_at": utc_now().isoformat(),
        "reset_by": user.email,
    }
    await session.execute(
        insert(DataSourceCursor)
        .values(data_source_id=source.id, state=state, updated_at=utc_now())
        .on_conflict_do_update(
            index_elements=[DataSourceCursor.data_source_id],
            set_={"state": state, "updated_at": utc_now()},
        )
    )
    await record_audit(
        session,
        user=user,
        action="data_source.cursor_reset",
        object_type="data_source",
        object_id=str(source.id),
        details=state,
    )
    await session.commit()
    return state


class ConnectionTestResult(BaseModel):
    ok: bool
    detail: str
    result: dict[str, Any] = Field(default_factory=dict)


class DeviceSyncResult(BaseModel):
    listed: int
    created: int
    updated: int


def _management(source: DataSource) -> Any:
    adapter = ADAPTERS.get(source.adapter_key)
    factory = getattr(adapter, "management_connector", None)
    return factory(data_source_context(source)) if factory else None


class ChannelStatus(BaseModel):
    key: str
    label: str
    direction: str
    purpose: str
    hint: str | None = None
    configured: bool
    missing: list[str] = Field(default_factory=list)
    state: str  # off, waiting, ok, connected, reconnecting, error, stopped, untested
    detail: str | None = None
    last_at: datetime | None = None
    count_24h: int = 0


class DataSourceStatus(BaseModel):
    channels: list[ChannelStatus]
    effective_capabilities: dict[str, bool]
    limited_capabilities: list[str] = Field(
        default_factory=list, description="Declared capabilities an unconfigured channel holds back"
    )


CHANNEL_METHODS: dict[str, tuple[str, ...]] = {
    "http": ("webhook",),
    "mqtt": ("mqtt",),
    "stream": ("websocket", "mqtt"),
    "poll": ("polling",),
}


@router.get("/{data_source_id}/status", response_model=DataSourceStatus)
async def data_source_status(
    data_source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DataSourceStatus:
    """Per channel: configured or not (and what is missing), and whether it works, from the
    messages received, the connector's connection state and the last API answer."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    adapter = ADAPTERS.get(source.adapter_key)
    credentials = data_source_context(source).credentials
    config = source.config or {}
    since = utc_now() - timedelta(hours=24)
    channels: list[ChannelStatus] = []
    limited: set[str] = set()
    for channel in channels_of(adapter) if adapter else []:
        missing = [
            k for k in channel.get("config_keys", []) if not str(config.get(k) or "").strip()
        ]
        missing += [k for k in channel.get("credential_keys", []) if not credentials.get(k)]
        configured = not missing
        state, detail, last_at, count = "off", None, None, 0
        if configured and channel["direction"] == "in":
            methods = CHANNEL_METHODS.get(str(channel["key"]), ())
            if methods:
                row = (
                    await session.execute(
                        select(func.count(), func.max(SourceEvent.ingested_at)).where(
                            SourceEvent.data_source_id == source.id,
                            SourceEvent.ingested_at >= since,
                            SourceEvent.ingestion_method.in_(methods),
                        )
                    )
                ).one()
                count, last_at = int(row[0] or 0), row[1]
            connection = (
                await read_connector(source.id) if channel["key"] in ("mqtt", "stream") else None
            )
            if connection is not None:
                state = str(connection.get("status") or "unknown")
                detail = connection.get("detail")
            elif count:
                state, detail = "ok", f"{count} messages in the last 24 hours"
            else:
                state, detail = "waiting", "configured, nothing received in the last 24 hours"
            if connection is not None and count and state == "connected":
                detail = f"{detail}; {count} messages in the last 24 hours"
        elif configured:
            test = await read_api_test(source.id)
            if test is None:
                state, detail = "untested", "configured; run Test connection"
            else:
                state = "ok" if test.get("ok") else "error"
                detail = str(test.get("detail") or "")
                last_at = datetime.fromisoformat(str(test["at"])) if test.get("at") else None
        else:
            detail = "needs " + ", ".join(missing)
            limited.update(channel.get("capabilities", []))
        channels.append(
            ChannelStatus(
                key=str(channel["key"]),
                label=str(channel["label"]),
                direction=str(channel["direction"]),
                purpose=str(channel.get("purpose") or ""),
                hint=channel.get("hint"),
                configured=configured,
                missing=missing,
                state=state,
                detail=detail,
                last_at=last_at,
                count_24h=count,
            )
        )
    declared = dict(source.capabilities or {})
    effective = {k: bool(v) and k not in limited for k, v in declared.items()}
    return DataSourceStatus(
        channels=channels,
        effective_capabilities=effective,
        limited_capabilities=sorted(k for k in limited if declared.get(k)),
    )


@router.post("/{data_source_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    data_source_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ConnectionTestResult:
    """Call the platform's API with the stored credentials. A push-only source has nothing to
    call: it receives on its webhook."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    connector = _management(source)
    tester = getattr(connector, "test_connection", None)
    if tester is None:
        return ConnectionTestResult(
            ok=True, detail="This source receives on its webhook; there is no API to call."
        )
    try:
        result = await tester()
    except ApplicationError as error:
        await report_api_test(source.id, False, str(error))
        return ConnectionTestResult(ok=False, detail=str(error), result={"code": error.code})
    except httpx.HTTPError as error:
        await report_api_test(source.id, False, f"platform unreachable: {error}")
        return ConnectionTestResult(ok=False, detail=f"platform unreachable: {error}")
    await report_api_test(source.id, True, "The platform answered.")
    return ConnectionTestResult(
        ok=True, detail="The platform answered.", result=dict(result) if result else {}
    )


@router.post("/{data_source_id}/sync-devices", response_model=DeviceSyncResult)
async def sync_devices(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceSyncResult:
    """Read the platform's device list into the source's external identities: new ones appear
    under Needs attention to be linked, known ones get their attributes refreshed."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    lister = getattr(_management(source), "list_devices", None)
    if lister is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not list devices",
        )
    try:
        listed = await lister()
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    created = updated = 0
    for item in listed:
        external_id = (
            str(item.get("external_id") or item.get("devEui") or item.get("dev_eui") or "")
            .strip()
            .upper()
        )
        if not external_id:
            continue
        attributes = {**dict(item.get("attributes") or {})}
        if item.get("name"):
            attributes["name"] = item["name"]
        identity = await session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.data_source_id == source.id,
                ExternalIdentity.external_id == external_id,
            )
        )
        if identity is None:
            session.add(
                ExternalIdentity(
                    data_source_id=source.id,
                    external_id=external_id,
                    identity_type=str(item.get("identity_type") or "dev_eui"),
                    attributes=attributes,
                )
            )
            created += 1
        else:
            identity.attributes = {**(identity.attributes or {}), **attributes}
            updated += 1
    await record_audit(
        session,
        user=user,
        action="data_source.devices_synced",
        object_type="data_source",
        object_id=str(source.id),
        details={"listed": len(listed), "created": created, "updated": updated},
    )
    await session.commit()
    return DeviceSyncResult(listed=len(listed), created=created, updated=updated)


@router.post("/{data_source_id}/sync-gateways", response_model=GatewaySyncResult)
async def sync_gateways(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> GatewaySyncResult:
    """Read the platform's gateway list into the registry: names, locations, states."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    adapter = ADAPTERS.get(source.adapter_key)
    factory = getattr(adapter, "management_connector", None)
    connector = factory(data_source_context(source)) if factory else None
    lister = getattr(connector, "list_gateway_updates", None)
    if lister is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not list gateways",
        )
    try:
        updates = await lister()
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    now = utc_now()
    for update in updates:
        await apply_gateway_update(session, source.id, update, now)
    await record_audit(
        session,
        user=user,
        action="data_source.gateways_synced",
        object_type="data_source",
        object_id=str(source.id),
        details={"synced": len(updates)},
    )
    await session.commit()
    return GatewaySyncResult(synced=len(updates))


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
    if getattr(ADAPTERS.get(source.adapter_key), "builtin", False):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Built-in channel sources cannot be deleted; disable instead"
        )
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
