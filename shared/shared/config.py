"""Settings for all services, read from the environment and an optional `.env` file.

Every variable is documented in `.env.example`. Missing required values raise at startup, which is
intended: a service must not start with a half configured environment.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    database_url: str = Field(description="SQLAlchemy async URL, postgresql+asyncpg://...")
    redis_url: str = Field(description="redis://:password@host:port/db")

    minio_endpoint: str = Field(description="host:port of the MinIO API, without scheme")
    minio_root_user: str
    minio_root_password: str
    minio_secure: bool = False
    minio_bucket_uploads: str = "uploads"
    minio_bucket_exports: str = "exports"
    minio_bucket_log_files: str = "device-log-files"

    jwt_secret: str = Field(min_length=32, description="At least 32 bytes, RFC 7518 3.2")
    jwt_lifetime_seconds: int = 3600
    cors_origins: str = "http://localhost:3000"
    public_url: str = Field(
        default="http://localhost:3000", description="Where links in emails point to"
    )
    credentials_key: str = Field(
        min_length=16, description="Key for encrypting data source credentials at rest"
    )
    invitation_lifetime_hours: int = 168

    mail_server: str | None = None
    mail_port: int = 587
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str | None = None
    dev_notify_emails: str = Field(
        default="", description="Comma separated addresses that may be emailed in development"
    )

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @property
    def dev_notify_email_list(self) -> set[str]:
        return {item.strip().lower() for item in self.dev_notify_emails.split(",") if item.strip()}

    @property
    def mail_configured(self) -> bool:
        return all([self.mail_server, self.mail_username, self.mail_password, self.mail_from])

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def minio_url(self) -> str:
        scheme = "https" if self.minio_secure else "http"
        return f"{scheme}://{self.minio_endpoint}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
