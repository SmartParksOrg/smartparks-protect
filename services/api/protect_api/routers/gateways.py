"""Gateways and connectivity health (architecture 20, decision D66): the registry per project
(gateways that received the project's devices), gateway detail with per-device statistics,
gateway diversity and best-gateway analysis per device, and the server-level registry with
administrator overrides."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.crud import geom_to_geojson, get_or_404
from protect_api.deps import ProjectContext, require_permission, require_server_admin
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.routers.network import _project_device_ids
from protect_api.schemas.integrations import (
    DeviceConnectivity,
    GatewayDetail,
    GatewayDeviceStat,
    GatewayRead,
    GatewayUpdateRequest,
)
from shared.database import get_session
from shared.domain.links import resolve_links
from shared.models import DataSource, Device, Gateway, GatewayReception
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(tags=["gateways"])
admin_router = APIRouter(
    prefix="/admin", tags=["gateways"], dependencies=[Depends(require_server_admin)]
)

MAX_HOURS = 24 * 30


def gateway_read(
    gateway: Gateway,
    source: DataSource | None,
    stats: dict[str, Any] | None = None,
) -> GatewayRead:
    data = GatewayRead.model_validate(gateway)
    data.geometry = geom_to_geojson(gateway.geom)
    data.display_name = gateway.name_override or gateway.name or gateway.external_id
    data.data_source_name = source.name if source else None
    if source is not None:
        data.links = [
            link
            for link in resolve_links(source, None, gateway_id=gateway.external_id)
            if link["key"] == "OPEN_GATEWAY"
        ]
    if stats:
        data.receptions = int(stats.get("receptions") or 0)
        data.devices = int(stats.get("devices") or 0)
        data.mean_rssi = stats.get("mean_rssi")
        data.mean_snr = stats.get("mean_snr")
        data.last_reception_at = stats.get("last_reception_at")
    return data


async def _sources(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, DataSource]:
    if not ids:
        return {}
    return {
        s.id: s
        for s in (await session.scalars(select(DataSource).where(DataSource.id.in_(ids)))).all()
    }


async def _reception_stats(
    session: AsyncSession,
    device_ids: list[uuid.UUID],
    since: datetime,
    until: datetime,
) -> dict[tuple[uuid.UUID, str], dict[str, Any]]:
    """Per (data source, gateway id): receptions, devices, mean RSSI and SNR, last time."""
    if not device_ids:
        return {}
    rows = (
        await session.execute(
            select(
                GatewayReception.data_source_id,
                GatewayReception.gateway_id,
                func.count().label("receptions"),
                func.count(func.distinct(GatewayReception.device_id)).label("devices"),
                func.avg(GatewayReception.rssi).label("mean_rssi"),
                func.avg(GatewayReception.snr).label("mean_snr"),
                func.max(GatewayReception.time).label("last_reception_at"),
            )
            .where(
                GatewayReception.device_id.in_(device_ids),
                GatewayReception.time >= since,
                GatewayReception.time < until,
            )
            .group_by(GatewayReception.data_source_id, GatewayReception.gateway_id)
        )
    ).all()
    return {
        (row.data_source_id, row.gateway_id): {
            "receptions": row.receptions,
            "devices": row.devices,
            "mean_rssi": round(float(row.mean_rssi), 1) if row.mean_rssi is not None else None,
            "mean_snr": round(float(row.mean_snr), 1) if row.mean_snr is not None else None,
            "last_reception_at": row.last_reception_at,
        }
        for row in rows
    }


def _window(hours: int) -> tuple[datetime, datetime]:
    until = utc_now()
    return until - timedelta(hours=hours), until


@router.get("/projects/{project_id}/gateways", response_model=list[GatewayRead])
async def project_gateways(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[GatewayRead]:
    """Gateways that received the project's devices in the window, busiest first."""
    since, until = _window(hours)
    device_ids = await _project_device_ids(session, context.project.id, since, until)
    stats = await _reception_stats(session, device_ids, since, until)
    if not stats:
        return []
    gateways = (
        await session.scalars(
            select(Gateway).where(
                Gateway.data_source_id.in_({k[0] for k in stats}),
                Gateway.external_id.in_({k[1] for k in stats}),
            )
        )
    ).all()
    sources = await _sources(session, {g.data_source_id for g in gateways})
    items = [
        gateway_read(g, sources.get(g.data_source_id), stats.get((g.data_source_id, g.external_id)))
        for g in gateways
        if (g.data_source_id, g.external_id) in stats
    ]
    items.sort(key=lambda g: g.receptions, reverse=True)
    return items[:limit]


