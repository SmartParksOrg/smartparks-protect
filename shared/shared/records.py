"""Records (phase 20, decision D142): the moments a selection of entities and devices produced
anything, and the rows that fill them, shared by the API's records read and the records export.
A moment is one (device, effective time); its row carries the position of that moment if any,
the measurements by metric key and the state fields reported then."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CompoundSelect

from shared.curation.effective import (
    effective_geom,
    effective_time,
    in_window,
    sources_filter,
    visible,
)
from shared.models import (
    DataSource,
    Device,
    DeviceStateHistory,
    DeviceType,
    Entity,
    Measurement,
    Position,
)

Key = tuple[uuid.UUID, datetime]


@dataclass(slots=True)
class RecordSelection:
    """What to read: whose records, over which window; `project` gives the project filter of
    the caller's scope for a model's `project_id` column (it is called once per table read, so
    a filter bound to one table never joins another in), and `include_invalid` keeps curated-out
    rows."""

    project: Callable[[Any], Any]
    entity_ids: list[uuid.UUID]
    device_ids: list[uuid.UUID]
    since: datetime
    until: datetime
    include_invalid: bool = False
    sources: str = "device"


@dataclass(slots=True)
class Record:
    time: datetime
    device_id: uuid.UUID
    device_name: str | None
    entity_id: uuid.UUID | None
    entity_name: str | None
    project_id: uuid.UUID | None
    position: Position | None
    lat: float | None
    lon: float | None
    measurements: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] | None = None
    source_event_id: int | None = None
    source_event_ingested_at: datetime | None = None
    trace_id: uuid.UUID | None = None
    #: The metadata a reader adds as columns (Tim, 2026-09-20): the device's type, the data
    #: source the moment's records came through, what kinds of record the moment holds, and
    #: the position's own kind (a fix, an estimate, a fixed place).
    device_type: str | None = None
    data_source_id: uuid.UUID | None = None
    data_source_name: str | None = None
    kinds: list[str] = field(default_factory=list)
    record_type: str | None = None


def _owner(model: Any, selection: RecordSelection) -> Any:
    parts = []
    if selection.entity_ids:
        parts.append(model.entity_id.in_(selection.entity_ids))
    if selection.device_ids:
        parts.append(model.device_id.in_(selection.device_ids))
    return or_(*parts)


def conditions(model: Any, selection: RecordSelection) -> list[Any]:
    rules = [
        selection.project(model.project_id),
        _owner(model, selection),
        in_window(model, selection.since, selection.until),
    ]
    if not selection.include_invalid:
        rules.append(visible(model))
    if model is Position:
        clause = sources_filter(selection.sources)
        if clause is not None:
            rules.append(clause)
    return rules


def keys_statement(selection: RecordSelection) -> CompoundSelect[Any]:
    """The distinct (device, effective time) pairs of the selection, unordered. The time column
    is `moment`: `t` is an attribute of SQLAlchemy's Row."""
    positions = select(
        Position.device_id.label("device_id"), effective_time(Position).label("moment")
    ).where(*conditions(Position, selection))
    measurements = select(
        Measurement.device_id.label("device_id"), effective_time(Measurement).label("moment")
    ).where(*conditions(Measurement, selection))
    return union(positions, measurements)


async def count_keys(session: AsyncSession, selection: RecordSelection) -> int:
    keys = keys_statement(selection).subquery("k")
    return int(await session.scalar(select(func.count()).select_from(keys)) or 0)


async def metric_keys(session: AsyncSession, selection: RecordSelection) -> list[str]:
    """The metric keys the selection reports in the window, for a wide export's header."""
    rows = await session.execute(
        select(Measurement.metric_key)
        .where(*conditions(Measurement, selection))
        .group_by(Measurement.metric_key)
        .order_by(Measurement.metric_key)
    )
    return [row[0] for row in rows.all()]


#: The route a record came by (`lorawan`, `webble`, `flash_log`): a status message stores it
#: on its state, a position on its attributes. The row shows both under the one state column,
#: because a `via` that is empty on every position row read as missing data (Tim, 2026-09-20).
ROUTE_KEY = "via"


async def state_keys(session: AsyncSession, selection: RecordSelection) -> list[str]:
    """The state fields the selection's devices reported in the window, and the route when
    a position carries one."""
    devices: Any = select(Measurement.device_id).where(*conditions(Measurement, selection))
    if selection.device_ids:
        devices = devices.union(select(Device.id).where(Device.id.in_(selection.device_ids)))
    rows = await session.execute(
        select(func.jsonb_object_keys(DeviceStateHistory.state).label("k"))
        .where(
            DeviceStateHistory.device_id.in_(devices),
            DeviceStateHistory.time >= selection.since,
            DeviceStateHistory.time < selection.until,
        )
        .group_by("k")
        .order_by("k")
    )
    keys = [row[0] for row in rows.all()]
    if ROUTE_KEY not in keys:
        routed = await session.scalar(
            select(Position.id)
            .where(*conditions(Position, selection), Position.attributes.has_key(ROUTE_KEY))
            .limit(1)
        )
        if routed is not None:
            keys = sorted([*keys, ROUTE_KEY])
    return keys


def state_of(state: dict[str, Any] | None, position: Position | None) -> dict[str, Any] | None:
    """The state fields a row shows: the state reported at that moment, with the position's
    route filled in under `via` when the moment has no state saying otherwise."""
    route = position.attributes.get(ROUTE_KEY) if position is not None else None
    if route is None or (state is not None and state.get(ROUTE_KEY) is not None):
        return state
    return {**(state or {}), ROUTE_KEY: route}


