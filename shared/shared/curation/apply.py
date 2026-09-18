"""Applying and reverting one correction (architecture 28.2, 28.6, 28.8 to 28.10).

Only the curatable fields exist here (28.3). A correction stores the effective value before
it and the value it sets; applying writes the overlay column, reruns the attribution when the
time moved, bumps the record's curation version, flags outbound deliveries of the record as
stale and recomputes the current state of the device and the entities involved. Reverting
restores the value before the correction; a correction on a field that already carried an
active one supersedes it, and reverting the newer one brings the older one back.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.connectivity.network_location import NETWORK_RECORD_TYPE
from shared.curation.effective import effective_time, effective_value_num, visible
from shared.domain.assignments import resolve_attribution
from shared.domain.static_place import placed_device_of, stamp_static_place
from shared.enums import (
    CorrectionStatus,
    CurationField,
    CurationTarget,
    DeliveryStatus,
    ErrorCode,
    LocationSource,
)
from shared.models import (
    DataCorrection,
    Device,
    DeviceCurrentState,
    Entity,
    EntityCurrentState,
    IntegrationDelivery,
    Measurement,
    Position,
)
from shared.timeutil import require_aware, utc_now
from shared.trace import ApplicationError

CURATABLE: dict[CurationTarget, frozenset[CurationField]] = {
    CurationTarget.POSITION: frozenset(
        {CurationField.TIME, CurationField.COORDINATES, CurationField.VALID}
    ),
    CurationTarget.MEASUREMENT: frozenset(
        {CurationField.TIME, CurationField.VALUE, CurationField.VALID}
    ),
}
Record = Position | Measurement


def _error(message: str, code: ErrorCode = ErrorCode.CANONICALIZATION_FAILED) -> ApplicationError:
    return ApplicationError(code=code, message=message, component="curation", user_actionable=True)


def model_for(target_type: str) -> type[Position] | type[Measurement]:
    return Position if target_type == CurationTarget.POSITION else Measurement


async def load_record(
    session: AsyncSession, target_type: str, target_id: int, target_time: datetime
) -> Record | None:
    model = model_for(target_type)
    record: Record | None = await session.scalar(
        select(model).where(model.id == target_id, model.time == require_aware(target_time))
    )
    return record


def _point_json(geom: Any) -> dict[str, float]:
    shape = to_shape(geom)
    return {"latitude": shape.y, "longitude": shape.x}


def effective_of(record: Record, field_name: str) -> Any:
    """The current effective value of a curatable field, as JSON."""
    if field_name == CurationField.TIME:
        return (record.curated_time or record.time).isoformat()
    if field_name == CurationField.VALID:
        return bool(record.valid)
    if field_name == CurationField.COORDINATES:
        assert isinstance(record, Position)
        return _point_json(record.curated_geom if record.curated_geom is not None else record.geom)
    assert isinstance(record, Measurement)
    return record.curated_value_num if record.curated_value_num is not None else record.value_num


def original_of(record: Record, field_name: str) -> Any:
    if field_name == CurationField.TIME:
        return record.time.isoformat()
    if field_name == CurationField.VALID:
        return True
    if field_name == CurationField.COORDINATES:
        assert isinstance(record, Position)
        return _point_json(record.geom)
    assert isinstance(record, Measurement)
    return record.value_num


def normalize_value(target_type: str, field_name: str, value: Any) -> Any:
    """Validate a proposed value for a field and return its JSON form."""
    allowed = CURATABLE[CurationTarget(target_type)]
    if CurationField(field_name) not in allowed:
        raise _error(f"{field_name} is not curatable on a {target_type}")
    if field_name == CurationField.TIME:
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            return require_aware(parsed).isoformat()
        except (TypeError, ValueError) as exc:
            raise _error(f"time must be an ISO 8601 timestamp with offset: {exc}") from None
    if field_name == CurationField.VALID:
        if not isinstance(value, bool):
            raise _error("valid must be true or false")
        return value
    if field_name == CurationField.COORDINATES:
        if not isinstance(value, dict):
            raise _error("coordinates must be an object with latitude and longitude")
        try:
            lat, lon = float(value["latitude"]), float(value["longitude"])
        except (KeyError, TypeError, ValueError):
            raise _error("coordinates must be an object with latitude and longitude") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise _error("coordinates out of range")
        return {"latitude": lat, "longitude": lon}
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _error("value must be a number")
    return float(value)


def _write(record: Record, field_name: str, value: Any, *, original: Any) -> None:
    """Set the overlay column; a value equal to the original clears it."""
    same = value == original
    if field_name == CurationField.TIME:
        record.curated_time = None if same else datetime.fromisoformat(str(value))
    elif field_name == CurationField.VALID:
        record.valid = bool(value)
        same = bool(value) is True
    elif field_name == CurationField.COORDINATES:
        assert isinstance(record, Position)
        record.curated_geom = (
            None if same else from_shape(Point(value["longitude"], value["latitude"]), srid=4326)
        )
    else:
        assert isinstance(record, Measurement)
        record.curated_value_num = None if same else float(value)
    fields = [f for f in (record.curated_fields or []) if f != field_name]
    if not same:
        fields.append(field_name)
    record.curated_fields = fields
    record.curation_version = int(record.curation_version or 1) + 1


@dataclass(slots=True)
class Applied:
    correction: DataCorrection
    device_id: uuid.UUID
    entity_ids: set[uuid.UUID | None] = field(default_factory=set)
    deliveries_flagged: int = 0


async def _rerun_attribution(session: AsyncSession, record: Record, impact: dict[str, Any]) -> None:
    """Timestamp corrections rerun the historical assignment resolution (architecture 28.9)."""
    at = record.curated_time or record.time
    attribution = await resolve_attribution(session, record.device_id, at)
    impact["attribution"] = {
        "before": {
            "project_id": str(record.project_id) if record.project_id else None,
            "entity_id": str(record.entity_id) if record.entity_id else None,
        },
        "after": {
            "project_id": str(attribution.project_id) if attribution.project_id else None,
            "entity_id": str(attribution.entity_id) if attribution.entity_id else None,
        },
    }
    record.project_id = attribution.project_id
    record.entity_id = attribution.entity_id


async def flag_deliveries(
    session: AsyncSession, target_type: str, target_id: int, reason: str
) -> int:
    """Outbound deliveries of the record that already reached a target may now be stale
    (architecture 28.10); they are flagged for review, never resent silently."""
    result = await session.execute(
        update(IntegrationDelivery)
        .where(
            IntegrationDelivery.object_type == target_type,
            IntegrationDelivery.object_id == str(target_id),
            IntegrationDelivery.status == DeliveryStatus.SENT,
            IntegrationDelivery.stale_at.is_(None),
        )
        .values(stale_at=utc_now(), stale_reason=reason[:128])
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def apply_correction(
    session: AsyncSession, correction: DataCorrection, *, flag: bool = True
) -> Applied:
    """Write the correction into the record. The caller commits."""
    record = await load_record(
        session, correction.target_type, correction.target_id, correction.target_time
    )
    if record is None:
        raise _error(
            f"{correction.target_type} {correction.target_id} no longer exists",
            ErrorCode.DEVICE_NOT_FOUND,
        )
    field_name = correction.field
    value = normalize_value(correction.target_type, field_name, correction.corrected_value)
    active = await session.scalar(
        select(DataCorrection).where(
            DataCorrection.target_type == correction.target_type,
            DataCorrection.target_id == correction.target_id,
            DataCorrection.target_time == correction.target_time,
            DataCorrection.field == field_name,
            DataCorrection.status == CorrectionStatus.ACTIVE,
            DataCorrection.id != correction.id,
        )
    )
    if active is not None:
        active.status = CorrectionStatus.SUPERSEDED
        correction.supersedes_id = active.id
    correction.original_value = effective_of(record, field_name)
    correction.corrected_value = value
    impact: dict[str, Any] = dict(correction.impact or {})
    _write(record, field_name, value, original=original_of(record, field_name))
    applied = Applied(correction=correction, device_id=record.device_id)
    applied.entity_ids.add(record.entity_id)
    if field_name == CurationField.TIME:
        await _rerun_attribution(session, record, impact)
        applied.entity_ids.add(record.entity_id)
    if flag:
        applied.deliveries_flagged = await flag_deliveries(
            session,
            correction.target_type,
            correction.target_id,
            f"{field_name} corrected ({correction.reason_code})",
        )
        impact["deliveries_flagged"] = applied.deliveries_flagged
    correction.impact = impact
    correction.status = CorrectionStatus.ACTIVE
    correction.applied_at = utc_now()
    await session.flush()
    return applied


async def revert_correction(
    session: AsyncSession,
    correction: DataCorrection,
    *,
    user_id: uuid.UUID | None,
    comment: str | None,
) -> Applied:
    """Restore the value before the correction. Refused when a newer correction on the same
    field is active: revert that one first (the chain pops from the top)."""
    if correction.status != CorrectionStatus.ACTIVE:
        raise _error(f"only an active correction can be reverted (this one is {correction.status})")
    newer = await session.scalar(
        select(DataCorrection.id).where(
            DataCorrection.supersedes_id == correction.id,
            DataCorrection.status == CorrectionStatus.ACTIVE,
        )
    )
    if newer is not None:
        raise _error("a newer correction on this field is active; revert that one first")
    record = await load_record(
        session, correction.target_type, correction.target_id, correction.target_time
    )
    if record is None:
        raise _error(f"{correction.target_type} {correction.target_id} no longer exists")
    field_name = correction.field
    _write(record, field_name, correction.original_value, original=original_of(record, field_name))
    applied = Applied(correction=correction, device_id=record.device_id)
    applied.entity_ids.add(record.entity_id)
    if field_name == CurationField.TIME:
        before = (correction.impact or {}).get("attribution", {}).get("before")
        if before:
            record.project_id = uuid.UUID(before["project_id"]) if before["project_id"] else None
            record.entity_id = uuid.UUID(before["entity_id"]) if before["entity_id"] else None
        else:
            await _rerun_attribution(session, record, {})
        applied.entity_ids.add(record.entity_id)
    if correction.supersedes_id is not None:
        older = await session.get(DataCorrection, correction.supersedes_id)
        if older is not None and older.status == CorrectionStatus.SUPERSEDED:
            older.status = CorrectionStatus.ACTIVE
    applied.deliveries_flagged = await flag_deliveries(
        session, correction.target_type, correction.target_id, f"{field_name} correction reverted"
    )
    correction.status = CorrectionStatus.REVERTED
    correction.reverted_at = utc_now()
    correction.reverted_by_user_id = user_id
    correction.revert_comment = comment
    await session.flush()
    return applied


async def recompute_current_state(
    session: AsyncSession, device_id: uuid.UUID | None, entity_ids: set[uuid.UUID | None]
) -> None:
    """The current position of the device and of every entity touched, rebuilt from the rows
    by effective time (architecture 28.8) under the location source rules of decision D164:
    the newest device fix, or a network estimate when the setting lets it stand in; the kind,
    the newest fix time and the accuracy travel with it (D193). Last seen follows the
    effective times as well: a time correction (a device clock ahead, decision D119) must
    move it back with the records."""
    device_state = (
        await session.get(DeviceCurrentState, device_id) if device_id is not None else None
    )
    if device_state is not None and device_id is not None:
        device = await session.get(Device, device_id)
        fix = await _newest_position(session, Position.device_id == device_id, network=False)
        estimate = await _newest_position(session, Position.device_id == device_id, network=True)
        _rebuild_position(
            device_state,
            fix,
            estimate,
            device.location_source if device else LocationSource.DEVICE,
            device.location_fallback_hours if device else 24,
        )
        last_measurement = await session.scalar(
            select(func.max(effective_time(Measurement))).where(
                Measurement.device_id == device_id, visible(Measurement)
            )
        )
        # the newest value per metric, the health card's figures (decision D104): a time
        # correction that brings a device's status records back from the future must show them
        if last_measurement is not None:
            device_state.latest_measurements = await _latest_measurements(
                session, device_id, last_measurement
            )
            battery = device_state.latest_measurements.get("battery_voltage")
            if isinstance(battery, dict) and isinstance(battery.get("value"), int | float):
                device_state.battery_voltage = float(battery["value"])
        seen = [
            t
            for t in (
                fix.time if fix else None,
                estimate.time if estimate else None,
                last_measurement,
                device_state.latest_state_time,
            )
            if t is not None
        ]
        device_state.last_seen_at = max(seen) if seen else None
        # a place set by hand is not a record, so no rebuild from the rows can find it
        # (decision D261); without this an attribution job blanks every placed device
        if device is not None:
            stamp_static_place(device_state, device)
        device_state.updated_at = utc_now()
    # rows added earlier in this transaction (the decoder's) must be visible to `get`
    await session.flush()
    for entity_id in entity_ids:
        if entity_id is None:
            continue
        entity = await session.get(Entity, entity_id)
        if entity is None:
            continue
        fix = await _newest_position(session, Position.entity_id == entity_id, network=False)
        estimate = await _newest_position(session, Position.entity_id == entity_id, network=True)
        entity_state = await session.get(EntityCurrentState, entity_id)
        if entity_state is None:
            # An entity that never received a record while assigned has no row yet; the
            # repair that gives it history must also give it a place on the map.
            entity_state = EntityCurrentState(entity_id=entity_id, project_id=entity.project_id)
            session.add(entity_state)
        chosen = _rebuild_position(
            entity_state, fix, estimate, entity.location_source, entity.location_fallback_hours
        )
        if chosen is not None:
            entity_state.device_id = chosen.device_id
        last_measurement = await session.scalar(
            select(func.max(effective_time(Measurement))).where(
                Measurement.entity_id == entity_id, visible(Measurement)
            )
        )
        seen = [
            t
            for t in (
                fix.time if fix else None,
                estimate.time if estimate else None,
                last_measurement,
            )
            if t is not None
        ]
        entity_state.last_seen_at = max(seen) if seen else None
        placed = await placed_device_of(session, entity_id)
        if placed is not None:
            stamp_static_place(entity_state, placed)
            entity_state.device_id = placed.id
        entity_state.updated_at = utc_now()
    await session.flush()


@dataclass(frozen=True)
class _Newest:
    """The newest visible position of one kind: where it is, when, whose, how accurate."""

    geom: Any
    time: datetime
    device_id: uuid.UUID
    accuracy_m: float | None


#: The newest value per metric is looked for within this long before the device's newest
#: measurement, so the scan stays bounded on a device with years of rows.
LATEST_WINDOW = timedelta(days=30)


async def _latest_measurements(
    session: AsyncSession, device_id: uuid.UUID, newest: datetime
) -> dict[str, Any]:
    """The newest visible value per metric by effective time, in the shape the decoder keeps
    (`{key: {"value", "time"}}`), from the month before the device's newest measurement."""
    when = effective_time(Measurement)
    rows = (
        await session.execute(
            select(
                Measurement.metric_key,
                when.label("at"),
                effective_value_num().label("num"),
                Measurement.value_bool,
                Measurement.value_text,
                Measurement.value_json,
            )
            .where(
                Measurement.device_id == device_id,
                visible(Measurement),
                when > newest - LATEST_WINDOW,
                when <= newest,
            )
            .distinct(Measurement.metric_key)
            .order_by(Measurement.metric_key, when.desc())
        )
    ).all()
    latest: dict[str, Any] = {}
    for row in rows:
        value: Any = row.num
        if value is None:
            value = (
                row.value_bool
                if row.value_bool is not None
                else row.value_text
                if row.value_text is not None
                else row.value_json
            )
        latest[row.metric_key] = {"value": value, "time": row.at.isoformat()}
    return latest


