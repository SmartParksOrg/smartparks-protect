"""Bounded lists (architecture 13.10).

Every list endpoint takes `Page` and returns a `PageResponse`. The cursor is the key of the last
item of the previous page; rows are ordered by that key. A test asserts that no list endpoint lacks
the dependency, so an unbounded endpoint cannot be added by accident.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class Page:
    limit: int
    cursor: str | None


def page(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None, description="key of the last item of the previous page"),
) -> Page:
    return Page(limit=limit, cursor=cursor)


class PageResponse[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


async def paginate(
    session: AsyncSession,
    key: InstrumentedAttribute[Any],
    statement: Select[Any],
    page: Page,
) -> tuple[list[Any], str | None]:
    """Apply the cursor and limit to a statement returning rows of the model that owns `key`."""
    if page.cursor is not None:
        statement = statement.where(key > _parse_cursor(key, page.cursor))
    statement = statement.order_by(key).limit(page.limit + 1)
    rows = list((await session.execute(statement)).scalars().all())
    next_cursor = str(getattr(rows[page.limit - 1], key.key)) if len(rows) > page.limit else None
    return rows[: page.limit], next_cursor


def _parse_cursor(key: InstrumentedAttribute[Any], cursor: str) -> Any:
    if key.type.python_type is uuid.UUID:
        try:
            return uuid.UUID(cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
    return cursor
