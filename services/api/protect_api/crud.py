"""Small helpers shared by the admin routers."""

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from pydantic import BaseModel
from shapely.geometry import mapping, shape
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_404[T](session: AsyncSession, model: type[T], id_: Any, what: str) -> T:
    obj = await session.get(model, id_)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return obj


def range_bounds(validity: Range[datetime]) -> tuple[datetime, datetime | None]:
    """Lower and upper bound of a `[start, end)` validity range. The lower bound always exists."""
    lower = validity.lower
    if lower is None:
        raise ValueError("validity range without a lower bound")
    return lower, validity.upper


def apply_patch(obj: Any, patch: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """Set the fields present in the patch. Returns what changed, for the audit log."""
    changed: dict[str, Any] = {}
    for key, value in patch.model_dump(exclude_unset=True, exclude=exclude).items():
        if getattr(obj, key) != value:
            setattr(obj, key, value)
            changed[key] = _jsonable(value)
    return changed


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    return json.loads(json.dumps(value, default=str))


def geojson_to_geom(geometry: dict[str, Any] | None) -> WKBElement | None:
    if geometry is None:
        return None
    try:
        return from_shape(shape(geometry), srid=4326)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid geometry: {exc}"
        ) from exc


def geom_to_geojson(geom: WKBElement | None) -> dict[str, Any] | None:
    if geom is None:
        return None
    return dict(mapping(to_shape(geom)))


#: The constraints a person runs into by name, in words (Tim, 2026-10-19: a rename answered
#: with the database's own line about `devices_name_key`, which said nothing to him).
CONSTRAINT_WORDS: dict[str, str] = {
    "devices_name_key": "a device with this name exists already; device names are unique "
    "across the server",
    "devices_serial_number_key": "a device with this serial number exists already",
    "uq_entities_project_name": "an entity with this name exists in the project already",
    "uq_features_project_name": "a feature with this name exists in the project already",
    "uq_groups_project_name": "a group with this name exists in the project already",
}


async def flush_or_409(session: AsyncSession, what: str) -> None:
    """Flush and turn a constraint violation into a 409 with a readable message: the
    constraint's words when it is one a person runs into, else the database's first line."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        message = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
        for constraint, words in CONSTRAINT_WORDS.items():
            if constraint in message:
                message = words
                break
        raise HTTPException(status.HTTP_409_CONFLICT, f"{what}: {message}") from None