async def _newest_position(session: AsyncSession, owner: Any, *, network: bool) -> _Newest | None:
    kind = (
        Position.record_type == NETWORK_RECORD_TYPE
        if network
        else Position.record_type != NETWORK_RECORD_TYPE
    )
    row = (
        await session.execute(
            select(
                Position.geom,
                Position.curated_geom,
                effective_time(Position),
                Position.device_id,
                Position.accuracy_m,
            )
            .where(owner, kind, visible(Position))
            .order_by(effective_time(Position).desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return _Newest(
        geom=row[1] if row[1] is not None else row[0],
        time=row[2],
        device_id=row[3],
        accuracy_m=row[4],
    )


def _rebuild_position(
    state: DeviceCurrentState | EntityCurrentState,
    fix: _Newest | None,
    estimate: _Newest | None,
    location_source: str,
    fallback_hours: int,
) -> _Newest | None:
    """The decoder's rule (D164) applied to a rebuild from the rows: the newest device fix,
    unless the setting lets a newer network estimate stand in (always for `network`, after the
    fallback period without a fix for `device_else_network`). Returns what became current."""
    chosen: _Newest | None = fix
    kind: str | None = "device" if fix else None
    if estimate is not None and location_source != LocationSource.DEVICE:
        newer = fix is None or estimate.time > fix.time
        stale_fix = fix is None or (estimate.time - fix.time) > timedelta(
            hours=max(0, fallback_hours)
        )
        if newer and (location_source == LocationSource.NETWORK or stale_fix):
            chosen, kind = estimate, NETWORK_RECORD_TYPE
    state.latest_fix_time = fix.time if fix else None
    if chosen is None:
        state.latest_position = None
        state.latest_position_time = None
        state.latest_position_kind = None
        state.latest_accuracy_m = None
        return None
    state.latest_position = chosen.geom
    state.latest_position_time = chosen.time
    state.latest_position_kind = kind
    state.latest_accuracy_m = chosen.accuracy_m
    return chosen
