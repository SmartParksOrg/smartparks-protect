"""Shared test setup.

Settings come from the environment; the defaults below match `.env.example` so tests run against
the local compose stack. Tests use their own database (`<name>_test`), created once per session,
migrated up with Alembic, and migrated back down at the end. That makes every test run also a
migration up-and-down test.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

DEFAULTS = {
    "ENVIRONMENT": "test",
    "DATABASE_URL": "postgresql+asyncpg://protect:protect-dev-password@localhost:5432/smartparks_protect",
    "REDIS_URL": "redis://:protect-dev-redis@localhost:6379/0",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ROOT_USER": "protect",
    "MINIO_ROOT_PASSWORD": "protect-dev-minio",
    "JWT_SECRET": "test-secret-that-is-at-least-32-bytes-long",
    "CREDENTIALS_KEY": "test-credentials-key-long-enough",
    "LOG_FORMAT": "text",
}

for key, value in DEFAULTS.items():
    os.environ.setdefault(key, value)

# Every test talks to the test database, never to the development one.
_BASE_URL = os.environ["DATABASE_URL"]
_BASE_NAME = _BASE_URL.rsplit("/", 1)[1]
TEST_DB_NAME = f"{_BASE_NAME}_test"
os.environ["DATABASE_URL"] = _BASE_URL.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
# Tests get Redis database 1, flushed at the start of every session, so streams and heartbeats of
# the development stack (database 0) and of earlier runs never leak into a test.
_REDIS_BASE = os.environ["REDIS_URL"]
os.environ["REDIS_URL"] = _REDIS_BASE.rsplit("/", 1)[0] + "/1"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from alembic import command  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "services" / "api" / "alembic.ini"


def _admin_engine() -> sa.Engine:
    url = _BASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    return sa.create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session", autouse=True)
def clean_redis() -> None:
    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    client.flushdb()
    client.close()


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Create the test database, migrate to head, yield, migrate to base, drop."""
    engine = _admin_engine()
    with engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        connection.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    yield os.environ["DATABASE_URL"]
    command.downgrade(config, "base")
    test_engine = sa.create_engine(
        os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql+psycopg://")
    )
    with test_engine.connect() as connection:
        remaining = connection.execute(
            sa.text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        ).scalar()
    test_engine.dispose()
    with engine.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    engine.dispose()
    # Only alembic_version may survive a downgrade to base.
    assert remaining <= 1, f"downgrade left tables behind: {remaining}"


@pytest_asyncio.fixture
async def session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test."""
    from shared.database import get_engine

    engine = get_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
