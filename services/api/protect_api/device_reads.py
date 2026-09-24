"""Device reads with what the current state knows: last seen, health, the entity tracked today,
the project and the data sources. Shared by the devices and the entities routers, so both judge
a device's health by the same rule (decision D286)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.crud import geom_to_geojson
from protect_api.schemas.domain import DeviceRead
from protect_api.schemas.log_files import WalkRead
from shared import reprocessing
from shared.device_drivers.registry import DRIVERS
from shared.domain.battery import resolve as resolve_battery
from shared.domain.health import device_health
from shared.models import (
    DataSource,
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    DeviceType,
    Entity,
    ExternalIdentity,
)
from shared.timeutil import utc_now


async def with_state(session: AsyncSession, devices: list[Device]) -> list[DeviceRead]:
    """Device reads with last seen and health from the current state, one query for all."""
    reads = [DeviceRead.model_validate(d) for d in devices]
    for device, read in zip(devices, reads, strict=True):
        read.static_position = geom_to_geojson(device.static_geom)
    if not devices:
        return reads
    ids = [d.id for d in devices]
    states = {
        s.device_id: s
        for s in (
            await session.scalars(
                select(DeviceCurrentState).where(DeviceCurrentState.device_id.in_(ids))
            )
        ).all()
    }
    types = {
        t.id: t
        for t in (
            await session.scalars(
                select(DeviceType).where(DeviceType.id.in_({d.device_type_id for d in devices}))
            )
        ).all()
    }
    now = utc_now()
    tracking = {
        device_id: (entity_id, name, group_id)
        for device_id, entity_id, name, group_id in (
            await session.execute(
                select(DeviceEntityAssignment.device_id, Entity.id, Entity.name, Entity.group_id)
                .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
                .where(
                    DeviceEntityAssignment.device_id.in_(ids),
                    DeviceEntityAssignment.validity.op("@>")(now),
                )
            )
        ).all()
    }
    current_projects = {
        device_id: project_id
        for device_id, project_id in (
            await session.execute(
                select(DeviceProjectAssignment.device_id, DeviceProjectAssignment.project_id).where(
                    DeviceProjectAssignment.device_id.in_(ids),
                    DeviceProjectAssignment.validity.op("@>")(now),
                )
            )
        ).all()
    }
    source_names: dict[uuid.UUID, list[str]] = {}
    for device_id, name in (
        await session.execute(
            select(ExternalIdentity.device_id, DataSource.name)
            .join(DataSource, DataSource.id == ExternalIdentity.data_source_id)
            .where(ExternalIdentity.device_id.in_(ids), ExternalIdentity.ignored.is_(False))
            .distinct()
            .order_by(DataSource.name)
        )
    ).all():
        source_names.setdefault(device_id, []).append(name)
    for device, read in zip(devices, reads, strict=True):
        read.project_id = current_projects.get(device.id)
        read.data_source_names = source_names.get(device.id, [])
        if device.id in tracking:
            read.entity_id, read.entity_name, read.group_id = tracking[device.id]
        state = states.get(device.id)
        if state is None:
            continue
        device_type = types.get(device.device_type_id)
        driver = DRIVERS.get(device_type.driver_key) if device_type else None
        read.last_seen_at = state.last_seen_at
        read.data_received_at = state.updated_at
        read.health = device_health(
            getattr(driver, "health", None),
            latest_measurements=state.latest_measurements,
            latest_state=state.latest_state,
            latest_state_time=state.latest_state_time,
            last_seen_at=state.last_seen_at,
            last_movement_at=state.last_movement_at,
            last_reset_at=state.last_reset_at,
            battery=resolve_battery(
                device.attributes,
                device_type.default_settings if device_type else None,
                driver,
            ).profile,
        )
    return reads


async def walk_reads(session: AsyncSession, walks: list[reprocessing.Walk]) -> list[WalkRead]:
    """The walks with the names a person reads: the identity's external id and the device."""
    if not walks:
        return []
    external_ids: dict[uuid.UUID, str] = {
        identity_id: external_id
        for identity_id, external_id in (
            await session.execute(
                select(ExternalIdentity.id, ExternalIdentity.external_id).where(
                    ExternalIdentity.id.in_([w.identity_id for w in walks])
                )
            )
        ).all()
    }
    names: dict[uuid.UUID, str] = {
        device_id: name
        for device_id, name in (
            await session.execute(
                select(Device.id, Device.name).where(Device.id.in_([w.device_id for w in walks]))
            )
        ).all()
    }
    return [
        WalkRead(
            identity_id=w.identity_id,
            external_id=external_ids.get(w.identity_id),
            device_id=w.device_id,
            device_name=names.get(w.device_id),
            total=w.total,
            done=w.done,
        )
        for w in sorted(walks, key=lambda w: (names.get(w.device_id) or "", str(w.identity_id)))
    ]
