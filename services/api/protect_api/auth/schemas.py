import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr, Field


class UserRead(schemas.BaseUser[uuid.UUID]):
    full_name: str | None
    timezone: str
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(schemas.BaseUserCreate):
    full_name: str | None = None
    timezone: str = "UTC"


class UserUpdate(schemas.BaseUserUpdate):
    full_name: str | None = None
    timezone: str | None = None


class RegisterRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    password: str = Field(min_length=10, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)
    timezone: str = "UTC"


class InvitationInfo(BaseModel):
    email: EmailStr
    server_admin: bool
    role: str | None
    project_id: uuid.UUID | None
    project_name: str | None
    expires_at: datetime


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
