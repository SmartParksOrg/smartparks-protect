"""Data sources (external platform accounts) and their external identities. Server admin only in
phase 1; credentials are written, never read back."""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from shared.connectivity.base import AdapterCapabilities, DataSourceContext
from shared.connectivity.channels import api_channel_key, channel_enabled
from shared.connectivity.gateway_sync import gateway_lister, sync_source_gateways
from shared.connectivity.registry import ADAPTERS, channels_of, describe_adapter
from shared.connectivity.state import read_api_test, read_connector, report_api_test
from shared.connectivity.transports.http import hash_token, new_webhook_token
from shared.database import get_session
from shared.ingest import data_source_context
from shared.models import (
    Command,
    DataSource,
    DataSourceCursor,
    DataSourceProjectScope,
    Device,
    ExternalIdentity,
    Project,
    SourceEvent,
    User,
)
from shared.secrets import decrypt_json, encrypt_json
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
    adapter = ADAPTERS[body.adapter_key]
    token = new_webhook_token() if getattr(adapter, "push", False) else None
    credentials = dict(body.credentials or {})
    if token and getattr(adapter, "keeps_webhook_token", False):
        credentials["webhook_token"] = token  # for Connect applications (decision D125)
    values["config"] = await _complete_config(
        body.adapter_key, dict(values.get("config") or {}), credentials, values.get("channels")
    )
    source = DataSource(
        credentials_encrypted=encrypt_json(credentials) if credentials else None,
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
    if getattr(ADAPTERS.get(source.adapter_key), "keeps_webhook_token", False):
        credentials = (
            decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {}
        )
        source.credentials_encrypted = encrypt_json({**credentials, "webhook_token": token})
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


class ApplicationConnection(BaseModel):
    application_id: str
    name: str
    outcome: str = Field(description="connected, updated, already or failed")
    urls: list[str] = Field(default_factory=list, description="The URL list after the change")
    before: list[str] = Field(default_factory=list, description="The URL list as it was")
    headers: list[str] = Field(default_factory=list, description="Header names, never changed")
    error: str | None = None


class ConnectApplications(BaseModel):
    application_ids: list[str] | None = Field(
        None, description="Only these applications; every application when absent"
    )


class ApplicationStatus(BaseModel):
    application_id: str
    name: str
    state: str = Field(description="connected, other (posts elsewhere only) or none")
    urls: list[str] = Field(default_factory=list, description="URLs without their query")
    headers: list[str] = Field(default_factory=list)


class DisconnectApplicationsResult(BaseModel):
    disconnected: int
    not_connected: int
    failed: int
    applications: list[ApplicationConnection]


class ConnectApplicationsResult(BaseModel):
    dry_run: bool = False
    connected: int
    updated: int
    already: int
    failed: int
    applications: list[ApplicationConnection]


def _webhook_base(source: DataSource) -> str:
    return f"{get_settings().public_url}/api/v1/ingest/http/{source.id}"


async def _complete_config(
    adapter_key: str,
    config: dict[str, Any],
    credentials: dict[str, Any],
    channels: dict[str, Any] | None,
) -> dict[str, Any]:
    """Let an adapter with a quick setup (decision D128) fill in what it derives, when its API
    channel is on; its refusal is the caller's 422 with the reason."""
    adapter = ADAPTERS.get(adapter_key)
    completer = getattr(adapter, "complete_config", None)
    if completer is None or not channel_enabled(channels, api_channel_key(adapter_key)):
        return config
    context = DataSourceContext(
        id=uuid.uuid4(),
        name="",
        adapter_key=adapter_key,
        config=dict(config),
        credentials=dict(credentials),
        capabilities=AdapterCapabilities(),
    )
    try:
        return dict(await completer(context))
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"platform unreachable: {error}"
        ) from error


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
    enabled: bool = True
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
        enabled = channel_enabled(source.channels, str(channel["key"]))
        state, detail, last_at, count = "off", None, None, 0
        if not enabled:
            state, detail = "disabled", "switched off on this source"
            if configured:
                limited.update(channel.get("capabilities", []))
        elif configured and channel["direction"] == "in":
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
                # Adapters without a test call (ThingPark) prove the channel by their downlinks.
                last_command = await session.scalar(
                    select(Command)
                    .where(Command.data_source_id == source.id)
                    .order_by(Command.created_at.desc())
                    .limit(1)
                )
                if last_command is None:
                    state, detail = "ready", "configured; no downlink sent through this source yet"
                else:
                    failed = last_command.status in ("failed", "expired")
                    state = "error" if failed else "ok"
                    detail = f"last downlink {last_command.action_key} {last_command.status}"
                    if failed and last_command.error_message:
                        detail = f"{detail}: {last_command.error_message}"
                    last_at = last_command.updated_at
            else:
                state = "ok" if test.get("ok") else "error"
                detail = str(test.get("detail") or "")
                last_at = datetime.fromisoformat(str(test["at"])) if test.get("at") else None
        elif not configured:
            detail = "needs " + ", ".join(missing)
            limited.update(channel.get("capabilities", []))
        channels.append(
            ChannelStatus(
                key=str(channel["key"]),
                label=str(channel["label"]),
                direction=str(channel["direction"]),
                purpose=str(channel.get("purpose") or ""),
                hint=channel.get("hint"),
                enabled=enabled,
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
    if not channel_enabled(source.channels, api_channel_key(source.adapter_key)):
        return ConnectionTestResult(ok=False, detail="The API channel of this source is off.")
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
    payload = dict(result) if result else {}
    status_of = getattr(connector, "integration_status", None)
    if status_of is not None and source.webhook_token_hash is not None:
        # which applications post to this webhook (decision D126)
        try:
            applications = await status_of(_webhook_base(source))
        except ApplicationError as error:
            payload["applications_error"] = str(error)
        else:
            payload["applications"] = applications
            payload["connected"] = sum(1 for a in applications if a["state"] == "connected")
    return ConnectionTestResult(ok=True, detail="The platform answered.", result=payload)


@router.get("/{data_source_id}/applications", response_model=list[ApplicationStatus])
async def list_applications(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ApplicationStatus]:
    """The platform's applications with whether each posts to this source (decision D132)."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    if not channel_enabled(source.channels, api_channel_key(source.adapter_key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The API channel of this source is off")
    status_of = getattr(_management(source), "integration_status", None)
    if status_of is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not manage its platform's integrations",
        )
    try:
        rows = await status_of(_webhook_base(source))
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    return [ApplicationStatus(**r) for r in rows]


@router.post(
    "/{data_source_id}/disconnect-applications", response_model=DisconnectApplicationsResult
)
async def disconnect_applications(
    data_source_id: uuid.UUID,
    body: ConnectApplications,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DisconnectApplicationsResult:
    """Take this source's webhook out of the given applications' HTTP integrations (D132):
    only our entries go, other URLs and headers stay."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    if not channel_enabled(source.channels, api_channel_key(source.adapter_key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The API channel of this source is off")
    disconnect = getattr(_management(source), "disconnect_applications", None)
    if disconnect is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not manage its platform's integrations",
        )
    if not body.application_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name the applications")
    try:
        results = await disconnect(_webhook_base(source), only=set(body.application_ids))
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    applications = [ApplicationConnection(**r) for r in results]
    counts = {
        k: sum(1 for a in applications if a.outcome == k)
        for k in ("disconnected", "not_connected", "failed")
    }
    await record_audit(
        session,
        user=user,
        action="data_source.applications_disconnected",
        object_type="data_source",
        object_id=str(source.id),
        details={
            **counts,
            "applications": [
                {"id": a.application_id, "name": a.name, "outcome": a.outcome, "error": a.error}
                for a in applications
            ],
        },
    )
    await session.commit()
    return DisconnectApplicationsResult(**counts, applications=applications)


