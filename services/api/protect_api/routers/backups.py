"""Backup and recovery for server admins (architecture 28.11): the status the page shows and
the history of runs. Runs are written by the host scripts through `protect_api.backup`."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.deps import require_server_admin
from protect_api.schemas.backup import BackupItem, BackupRunRead, BackupStatusRead
from shared.backup import RPO_SECONDS, RTO_SECONDS, assess
from shared.database import get_session
from shared.models import BackupRun

router = APIRouter(
    prefix="/admin/backups", tags=["backups"], dependencies=[Depends(require_server_admin)]
)


@router.get("/status", response_model=BackupStatusRead)
async def backup_status(session: AsyncSession = Depends(get_session)) -> BackupStatusRead:
    health = await assess(session)
    return BackupStatusRead(
        enabled=health.enabled,
        overall=health.overall,
        items=[
            BackupItem(key=i.key, label=i.label, status=i.status, detail=i.detail, at=i.at)
            for i in health.items
        ],
        recovery_point_seconds=health.recovery_point_seconds,
        rpo_seconds=RPO_SECONDS,
        rto_seconds=RTO_SECONDS,
        wal={k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in health.wal.items()},
        latest={k: BackupRunRead.model_validate(r) for k, r in health.latest.items()},
    )


@router.get("/runs", response_model=list[BackupRunRead])
async def backup_runs(
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[BackupRunRead]:
    """Newest first."""
    statement = select(BackupRun).order_by(BackupRun.started_at.desc()).limit(limit)
    if kind is not None:
        statement = statement.where(BackupRun.kind == kind)
    rows = await session.scalars(statement)
    return [BackupRunRead.model_validate(r) for r in rows]
