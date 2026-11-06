"""Data sources on one platform instance (decisions D375 and D376).

A tenant API key on a ChirpStack lists and posts its own tenant's things alone, so a project
heard through several tenants of one ChirpStack has a data source per tenant key, all with
the same address. The physical gateways behind them are the same: a gateway row is kept once
per instance, under whichever source first saw it, and every read of its receptions takes the
receptions of all its sibling sources together.
"""

import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import DataSource

Groups = dict[uuid.UUID, tuple[uuid.UUID, ...]]


def instance_host(config: dict[str, Any] | None) -> str | None:
    """The host of the platform instance a source talks to, from its `api_url`, whatever the
    scheme (grpc-web over https, native gRPC); None for a source without one."""
    url = str((config or {}).get("api_url") or "").strip()
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.hostname or "").lower() or None


async def instance_groups(session: AsyncSession) -> Groups:
    """Every data source id mapped to the ids of the sources on its platform instance, itself
    among them, in one fixed order: sources of one adapter with the same `api_url` host form a
    group, every other source stands alone."""
    rows = (
        await session.execute(select(DataSource.id, DataSource.adapter_key, DataSource.config))
    ).all()
    by_instance: dict[tuple[str, str], list[uuid.UUID]] = {}
    groups: Groups = {}
    for source_id, adapter_key, config in rows:
        host = instance_host(config)
        if host is None:
            groups[source_id] = (source_id,)
        else:
            by_instance.setdefault((adapter_key, host), []).append(source_id)
    for ids in by_instance.values():
        ordered = tuple(sorted(ids, key=str))
        for source_id in ordered:
            groups[source_id] = ordered
    return groups


def siblings_of(groups: Groups, source_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
    return groups.get(source_id, (source_id,))


def canonical_source(groups: Groups, source_id: uuid.UUID) -> uuid.UUID:
    """The one id that stands for every source of the instance: the first of the group."""
    return siblings_of(groups, source_id)[0]