@router.get("/projects/{project_id}/gateways/{gateway_id}", response_model=GatewayDetail)
async def project_gateway(
    gateway_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    session: AsyncSession = Depends(get_session),
) -> GatewayDetail:
    gateway = await get_or_404(session, Gateway, gateway_id, "Gateway")
    since, until = _window(hours)
    device_ids = await _project_device_ids(session, context.project.id, since, until)
    stats = await _reception_stats(session, device_ids, since, until)
    source = await session.get(DataSource, gateway.data_source_id)
    rows = (
        await session.execute(
            select(
                GatewayReception.device_id,
                func.count().label("receptions"),
                func.avg(GatewayReception.rssi).label("mean_rssi"),
                func.avg(GatewayReception.snr).label("mean_snr"),
                func.max(GatewayReception.time).label("last_reception_at"),
            )
            .where(
                GatewayReception.data_source_id == gateway.data_source_id,
                GatewayReception.gateway_id == gateway.external_id,
                GatewayReception.device_id.in_(device_ids) if device_ids else false(),
                GatewayReception.time >= since,
                GatewayReception.time < until,
            )
            .group_by(GatewayReception.device_id)
            .order_by(func.count().desc())
            .limit(200)
        )
    ).all()
    names = {
        d.id: d.name
        for d in (
            await session.scalars(
                select(Device).where(Device.id.in_([r.device_id for r in rows if r.device_id]))
            )
        ).all()
    }
    return GatewayDetail(
        gateway=gateway_read(
            gateway, source, stats.get((gateway.data_source_id, gateway.external_id))
        ),
        devices=[
            GatewayDeviceStat(
                device_id=row.device_id,
                device_name=names.get(row.device_id) if row.device_id else None,
                receptions=row.receptions,
                mean_rssi=round(float(row.mean_rssi), 1) if row.mean_rssi is not None else None,
                mean_snr=round(float(row.mean_snr), 1) if row.mean_snr is not None else None,
                last_reception_at=row.last_reception_at,
            )
            for row in rows
        ],
    )