def value_of(m: Measurement) -> Any:
    if m.curated_value_num is not None:
        return m.curated_value_num
    if m.value_num is not None:
        return m.value_num
    if m.value_bool is not None:
        return m.value_bool
    if m.value_text is not None:
        return m.value_text
    return m.value_json


async def fill(session: AsyncSession, selection: RecordSelection, keys: list[Key]) -> list[Record]:
    """The rows of a page of moments, in the order of `keys`: the positions, measurements and
    state history of the page's devices over its time span are read once each through the owner
    and time indexes and matched to the moments."""
    if not keys:
        return []
    wanted = set(keys)
    devices = {device_id for device_id, _ in keys}
    span_from = min(t for _, t in keys)
    span_to = max(t for _, t in keys) + timedelta(microseconds=1)
    span_positions = [
        selection.project(Position.project_id),
        Position.device_id.in_(devices),
        in_window(Position, span_from, span_to),
    ]
    span_measurements = [
        selection.project(Measurement.project_id),
        Measurement.device_id.in_(devices),
        in_window(Measurement, span_from, span_to),
    ]
    if not selection.include_invalid:
        span_positions.append(visible(Position))
        span_measurements.append(visible(Measurement))
    position_rows = (
        await session.execute(
            select(
                Position,
                effective_time(Position).label("moment"),
                func.ST_Y(effective_geom()).label("lat"),
                func.ST_X(effective_geom()).label("lon"),
            )
            .where(*span_positions)
            .order_by(Position.id)
        )
    ).all()
    measurement_rows = (
        await session.scalars(
            select(Measurement).where(*span_measurements).order_by(Measurement.id)
        )
    ).all()
    state_rows = (
        await session.scalars(
            select(DeviceStateHistory).where(
                DeviceStateHistory.device_id.in_(devices),
                DeviceStateHistory.time >= span_from,
                DeviceStateHistory.time < span_to,
            )
        )
    ).all()

    positions: dict[Key, tuple[Position, float, float]] = {}
    for position, t, lat, lon in position_rows:
        key = (position.device_id, t)
        if key in wanted and key not in positions:
            positions[key] = (position, lat, lon)
    measurements: dict[Key, dict[str, Any]] = {}
    firsts: dict[Key, Measurement] = {}
    for m in measurement_rows:
        key = (m.device_id, m.curated_time or m.time)
        if key not in wanted:
            continue
        bucket = measurements.setdefault(key, {})
        if m.metric_key not in bucket:
            bucket[m.metric_key] = value_of(m)
            firsts.setdefault(key, m)
    states: dict[Key, dict[str, Any]] = {}
    for s in state_rows:
        key = (s.device_id, s.time)
        if key in wanted:
            states.setdefault(key, s.state)

    device_rows = (await session.scalars(select(Device).where(Device.id.in_(devices)))).all()
    device_names = {d.id: d.name for d in device_rows}
    type_ids = {d.device_type_id for d in device_rows}
    type_labels = (
        {
            dt.id: dt.label
            for dt in (
                await session.scalars(select(DeviceType).where(DeviceType.id.in_(type_ids)))
            ).all()
        }
        if type_ids
        else {}
    )
    device_types = {d.id: type_labels.get(d.device_type_id) for d in device_rows}
    source_ids = {p.data_source_id for p, _, _ in positions.values() if p.data_source_id} | {
        m.data_source_id for m in firsts.values() if m.data_source_id
    }
    source_names = (
        {
            s.id: s.name
            for s in (
                await session.scalars(select(DataSource).where(DataSource.id.in_(source_ids)))
            ).all()
        }
        if source_ids
        else {}
    )
    entity_ids = {p.entity_id for p, _, _ in positions.values() if p.entity_id is not None} | {
        m.entity_id for m in firsts.values() if m.entity_id is not None
    }
    entity_names = (
        {
            e.id: e.name
            for e in (await session.scalars(select(Entity).where(Entity.id.in_(entity_ids)))).all()
        }
        if entity_ids
        else {}
    )
    records: list[Record] = []
    for key in keys:
        device_id, t = key
        found = positions.get(key)
        first = firsts.get(key)
        owner = found[0] if found else first
        records.append(
            Record(
                time=t,
                device_id=device_id,
                device_name=device_names.get(device_id),
                entity_id=owner.entity_id if owner else None,
                entity_name=entity_names.get(owner.entity_id)
                if owner and owner.entity_id
                else None,
                project_id=owner.project_id if owner else None,
                position=found[0] if found else None,
                lat=found[1] if found else None,
                lon=found[2] if found else None,
                measurements=measurements.get(key, {}),
                state=state_of(states.get(key), found[0] if found else None),
                source_event_id=owner.source_event_id if owner else None,
                source_event_ingested_at=owner.source_event_ingested_at if owner else None,
                trace_id=owner.trace_id if owner else None,
                device_type=device_types.get(device_id),
                data_source_id=owner.data_source_id if owner else None,
                data_source_name=source_names.get(owner.data_source_id)
                if owner and owner.data_source_id
                else None,
                kinds=[
                    kind
                    for kind, present in (
                        ("position", found is not None),
                        ("measurement", key in measurements),
                        ("state", key in states),
                    )
                    if present
                ],
                record_type=found[0].record_type if found else None,
            )
        )
    return records
