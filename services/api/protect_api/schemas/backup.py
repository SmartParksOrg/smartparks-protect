from datetime import datetime
from typing import Any

from pydantic import BaseModel

from protect_api.schemas.common import ORMModel


class BackupRunRead(ORMModel):
    id: int
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: int
    size_bytes: int | None
    label: str | None
    host: str | None
    details: dict[str, Any]
    error: str | None


class BackupItem(BaseModel):
    key: str
    label: str
    status: str
    detail: str
    at: datetime | None


class BackupStatusRead(BaseModel):
    """The Backup and recovery status of architecture 28.11."""

    enabled: bool
    overall: str
    items: list[BackupItem]
    recovery_point_seconds: int | None
    rpo_seconds: int
    rto_seconds: int
    wal: dict[str, Any]
    latest: dict[str, BackupRunRead]
