"""User manager: password rules, password reset mail, password change stamp."""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin, exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase

from protect_api.mailer import get_mailer
from shared.config import get_settings
from shared.logger import get_logger
from shared.models import User

log = get_logger("api.auth")

MIN_PASSWORD_LENGTH = 10


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):  # type: ignore[type-var]
    def __init__(self, user_db: SQLAlchemyUserDatabase[User, uuid.UUID]) -> None:  # type: ignore[type-var]
        super().__init__(user_db)
        secret = get_settings().jwt_secret
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret

    async def validate_password(self, password: str, user: object) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise exceptions.InvalidPasswordException(
                reason=f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
            )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        await get_mailer().send_password_reset(user.email, token)
        log.info("password reset requested", user_id=str(user.id))

    async def on_after_reset_password(self, user: User, request: Request | None = None) -> None:
        await self.user_db.update(
            user, {"password_changed_at": datetime.now(UTC).replace(microsecond=0)}
        )
        log.info("password reset completed", user_id=str(user.id))

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response: object | None = None,
    ) -> None:
        await self.user_db.update(user, {"last_login_at": datetime.now(UTC)})
