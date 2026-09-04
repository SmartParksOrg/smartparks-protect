# Backup and recovery

A Smart Parks Protect server must survive complete loss (architecture section 28). Three layers make that true: continuous, encrypted, off-server copies of the data; the reproducible deployment in this repository; and, where the provider offers them, VM snapshots as a fast extra. This page covers the first layer and the checks around it. Rebuilding a server from those copies is the [restore guide](restore-guide.md).

## What is protected and how

| Component | Mechanism | Recovery point |
| --- | --- | --- |
| PostgreSQL (every project, device, source event, canonical row, event, rule, trace, integration) | pgBackRest inside the database container: a weekly full and hourly incremental backups, plus every WAL segment as it closes (`archive_command`), all to an S3-compatible bucket, encrypted with AES-256 before upload | Any point in time since the oldest kept full backup; the last archived segment is at most `archive_timeout` (15 minutes) old |
| Objects in MinIO (out-of-line payloads, exports, log files) | `mc mirror` from the `object-mirror` compose service to the same bucket under `<prefix>/<bucket>/`, daily, never deleting on the remote | The last daily mirror |
| Configuration and secrets | The vault-encrypted host vars in your private Ansible repository, and the backup cipher passphrase in a password manager | Whatever you committed last |
| Schema version | Alembic revision inside the database backup; the release tag in the host vars | Same as the database |
| Redis streams | Not backed up: every message is derived from stored source events and can be replayed | Not applicable |

The repository is any S3-compatible bucket at a provider other than the server's host: Backblaze B2, Wasabi, Hetzner Object Storage, DigitalOcean Spaces or AWS S3 all work. Use one bucket per server with credentials that can reach only that bucket.

## Turning backups on

1. Create the bucket and an access key limited to it. Turn on object versioning if the provider supports it, so an overwritten or deleted mirror object keeps its earlier versions.
2. Generate a cipher passphrase: `openssl rand -base64 48`. Store it in your password manager. Without it no backup can be read, and it cannot be recovered from the server.
3. Put the values in the vaulted host vars (`ansible/host_vars/<host>.yml`): `backup_enabled`, `backup_s3_endpoint`, `backup_s3_region`, `backup_s3_bucket`, `backup_s3_key`, `backup_s3_key_secret`, `backup_cipher_pass`. The example file lists them.
4. Run the playbook with `--tags sync-config`. It writes `.env`, restarts the stack so PostgreSQL archives to the repository, and installs the schedule.
5. Create the stanza and take the first full backup by hand, and watch it succeed:

```bash
cd /opt/smartparks-protect
docker compose exec postgres protect-pgbackrest --stanza=protect stanza-create
docker compose exec postgres protect-pgbackrest --stanza=protect check
bash scripts/backup.sh database full
bash scripts/backup.sh objects
bash scripts/backup.sh check
```

6. Open Server admin, Backup and recovery. Every item should be green within the hour. The WAL item turns green after the first archived segment, at the latest `archive_timeout` after the restart.

## The schedule

Installed by Ansible as cron jobs of the application user when `backup_enabled` is true, logging to `logs/backup.log` and `logs/restore-verify.log` in the application directory:

| When | Job | Command |
| --- | --- | --- |
| Every hour at :15 | Incremental database backup | `scripts/backup.sh database incr` |
| Sunday 02:00 | Full database backup | `scripts/backup.sh database full` |
| Daily 02:45 | Object mirror | `scripts/backup.sh objects` |
| Daily 03:15 | Integrity check | `scripts/backup.sh check` |
| Monday 03:30 | Restore test | `scripts/restore-verify.sh` |

WAL archiving is not a job: PostgreSQL pushes every closed segment through pgBackRest as it happens. Retention is `BACKUP_RETENTION_FULL` full backups (four by default, one month); pgBackRest removes older full backups, their incrementals and their WAL.

Every run writes a row to `backup_runs` with its duration, size, label and error. The Backup and recovery page shows the newest state per job and the history. The rules service checks that state every five minutes and opens a system alert (`SYSTEM_BACKUP`) for a failed run, a run older than `BACKUP_STALE_HOURS`, a restore test older than `RESTORE_TEST_STALE_DAYS`, or a WAL segment older than `WAL_ARCHIVE_STALE_MINUTES`. Server-level automations deliver those alerts by email or Telegram like any other system alert. The alert resolves itself when the next run succeeds.

## The restore test

`scripts/restore-verify.sh` proves the backups without touching the running server: it starts a second compose project (`smartparks-protect-verify`, no host ports, its own volumes, WAL archiving off), restores the newest backup and replays every archived segment into it, runs the migrations, starts the API, checks health and row counts, checks that the objects the restored database references exist in the backup bucket, records the result as a `restore_test` run, and removes the project again. It needs free disk space of about twice the database size while it runs.

A failed restore test is a critical finding: the backups may not be usable. Read `logs/restore-verify.log`, fix the cause, and run the script by hand until it passes.

## Point in time

The WAL archive makes every moment since the oldest full backup recoverable. A deletion at 09:40 is undone by restoring to 09:39 on a replacement server, or on the same server with `scripts/restore.sh "2026-09-04 09:39:00+00"`. The restore guide has the steps.

## Security

Backups contain locations of animals and people, credentials of data sources (encrypted with `CREDENTIALS_KEY`, which is in the host vars, not in the backup) and personal data of users. The repository is encrypted before upload with the cipher passphrase; the transport is TLS. The bucket credentials should allow nothing beyond that bucket. Restoring requires the host vars, the passphrase and the bucket credentials, so access to those three is access to everything: keep them in a password manager with restricted sharing, and treat a restore as an audited event (record who did it and why in the session log or ticket).

## Verification status

The mechanisms were exercised on the development machine against a local repository (`BACKUP_REPO_TYPE=posix`): stanza creation, a full backup of the 6.6 GB benchmark database (151 seconds, 2.9 GB compressed), the info document, the run recording, the health assessment and the restore test flow. An S3 provider, the schedule on a server and the clean-server recovery timed against the four-hour target wait for the dev VM; the results are recorded in `PROJECT_PLAN.md` when done.
