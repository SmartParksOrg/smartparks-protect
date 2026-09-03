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


async def flush_or_409(session: AsyncSession, what: str) -> None:
    """Flush and turn a constraint violation into a 409 with a readable message."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        message = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
        raise HTTPException(status.HTTP_409_CONFLICT, f"{what}: {message}") from None
