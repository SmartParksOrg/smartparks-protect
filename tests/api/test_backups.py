"""Backup and recovery (phase 10): the health assessment, the admin endpoints, and the command
line the host scripts use to record runs and check object integrity."""

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import shared.backup as backup_health
from protect_api import backup as backup_cli
from shared.config import get_settings
from shared.enums import BackupKind, BackupStatus
from shared.models import BackupRun
from tests.api.conftest import actor

pytestmark = pytest.mark.asyncio

PGBACKREST_INFO = [
    {
        "name": "protect",
        "status": {"code": 0, "message": "ok"},
        "archive": [
            {"id": "17-1", "min": "000000010000007E000000E0", "max": "000000010000007E000000E5"}
        ],
        "backup": [
            {
                "label": "20260904-020000F",
                "type": "full",
                "info": {"size": 6603654747, "repository": {"size": 2992613751}},
                "timestamp": {"start": 1788531754, "stop": 1788531905},
                "archive": {
                    "start": "000000010000007E000000E2",
                    "stop": "000000010000007E000000E2",
                },
            },
            {
                "label": "20260904-020000F_20260904-031500I",
                "type": "incr",
                "info": {"size": 6603700000, "repository": {"size": 1200000}},
                "timestamp": {"start": 1788536100, "stop": 1788536110},
                "archive": {
                    "start": "000000010000007E000000E5",
                    "stop": "000000010000007E000000E5",
                },
            },
        ],
    }
]


def _enabled(monkeypatch, **overrides):
    settings = get_settings().model_copy(update={"backup_enabled": True, **overrides})
    monkeypatch.setattr(backup_health, "get_settings", lambda: settings)


def _wal(monkeypatch, *, archived_ago=None, failed_ago=None, mode="on"):
    now = datetime.now(UTC)

    async def fake(session):
        return {
            "archive_mode": mode,
            "archived_count": 10,
            "last_archived_wal": "000000010000007E000000E5",
            "last_archived_time": now - archived_ago if archived_ago is not None else None,
            "failed_count": 1 if failed_ago is not None else 0,
            "last_failed_wal": None,
            "last_failed_time": now - failed_ago if failed_ago is not None else None,
        }

    monkeypatch.setattr(backup_health, "wal_archiver", fake)


async def _clear(db):
    """Runs recorded by other tests in this session must not colour this one."""
    from sqlalchemy import delete

    await db.execute(delete(BackupRun))
    await db.commit()


async def _run(db, kind, status="ok", ago=timedelta(minutes=20), **fields):
    finished = datetime.now(UTC) - ago
    run = BackupRun(
        kind=kind,
        status=status,
        started_at=finished - timedelta(seconds=30),
        finished_at=finished,
        duration_seconds=30,
        details={},
        **fields,
    )
    db.add(run)
    await db.commit()
    return run


