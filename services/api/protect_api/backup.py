"""Command line behind scripts/backup.sh and scripts/restore-verify.sh (architecture 28.10,
28.11), run inside the API image where the database and the object stores are reachable:

    python -m protect_api.backup record --kind database_incr --status ok --started ... \\
        --duration 42 [--host h] [--error ...] [--details-stdin]
    python -m protect_api.backup integrity [--dry-run] [--started ...] [--host h]

`record` inserts one `backup_runs` row. With `--details-stdin` it reads JSON from stdin; the
output of `pgbackrest info --output=json` is recognised and summarised. `integrity` checks
that the objects the database references exist in the backup bucket (newest 500 per store
plus totals) and records the result unless `--dry-run`, which only prints it. The exit code
is 1 when objects are missing, so the scripts can fail loudly.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from minio import Minio
from minio.error import S3Error
from sqlalchemy import func, select

from shared.config import get_settings
from shared.database import session_scope
from shared.enums import BackupKind, BackupStatus
from shared.models import BackupRun, ExportJob, SourceEvent
from shared.timeutil import utc_now

SAMPLE = 500


def summarize_pgbackrest_info(
    info: list[dict[str, Any]],
) -> tuple[dict[str, Any], int | None, str | None]:
    """The details, size and label of the newest backup in a pgBackRest info document."""
    stanza = info[0]
    backups = stanza.get("backup") or []
    if not backups:
        return (
            {"stanza_status": stanza.get("status", {}).get("message"), "backup_count": 0},
            None,
            None,
        )
    latest = backups[-1]
    archive = (stanza.get("archive") or [{}])[-1]
    repository = latest.get("info", {}).get("repository", {})
    details = {
        "label": latest.get("label"),
        "type": latest.get("type"),
        "database_bytes": latest.get("info", {}).get("size"),
        "repository_bytes": repository.get("size"),
        "backup_seconds": latest.get("timestamp", {}).get("stop", 0)
        - latest.get("timestamp", {}).get("start", 0),
        "wal_start": latest.get("archive", {}).get("start"),
        "wal_stop": latest.get("archive", {}).get("stop"),
        "archive_min": archive.get("min"),
        "archive_max": archive.get("max"),
        "backup_count": len(backups),
        "stanza_status": stanza.get("status", {}).get("message"),
    }
    return details, repository.get("size"), latest.get("label")


async def record(args: argparse.Namespace) -> int:
    started = datetime.fromisoformat(args.started.replace("Z", "+00:00"))
    details: dict[str, Any] = {}
    size: int | None = None
    label: str | None = None
    if args.details_stdin:
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)
            if (
                isinstance(data, list)
                and data
                and isinstance(data[0], dict)
                and "backup" in data[0]
            ):
                details, size, label = summarize_pgbackrest_info(data)
            elif isinstance(data, dict):
                details = data
    async with session_scope() as session:
        session.add(
            BackupRun(
                kind=BackupKind(args.kind),
                status=BackupStatus(args.status),
                started_at=started,
                finished_at=started + timedelta(seconds=args.duration),
                duration_seconds=args.duration,
                size_bytes=size,
                label=label,
                host=args.host,
                details=details,
                error=args.error,
            )
        )
        await session.commit()
    print(f"recorded {args.kind} {args.status}")
    return 0


def _remote() -> Minio:
    settings = get_settings()
    if not (settings.backup_s3_endpoint and settings.backup_s3_bucket and settings.backup_s3_key):
        raise SystemExit("BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET and BACKUP_S3_KEY are required")
    return Minio(
        settings.backup_s3_endpoint,
        access_key=settings.backup_s3_key,
        secret_key=settings.backup_s3_key_secret,
        secure=settings.backup_s3_secure,
        region=settings.backup_s3_region,
    )


async def integrity(args: argparse.Namespace) -> int:
    settings = get_settings()
    started = (
        datetime.fromisoformat(args.started.replace("Z", "+00:00")) if args.started else utc_now()
    )
    async with session_scope() as session:
        stores: list[tuple[str, list[str], int]] = []
        for bucket, model, column in (
            (settings.minio_bucket_uploads, SourceEvent, SourceEvent.payload_object_key),
            (settings.minio_bucket_exports, ExportJob, ExportJob.object_key),
        ):
            total = await session.scalar(
                select(func.count()).select_from(model).where(column.is_not(None))
            )
            order = (
                SourceEvent.ingested_at.desc()
                if model is SourceEvent
                else ExportJob.created_at.desc()
            )
            keys = [
                key
                for key in await session.scalars(
                    select(column).where(column.is_not(None)).order_by(order).limit(SAMPLE)
                )
                if key is not None
            ]
            stores.append((bucket, keys, int(total or 0)))
    result: dict[str, Any] = {"checked": 0, "missing": 0, "stores": {}, "sample_size": SAMPLE}
    missing_keys: list[str] = []
    remote = _remote()

    def check(bucket: str, keys: list[str]) -> list[str]:
        missing = []
        for key in keys:
            remote_key = f"{settings.backup_object_prefix}/{bucket}/{key}"
            try:
                remote.stat_object(settings.backup_s3_bucket or "", remote_key)
            except S3Error as error:
                if error.code in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
                    missing.append(remote_key)
                else:
                    raise
        return missing

    for bucket, keys, total in stores:
        missing = await asyncio.to_thread(check, bucket, keys)
        result["stores"][bucket] = {
            "referenced": total,
            "checked": len(keys),
            "missing": len(missing),
        }
        result["checked"] += len(keys)
        result["missing"] += len(missing)
        missing_keys.extend(missing)
    result["missing_sample"] = missing_keys[:20]
    ok = result["missing"] == 0
    print(json.dumps(result))
    if not args.dry_run:
        duration = int((datetime.now(UTC) - started).total_seconds())
        async with session_scope() as session:
            session.add(
                BackupRun(
                    kind=BackupKind.INTEGRITY_CHECK,
                    status=BackupStatus.OK if ok else BackupStatus.FAILED,
                    started_at=started,
                    finished_at=started + timedelta(seconds=duration),
                    duration_seconds=duration,
                    host=args.host,
                    details=result,
                    error=None if ok else f"{result['missing']} referenced objects are missing",
                )
            )
            await session.commit()
    return 0 if ok else 1


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="protect_api.backup")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--kind", required=True, choices=[k.value for k in BackupKind])
    rec.add_argument("--status", required=True, choices=[s.value for s in BackupStatus])
    rec.add_argument("--started", required=True, help="ISO 8601")
    rec.add_argument("--duration", required=True, type=int, help="seconds")
    rec.add_argument("--host")
    rec.add_argument("--error")
    rec.add_argument("--details-stdin", action="store_true")
    integ = sub.add_parser("integrity")
    integ.add_argument("--dry-run", action="store_true", help="print the result, record nothing")
    integ.add_argument("--started")
    integ.add_argument("--host")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    if args.command == "record":
        return await record(args)
    return await integrity(args)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse(argv)))


if __name__ == "__main__":
    sys.exit(main())