@router.post("/{data_source_id}/connect-applications", response_model=ConnectApplicationsResult)
async def connect_applications(
    data_source_id: uuid.UUID,
    dry_run: bool = Query(
        False, description="Report what would change on every application without writing"
    ),
    body: ConnectApplications | None = None,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> ConnectApplicationsResult:
    """Put this source's webhook on the HTTP integration of every application the platform
    lists for it (decision D125). Needs the API channel and the encrypted copy of the webhook
    token, which a source made before the copy existed gets from one token rotation. With
    `dry_run` nothing is written: the answer shows each application's URL list before and
    after, so a platform in operation can be checked first (decision D129)."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    if not channel_enabled(source.channels, api_channel_key(source.adapter_key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The API channel of this source is off")
    connector = _management(source)
    connect = getattr(connector, "connect_applications", None)
    if connect is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not manage its platform's integrations",
        )
    credentials = decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {}
    token = credentials.get("webhook_token")
    if not token or source.webhook_token_hash is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This source keeps no copy of its webhook token: issue a new token once, then "
            "connect the applications",
        )
    try:
        only = set(body.application_ids) if body and body.application_ids is not None else None
        results = await connect(
            f"{_webhook_base(source)}?token={token}", dry_run=dry_run, only=only
        )
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    applications = [ApplicationConnection(**r) for r in results]
    counts = {
        k: sum(1 for a in applications if a.outcome == k)
        for k in ("connected", "updated", "already", "failed")
    }
    if dry_run:
        return ConnectApplicationsResult(dry_run=True, **counts, applications=applications)
    await record_audit(
        session,
        user=user,
        action="data_source.applications_connected",
        object_type="data_source",
        object_id=str(source.id),
        details={
            **counts,
            "applications": [
                {"id": a.application_id, "name": a.name, "outcome": a.outcome, "error": a.error}
                for a in applications
            ],
        },
    )
    await session.commit()
    return ConnectApplicationsResult(**counts, applications=applications)


@router.post("/{data_source_id}/sync-devices", response_model=DeviceSyncResult)
async def sync_devices(
    data_source_id: uuid.UUID,
    user: User = Depends(require_server_admin),
    session: AsyncSession = Depends(get_session),
) -> DeviceSyncResult:
    """Read the platform's device list into the source's external identities: new ones appear
    under Needs attention to be linked, known ones get their attributes refreshed."""
    source = await get_or_404(session, DataSource, data_source_id, "Data source")
    if not channel_enabled(source.channels, api_channel_key(source.adapter_key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The API channel of this source is off")
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
        external_id = str(
            item.get("external_id") or item.get("devEui") or item.get("dev_eui") or ""
        ).strip()
        if not external_id:
            continue
        # hex identifiers (DevEUIs) are stored upper case; a platform's own ids (Cloudloop's
        # case sensitive thing ids) stay as they are
        if re.fullmatch(r"[0-9a-fA-F]+", external_id):
            external_id = external_id.upper()
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
    lister = gateway_lister(source)
    if lister is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this data source's adapter does not list gateways",
        )
    try:
        synced = await sync_source_gateways(session, source, lister, utc_now())
    except ApplicationError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    except httpx.HTTPError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"platform unreachable: {error}"
        ) from error
    await record_audit(
        session,
        user=user,
        action="data_source.gateways_synced",
        object_type="data_source",
        object_id=str(source.id),
        details={"synced": synced},
    )
    await session.commit()
    return GatewaySyncResult(synced=synced)


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
    stored = decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {}
    if body.credentials is not None:
        # a copy of the webhook token outlives a credentials update (decision D125)
        kept = {k: v for k, v in stored.items() if k == "webhook_token"}
        source.credentials_encrypted = encrypt_json({**kept, **body.credentials})
        changed["credentials"] = "replaced"
    if body.config is not None or body.credentials is not None or body.channels is not None:
        source.config = await _complete_config(
            source.adapter_key,
            dict(source.config),
            decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {},
            source.channels,
        )
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
