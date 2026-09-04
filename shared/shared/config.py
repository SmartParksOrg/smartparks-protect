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
    documentation_url: str = Field(
        default="https://smartparksorg.github.io/smartparks-protect/",
        description="Documentation site, linked from OAuth metadata and MCP results",
    )
    mcp_public_url: str | None = Field(
        default=None,
        description="Public MCP URL, default PUBLIC_URL plus /mcp; the audience of access tokens",
    )
    api_internal_url: str = Field(
        default="http://localhost:8000", description="Where the MCP service reaches the API"
    )
    oauth_code_lifetime_seconds: int = Field(
        default=300, ge=30, description="Lifetime of an authorization code after consent"
    )
    oauth_consent_lifetime_seconds: int = Field(
        default=600, ge=60, description="How long a pending consent request stays valid"
    )
    oauth_refresh_token_lifetime_days: int = Field(
        default=30, ge=1, description="Lifetime of a refresh token; rotated on every use"
    )

    mail_server: str | None = None
    mail_port: int = 587
    mail_username: str | None = None
    mail_password: str | None = None
    mail_from: str | None = None
    dev_notify_emails: str = Field(
        default="", description="Comma separated addresses that may be emailed in development"
    )
    telegram_bot_token: str | None = Field(
        default=None, description="One bot per installation; chats link to targets with a code"
    )
    webhook_timeout_seconds: float = 10.0

    rules_reload_seconds: int = Field(
        default=10, ge=1, description="How often the rules service re-reads enabled rules"
    )
    system_check_interval_seconds: int = Field(
        default=300, ge=30, description="Interval of the worker, lag and dead-letter checks"
    )
    automation_max_event_age_seconds: int = Field(
        default=21_600,
        description="Default freshness bound of a new automation (architecture 25.8)",
    )

    backup_enabled: bool = Field(
        default=False, description="Backups are scheduled and their health is checked"
    )
    backup_repo_type: str = Field(default="s3", description="pgBackRest repository type")
    backup_s3_endpoint: str | None = None
    backup_s3_secure: bool = True
    backup_s3_bucket: str | None = None
    backup_s3_region: str = "us-east-1"
    backup_s3_key: str | None = None
    backup_s3_key_secret: str | None = None
    backup_object_prefix: str = "objects"
    backup_stale_hours: int = Field(default=26, ge=1)
    restore_test_stale_days: int = Field(default=8, ge=1)
    wal_archive_stale_minutes: int = Field(default=120, ge=5)

    trace_retention_routine_days: int = Field(default=30, ge=1)
    trace_retention_failed_days: int = Field(default=180, ge=1)
    trace_retention_command_days: int = Field(default=365, ge=1)
    trace_retention_audit_days: int = Field(default=730, ge=1)

    bus_maxlen: int = Field(default=100_000, description="Approximate entries kept per topic")
    bus_dead_maxlen: int = Field(default=10_000, description="Entries kept per dead-letter stream")
    bus_max_attempts: int = Field(
        default=5, description="Deliveries before a message is dead-lettered"
    )
    bus_retry_base_seconds: float = Field(
        default=5.0, description="First retry delay, doubles per attempt"
    )
    bus_concurrency: int = Field(
        default=8, ge=1, description="Concurrent lanes per consumer; one device stays in one lane"
    )
    heartbeat_stale_minutes: int = 15
    payload_inline_max_bytes: int = Field(
        default=65_536, description="Bigger raw payloads go to MinIO"
    )
    log_file_max_bytes: int = Field(
        default=64 * 1024 * 1024, description="Largest raw device log file accepted for upload"
    )
    log_file_batch_size: int = Field(
        default=200, ge=1, description="Frames of a log file decoded per transaction"
    )

    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @property
    def dev_notify_email_list(self) -> set[str]:
        return {item.strip().lower() for item in self.dev_notify_emails.split(",") if item.strip()}

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)

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