@router.get("/projects/{project_id}/connectivity", response_model=list[DeviceConnectivity])
async def project_connectivity(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    hours: int = Query(24, ge=1, le=MAX_HOURS),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceConnectivity]:
    """Gateway diversity per device: how many gateways heard it, which one most often and
    how large that gateway's share is, mean signal, last reception."""
    since, until = _window(hours)
    device_ids = await _project_device_ids(session, context.project.id, since, until)
    if not device_ids:
        return []
    rows = (
        await session.execute(
            select(
                GatewayReception.device_id,
                GatewayReception.data_source_id,
                GatewayReception.gateway_id,
                func.count().label("receptions"),
                func.count(func.distinct(GatewayReception.source_event_id)).label("uplinks"),
                func.avg(GatewayReception.rssi).label("mean_rssi"),
                func.avg(GatewayReception.snr).label("mean_snr"),
                func.max(GatewayReception.time).label("last_reception_at"),
            )
            .where(
                GatewayReception.device_id.in_(device_ids),
                GatewayReception.time >= since,
                GatewayReception.time < until,
            )
            .group_by(
                GatewayReception.device_id,
                GatewayReception.data_source_id,
                GatewayReception.gateway_id,
            )
        )
    ).all()
    if not rows:
        return []
    gateways = {
        (g.data_source_id, g.external_id): g
        for g in (
            await session.scalars(
                select(Gateway).where(
                    Gateway.data_source_id.in_({r.data_source_id for r in rows}),
                    Gateway.external_id.in_({r.gateway_id for r in rows}),
                )
            )
        ).all()
    }
    names = {
        d.id: d.name
        for d in (await session.scalars(select(Device).where(Device.id.in_(device_ids)))).all()
    }
    uplink_totals = {
        row.device_id: int(row.uplinks)
        for row in (
            await session.execute(
                select(
                    GatewayReception.device_id,
                    func.count(func.distinct(GatewayReception.source_event_id)).label("uplinks"),
                )
                .where(
                    GatewayReception.device_id.in_(device_ids),
                    GatewayReception.time >= since,
                    GatewayReception.time < until,
                )
                .group_by(GatewayReception.device_id)
            )
        ).all()
    }
    per_device: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        per_device.setdefault(row.device_id, []).append(row)
    result = []
    for device_id, device_rows in per_device.items():
        device_rows.sort(key=lambda r: r.receptions, reverse=True)
        best = device_rows[0]
        gateway = gateways.get((best.data_source_id, best.gateway_id))
        total_receptions = sum(int(r.receptions) for r in device_rows)
        uplinks = uplink_totals.get(device_id, 0)
        rssi = [
            float(r.mean_rssi) * int(r.receptions) for r in device_rows if r.mean_rssi is not None
        ]
        snr = [float(r.mean_snr) * int(r.receptions) for r in device_rows if r.mean_snr is not None]
        result.append(
            DeviceConnectivity(
                device_id=device_id,
                device_name=names.get(device_id),
                receptions=total_receptions,
                uplinks=uplinks,
                gateway_count=len(device_rows),
                best_gateway_id=gateway.id if gateway else None,
                best_gateway_name=(
                    (gateway.name_override or gateway.name or gateway.external_id)
                    if gateway
                    else best.gateway_id
                ),
                best_gateway_share=(
                    round(min(1.0, int(best.uplinks) / uplinks), 3) if uplinks else None
                ),
                mean_rssi=round(sum(rssi) / total_receptions, 1) if rssi else None,
                mean_snr=round(sum(snr) / total_receptions, 1) if snr else None,
                last_reception_at=max(r.last_reception_at for r in device_rows),
                gateways=[
                    {
                        "gateway_id": str(g.id)
                        if (g := gateways.get((r.data_source_id, r.gateway_id)))
                        else None,
                        "external_id": r.gateway_id,
                        "name": (g.name_override or g.name) if g else None,
                        "receptions": int(r.receptions),
                        "uplinks": int(r.uplinks),
                        "mean_rssi": round(float(r.mean_rssi), 1)
                        if r.mean_rssi is not None
                        else None,
                        "mean_snr": round(float(r.mean_snr), 1) if r.mean_snr is not None else None,
                    }
                    for r in device_rows
                ],
            )
        )
    result.sort(key=lambda d: (d.gateway_count, d.receptions))
    return result[:limit]


@admin_router.get("/gateways", response_model=PageResponse[GatewayRead])
async def all_gateways(
    page: Page = Depends(page),
    data_source_id: uuid.UUID | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[GatewayRead]:
    statement = select(Gateway)
    if data_source_id is not None:
        statement = statement.where(Gateway.data_source_id == data_source_id)
    rows, next_cursor = await paginate(session, Gateway.id, statement, page)
    sources = await _sources(session, {g.data_source_id for g in rows})
    return PageResponse(
        items=[gateway_read(g, sources.get(g.data_source_id)) for g in rows],
        next_cursor=next_cursor,
    )


@admin_router.patch("/gateways/{gateway_id}", response_model=GatewayRead)
async def update_gateway(
    gateway_id: uuid.UUID,
    body: GatewayUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> GatewayRead:
    gateway = await get_or_404(session, Gateway, gateway_id, "Gateway")
    patch = body.model_dump(exclude_unset=True)
    if "name_override" in patch:
        gateway.name_override = patch["name_override"] or None
    if "description" in patch:
        gateway.description = patch["description"]
    if "altitude_m" in patch:
        gateway.altitude_m = patch["altitude_m"]
    if patch.get("latitude") is not None or patch.get("longitude") is not None:
        if patch.get("latitude") is None or patch.get("longitude") is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "latitude and longitude go together"
            )
        gateway.geom = from_shape(Point(patch["longitude"], patch["latitude"]), srid=4326)
    await session.commit()
    source = await session.get(DataSource, gateway.data_source_id)
    return gateway_read(gateway, source)