async def test_status_off_and_admin_only(client, db):
    admin = await actor(client, db, superuser=True)
    user = await actor(client, db)
    assert (
        await client.get("/api/v1/admin/backups/status", headers=user.headers)
    ).status_code == 403
    response = await client.get("/api/v1/admin/backups/status", headers=admin.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["overall"] == "off"
    assert {i["status"] for i in body["items"]} == {"off"}
    assert body["rpo_seconds"] == 3600


async def test_status_healthy(client, db, monkeypatch):
    await _clear(db)
    _enabled(monkeypatch)
    _wal(monkeypatch, archived_ago=timedelta(minutes=5))
    await _run(
        db, BackupKind.DATABASE_FULL, ago=timedelta(hours=20), size_bytes=2_992_613_751, label="F"
    )
    await _run(
        db, BackupKind.DATABASE_INCR, ago=timedelta(minutes=18), size_bytes=1_200_000, label="I"
    )
    await _run(db, BackupKind.OBJECT_MIRROR, ago=timedelta(minutes=31))
    await _run(db, BackupKind.INTEGRITY_CHECK, ago=timedelta(hours=2))
    await _run(db, BackupKind.RESTORE_TEST, ago=timedelta(days=3))
    health = await backup_health.assess(db)
    assert health.overall == "ok", [(i.key, i.status, i.detail) for i in health.items]
    items = {i.key: i for i in health.items}
    assert items["database"].detail.startswith("OK, incr 18 minutes ago")
    assert "1.1 MB" in items["database"].detail
    assert items["wal"].status == "ok"
    assert items["offsite"].status == "ok"
    assert 4 * 60 < (health.recovery_point_seconds or 0) < 6 * 60


async def test_status_stale_failed_and_local_repository(client, db, monkeypatch):
    await _clear(db)
    _enabled(monkeypatch, backup_repo_type="posix")
    _wal(monkeypatch, archived_ago=timedelta(hours=5), failed_ago=timedelta(minutes=1))
    await _run(
        db, BackupKind.DATABASE_INCR, status="failed", ago=timedelta(minutes=5), error="boom"
    )
    await _run(db, BackupKind.OBJECT_MIRROR, ago=timedelta(hours=40))
    health = await backup_health.assess(db)
    items = {i.key: i for i in health.items}
    assert items["database"].status == "failed" and "boom" in items["database"].detail
    assert items["wal"].status == "failed" and "Archiving fails" in items["wal"].detail
    assert items["objects"].status == "stale"
    assert items["offsite"].status == "failed" and "posix" in items["offsite"].detail
    assert items["restore_test"].status == "stale"
    assert health.overall == "failed"


async def test_record_summarises_pgbackrest_info(client, db, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(PGBACKREST_INFO)))
    started = "2026-09-04T03:15:00Z"
    code = await backup_cli.run(
        backup_cli.parse(
            [
                "record",
                "--kind",
                "database_incr",
                "--status",
                "ok",
                "--started",
                started,
                "--duration",
                "12",
                "--host",
                "srv1",
                "--details-stdin",
            ]
        )
    )
    assert code == 0
    await db.rollback()
    run = await db.scalar(
        select(BackupRun).where(BackupRun.host == "srv1").order_by(BackupRun.id.desc()).limit(1)
    )
    assert run is not None
    assert run.label == "20260904-020000F_20260904-031500I"
    assert run.size_bytes == 1_200_000
    assert run.details["type"] == "incr"
    assert run.details["archive_max"] == "000000010000007E000000E5"
    assert run.details["backup_count"] == 2
    assert run.finished_at == datetime(2026, 9, 4, 3, 15, 12, tzinfo=UTC)

    admin = await actor(client, db, superuser=True)
    listed = await client.get(
        "/api/v1/admin/backups/runs", params={"limit": 5}, headers=admin.headers
    )
    assert listed.status_code == 200
    assert run.label in {r["label"] for r in listed.json()}


async def test_integrity_check_reports_missing_objects(client, db, monkeypatch):
    class Remote:
        def __init__(self, missing):
            self.missing = missing
            self.seen = []

        def stat_object(self, bucket, key):
            from minio.error import S3Error

            self.seen.append(key)
            if key in self.missing:
                raise S3Error(None, "NoSuchKey", "missing", key, "r", "h")

    monkeypatch.setattr(backup_cli, "_remote", lambda: Remote(set()))
    settings = get_settings().model_copy(
        update={"backup_s3_bucket": "bkp", "backup_object_prefix": "srv1"}
    )
    monkeypatch.setattr(backup_cli, "get_settings", lambda: settings)
    assert await backup_cli.run(backup_cli.parse(["integrity", "--dry-run"])) == 0

    remote = Remote({"srv1/uploads/does-not-exist"})
    monkeypatch.setattr(backup_cli, "_remote", lambda: remote)
    # An object reference nobody mirrored: a source event with an out-of-line payload key.
    from shared.enums import AcquisitionChannel, IngestionMethod, ProcessingStatus
    from shared.models import DataSource, SourceEvent

    source = DataSource(name="Integrity source", adapter_key="generic_http")
    db.add(source)
    await db.commit()
    db.add(
        SourceEvent(
            data_source_id=source.id,
            external_id="x",
            event_type="uplink",
            acquisition_channel=AcquisitionChannel.OTHER,
            ingestion_method=IngestionMethod.WEBHOOK,
            processing_status=ProcessingStatus.RECEIVED,
            payload=None,
            payload_object_key="does-not-exist",
            payload_size=1,
            payload_sha256="0" * 64,
        )
    )
    await db.commit()
    code = await backup_cli.run(backup_cli.parse(["integrity", "--host", "srv1"]))
    assert code == 1
    assert "srv1/uploads/does-not-exist" in remote.seen
    await db.rollback()
    run = await db.scalar(
        select(BackupRun)
        .where(BackupRun.kind == BackupKind.INTEGRITY_CHECK)
        .order_by(BackupRun.id.desc())
        .limit(1)
    )
    assert run is not None and run.status == BackupStatus.FAILED
    assert run.details["missing"] == 1
