"""FastAPI-Users wiring: user database adapter, JWT strategy, backend, current-user dependencies."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import jwt
from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.jwt import decode_jwt, generate_jwt
from fastapi_users.manager import BaseUserManager
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.auth.manager import UserManager
from shared.config import get_settings
from shared.database import get_session
from shared.models import User

# The ORM model satisfies UserProtocol at runtime, but its columns are `Mapped` descriptors and
# mypy does not apply descriptors when checking protocol attributes. Hence the ignores below.
UserDatabase = SQLAlchemyUserDatabase[User, uuid.UUID]  # type: ignore[type-var]


async def get_user_db(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[UserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)  # type: ignore[type-var]


async def get_user_manager(
    user_db: UserDatabase = Depends(get_user_db),
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


class PasswordChangeAwareJWTStrategy(JWTStrategy[User, uuid.UUID]):  # type: ignore[type-var]
    """Adds an `iat` claim and rejects tokens issued before `user.password_changed_at`, so a
    password change logs out every other session (pattern from AddaxAI Connect). `iat` has whole
    seconds, so the stamp is truncated to seconds where it is written."""

    async def write_token(self, user: User) -> str:
        data = {"sub": str(user.id), "aud": self.token_audience, "iat": datetime.now(UTC)}
        return generate_jwt(data, self.encode_key, self.lifetime_seconds, algorithm=self.algorithm)

    async def read_token(
        self,
        token: str | None,
        user_manager: BaseUserManager[User, uuid.UUID],  # type: ignore[type-var]
    ) -> User | None:
        user = await super().read_token(token, user_manager)
        if user is None or token is None:
            return None
        try:
            data = decode_jwt(
                token, self.decode_key, self.token_audience, algorithms=[self.algorithm]
            )
        except jwt.PyJWTError:
            return None
        issued_at = data.get("iat")
        if issued_at is None:
            return None
        issued = datetime.fromtimestamp(int(issued_at), tz=UTC)
        if user.password_changed_at is not None and issued < user.password_changed_at:
            return None
        return user


def get_jwt_strategy() -> PasswordChangeAwareJWTStrategy:
    settings = get_settings()
    return PasswordChangeAwareJWTStrategy(
        secret=settings.jwt_secret, lifetime_seconds=settings.jwt_lifetime_seconds
    )


bearer_transport = BearerTransport(tokenUrl="/api/v1/auth/login")
auth_backend = AuthenticationBackend(  # type: ignore[type-var]
    name="jwt", transport=bearer_transport, get_strategy=get_jwt_strategy
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])  # type: ignore[type-var]

current_active_user = fastapi_users.current_user(active=True)
