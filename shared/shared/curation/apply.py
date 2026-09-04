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
from datetime import datetime
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.curation.effective import effective_time, visible
from shared.domain.assignments import resolve_attribution
from shared.enums import (
    CorrectionStatus,
    CurationField,
    CurationTarget,
    DeliveryStatus,
    ErrorCode,
)
from shared.models import (
    DataCorrection,
    DeviceCurrentState,
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
    session: AsyncSession, device_id: uuid.UUID, entity_ids: set[uuid.UUID | None]
) -> None:
    """Latest valid position by effective time for the device and for every entity touched
    (architecture 28.8)."""
    latest = (
        await session.execute(
            select(Position.geom, Position.curated_geom, effective_time(Position))
            .where(Position.device_id == device_id, visible(Position))
            .order_by(effective_time(Position).desc())
            .limit(1)
        )
    ).first()
    device_state = await session.get(DeviceCurrentState, device_id)
    if device_state is not None:
        if latest is None:
            device_state.latest_position = None
            device_state.latest_position_time = None
        else:
            device_state.latest_position = latest[1] if latest[1] is not None else latest[0]
            device_state.latest_position_time = latest[2]
        device_state.updated_at = utc_now()
    for entity_id in entity_ids:
        if entity_id is None:
            continue
        row = (
            await session.execute(
                select(
                    Position.geom,
                    Position.curated_geom,
                    effective_time(Position),
                    Position.device_id,
                )
                .where(Position.entity_id == entity_id, visible(Position))
                .order_by(effective_time(Position).desc())
                .limit(1)
            )
        ).first()
        entity_state = await session.get(EntityCurrentState, entity_id)
        if entity_state is None:
            continue
        if row is None:
            entity_state.latest_position = None
            entity_state.latest_position_time = None
        else:
            entity_state.latest_position = row[1] if row[1] is not None else row[0]
            entity_state.latest_position_time = row[2]
            entity_state.device_id = row[3]
        entity_state.updated_at = utc_now()
    await session.flush()
