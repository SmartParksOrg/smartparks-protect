"""Async SQLAlchemy engine and session factory.

There is one async engine per process. Services get a session through `get_session`, which is a
FastAPI dependency and also usable as `async with session_scope() as session:` in workers.
Migrations (Alembic, phase 1) use their own synchronous engine and do not import this module.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from shared.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model in `shared.models`."""


@lru_cache
def get_engine() -> AsyncEngine:
    """The process's engine. With `STATEMENT_TIMEOUT_SECONDS` set (the API service, decision
    D147) every connection carries PostgreSQL's `statement_timeout`, so a request the proxy has
    given up on does not run on in the database for half an hour."""
    settings = get_settings()
    server_settings: dict[str, str] = {}
    if settings.statement_timeout_seconds:
        server_settings["statement_timeout"] = str(settings.statement_timeout_seconds * 1000)
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"server_settings": server_settings} if server_settings else {},
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, closed when the request ends."""
    async with session_scope() as session:
        yield session
