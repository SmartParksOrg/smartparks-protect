"""Backup and recovery health (architecture 28.11 and 28.12): one assessment shared by the
Backup and recovery page (API) and the system checks that raise alerts (rules service). The
facts come from `backup_runs`, written by the host scripts, and from PostgreSQL's own
`pg_stat_archiver`, which says whether WAL segments still reach the repository."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.enums import BackupKind, BackupStatus
from shared.models import BackupRun
from shared.timeutil import utc_now

RPO_SECONDS = 3600
RTO_SECONDS = 4 * 3600

ITEM_LABELS = {
    "database": "Database backup",
    "wal": "WAL archive (point in time)",
    "objects": "Object backup",
    "offsite": "Off-server copy",
    "integrity": "Object integrity check",
    "restore_test": "Last restore test",
}


@dataclass(slots=True)
class HealthItem:
    key: str
    label: str
    status: str  # ok, stale, failed, off
    detail: str
    at: datetime | None = None


@dataclass(slots=True)
class BackupHealth:
    enabled: bool
    overall: str
    items: list[HealthItem]
    recovery_point_seconds: int | None
    wal: dict[str, Any] = field(default_factory=dict)
    latest: dict[str, BackupRun] = field(default_factory=dict)


async def latest_runs(session: AsyncSession) -> dict[str, BackupRun]:
    result: dict[str, BackupRun] = {}
    for kind in BackupKind:
        run = await session.scalar(
            select(BackupRun)
            .where(BackupRun.kind == kind)
            .order_by(BackupRun.started_at.desc())
            .limit(1)
        )
        if run is not None:
            result[kind.value] = run
    return result


async def wal_archiver(session: AsyncSession) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT current_setting('archive_mode') AS archive_mode, archived_count, "
                    "last_archived_wal, last_archived_time, failed_count, last_failed_wal, "
                    "last_failed_time FROM pg_stat_archiver"
                )
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


def _ago(at: datetime | None, now: datetime) -> str:
    if at is None:
        return "never"
    seconds = int((now - at).total_seconds())
    if seconds < 120:
        return f"{seconds} seconds ago"
    if seconds < 7200:
        return f"{seconds // 60} minutes ago"
    if seconds < 172_800:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86_400} days ago"


def _size(size: int | None) -> str:
    if not size:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f", {value:.0f} {unit}" if unit == "B" else f", {value:.1f} {unit}"
        value = value / 1024
    return ""


def _run_item(
    key: str, run: BackupRun | None, max_age: timedelta, now: datetime, what: str
) -> HealthItem:
    label = ITEM_LABELS[key]
    if run is None:
        return HealthItem(key, label, "stale", f"No {what} recorded yet")
    if run.status == BackupStatus.FAILED:
        return HealthItem(
            key,
            label,
            "failed",
            f"Failed {_ago(run.finished_at, now)}: {run.error or ''}"[:300],
            run.finished_at,
        )
    if now - run.finished_at > max_age:
        return HealthItem(
            key, label, "stale", f"Last success {_ago(run.finished_at, now)}", run.finished_at
        )
    kind = run.kind.replace("database_", "").replace("_", " ")
    return HealthItem(
        key,
        label,
        "ok",
        f"OK, {kind if key == 'database' else what} {_ago(run.finished_at, now)}"
        f"{_size(run.size_bytes)}",
        run.finished_at,
    )


async def assess(session: AsyncSession) -> BackupHealth:
    settings = get_settings()
    now = utc_now()
    latest = await latest_runs(session)
    wal = await wal_archiver(session)
    if not settings.backup_enabled:
        return BackupHealth(
            enabled=False,
            overall="off",
            items=[
                HealthItem(key, label, "off", "Backups are not enabled on this server")
                for key, label in ITEM_LABELS.items()
            ],
            recovery_point_seconds=None,
            wal=wal,
            latest=latest,
        )
    stale_after = timedelta(hours=settings.backup_stale_hours)
    database_runs = [
        r for k, r in latest.items() if k in (BackupKind.DATABASE_FULL, BackupKind.DATABASE_INCR)
    ]
    newest_database = max(database_runs, key=lambda r: r.started_at) if database_runs else None
    items = [_run_item("database", newest_database, stale_after, now, "database backup")]

    archived_at: datetime | None = wal.get("last_archived_time")
    failed_at: datetime | None = wal.get("last_failed_time")
    if wal.get("archive_mode") != "on":
        items.append(HealthItem("wal", ITEM_LABELS["wal"], "failed", "archive_mode is off"))
    elif failed_at is not None and (archived_at is None or failed_at > archived_at):
        items.append(
            HealthItem(
                "wal",
                ITEM_LABELS["wal"],
                "failed",
                f"Archiving fails since {_ago(failed_at, now)} "
                f"({wal.get('failed_count')} failures)",
                failed_at,
            )
        )
    elif archived_at is None or now - archived_at > timedelta(
        minutes=settings.wal_archive_stale_minutes
    ):
        items.append(
            HealthItem(
                "wal",
                ITEM_LABELS["wal"],
                "stale",
                f"Last segment archived {_ago(archived_at, now)}",
                archived_at,
            )
        )
    else:
        items.append(
            HealthItem(
                "wal",
                ITEM_LABELS["wal"],
                "ok",
                f"Healthy, last segment {_ago(archived_at, now)}",
                archived_at,
            )
        )

    items.append(
        _run_item(
            "objects", latest.get(BackupKind.OBJECT_MIRROR), stale_after, now, "object mirror"
        )
    )
    if settings.backup_repo_type != "s3":
        items.append(
            HealthItem(
                "offsite",
                ITEM_LABELS["offsite"],
                "failed",
                f"The repository type is {settings.backup_repo_type}: on this server, "
                "not off-server",
            )
        )
    else:
        copies_ok = all(i.status == "ok" for i in items if i.key in ("database", "wal", "objects"))
        items.append(
            HealthItem(
                "offsite",
                ITEM_LABELS["offsite"],
                "ok" if copies_ok else "stale",
                "Healthy" if copies_ok else "Waiting for the database, WAL and object copies above",
            )
        )
    items.append(
        _run_item(
            "integrity", latest.get(BackupKind.INTEGRITY_CHECK), stale_after, now, "integrity check"
        )
    )
    items.append(
        _run_item(
            "restore_test",
            latest.get(BackupKind.RESTORE_TEST),
            timedelta(days=settings.restore_test_stale_days),
            now,
            "restore test",
        )
    )
    statuses = {i.status for i in items}
    overall = "failed" if "failed" in statuses else "stale" if "stale" in statuses else "ok"
    recovery_point = int((now - archived_at).total_seconds()) if archived_at is not None else None
    return BackupHealth(
        enabled=True,
        overall=overall,
        items=items,
        recovery_point_seconds=recovery_point,
        wal=wal,
        latest=latest,
    )
