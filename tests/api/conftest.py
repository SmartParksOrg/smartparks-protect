"""API test helpers: a client against the app, committed fixture rows, tokens per role."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from protect_api.main import app
from shared.enums import Role
from shared.models import Invitation, Project, ProjectMembership, User
from tests.conftest import unique_name

PASSWORD = "correct-horse-battery"
_password_helper = PasswordHelper()


@pytest_asyncio.fixture
async def client(migrated_database: str) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A committing session for fixture data. The test database is dropped at the end."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@dataclass
class Actor:
    user: User
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def create_user(
    db: AsyncSession, *, superuser: bool = False, email: str | None = None
) -> User:
    user = User(
        email=email or f"{unique_name('user')}@example.org",
        hashed_password=_password_helper.hash(PASSWORD),
        is_active=True,
        is_superuser=superuser,
        is_verified=True,
    )
    db.add(user)
    await db.commit()
    return user


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def actor(client: AsyncClient, db: AsyncSession, *, superuser: bool = False) -> Actor:
    user = await create_user(db, superuser=superuser)
    return Actor(user=user, token=await login(client, user.email))


async def create_project(db: AsyncSession, name: str | None = None) -> Project:
    project = Project(name=name or unique_name("Project"), slug=unique_name("project"))
    db.add(project)
    await db.commit()
    return project


async def add_member(db: AsyncSession, user: User, project: Project, role: Role) -> None:
    db.add(ProjectMembership(user_id=user.id, project_id=project.id, role=role))
    await db.commit()


async def project_actor(
    client: AsyncClient, db: AsyncSession, project: Project, role: Role
) -> Actor:
    user = await create_user(db)
    await add_member(db, user, project, role)
    return Actor(user=user, token=await login(client, user.email))


async def create_invitation(
    db: AsyncSession,
    *,
    email: str,
    project: Project | None = None,
    role: Role | None = None,
    server_admin: bool = False,
    expired: bool = False,
) -> Invitation:
    invitation = Invitation(
        email=email,
        project_id=project.id if project else None,
        role=role,
        server_admin=server_admin,
        token=uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=-1 if expired else 7),
    )
    db.add(invitation)
    await db.commit()
    return invitation
