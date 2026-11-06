"""The gateway sync (decision D176): the platform's gateway list read into the registry, names,
locations and states. The button on a data source and the ingest service's daily pass share it.

Several sources on one platform instance (decision D375: a tenant API key each on the same
ChirpStack, since a tenant key lists its own tenant's gateways alone) stand behind the same
physical gateways: a list applied through one source names, places and dates the rows the
other sources hold for the same gateway id, and makes a row of its own only for a gateway no
sibling holds yet.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.connectivity.base import GatewayUpdate
from shared.connectivity.channels import api_channel_key, channel_enabled
from shared.connectivity.registry import ADAPTERS
from shared.ingest import apply_gateway_update, data_source_context
from shared.logger import get_logger
from shared.models import DataSource, Gateway

log = get_logger("gateway_sync")

Lister = Callable[[], Awaitable[list[GatewayUpdate]]]


def gateway_lister(source: DataSource, *, require_channel: bool = False) -> Lister | None:
    """The source's `list_gateway_updates`, or None when its adapter does not list gateways
    (or, for the daily pass, when the source's API channel is switched off)."""
    adapter = ADAPTERS.get(source.adapter_key)
    if adapter is None:
        return None
    if require_channel and not channel_enabled(
        source.channels, api_channel_key(source.adapter_key)
    ):
        return None
    factory = getattr(adapter, "management_connector", None)
    connector = factory(data_source_context(source)) if factory else None
    lister = getattr(connector, "list_gateway_updates", None)
    return None if lister is None else cast(Lister, lister)


def instance_host(config: dict[str, Any] | None) -> str | None:
    """The host of the platform instance a source talks to, from its `api_url`, whatever the
    scheme (grpc-web over https, native gRPC); None for a source without one."""
    url = str((config or {}).get("api_url") or "").strip()
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.hostname or "").lower() or None


async def instance_source_ids(session: AsyncSession, source: DataSource) -> list[uuid.UUID]:
    """The source and its siblings: every source of the same adapter on the same platform
    instance (decision D375), the source itself first."""
    host = instance_host(source.config)
    if host is None:
        return [source.id]
    rows = (
        await session.scalars(
            select(DataSource).where(DataSource.adapter_key == source.adapter_key)
        )
    ).all()
    return [source.id] + [
        s.id for s in rows if s.id != source.id and instance_host(s.config) == host
    ]


async def sync_source_gateways(
    session: AsyncSession, source: DataSource, lister: Lister, now: datetime
) -> int:
    """Apply the platform's list to the registry; the number of gateways listed. Errors are
    the caller's: the endpoint turns them into a 502, the daily pass logs them. A gateway a
    sibling source already holds (D375) is updated there, every holder alike, and gets no row
    under this source; a gateway nobody holds becomes this source's row."""
    updates = await lister()
    sources = await instance_source_ids(session, source)
    for update in updates:
        holders: list[uuid.UUID] = [source.id]
        if len(sources) > 1:
            holders = list(
                await session.scalars(
                    select(Gateway.data_source_id).where(
                        Gateway.data_source_id.in_(sources),
                        Gateway.external_id == update.gateway_id.lower(),
                    )
                )
            ) or [source.id]
        for source_id in holders:
            await apply_gateway_update(session, source_id, update, now)
    return len(updates)


async def sync_all_gateways(
    session: AsyncSession, now: datetime, *, require_channel: bool = True
) -> dict[str, int]:
    """One pass over every enabled source whose adapter lists gateways (the ingest service's
    daily pass): the number listed per source name; a failing source is logged and skipped,
    every other one is committed on its own."""
    synced: dict[str, int] = {}
    sources = (await session.scalars(select(DataSource).where(DataSource.enabled.is_(True)))).all()
    for source in sources:
        lister = gateway_lister(source, require_channel=require_channel)
        if lister is None:
            continue
        try:
            synced[source.name] = await sync_source_gateways(session, source, lister, now)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.warning(
                "gateway sync failed",
                data_source=source.name,
                error=f"{type(exc).__name__}: {exc}",
            )
    if synced:
        log.info("gateways synced", sources=synced)
    return synced
