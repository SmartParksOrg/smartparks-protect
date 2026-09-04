# ADR 0016: pgBackRest, mirrored objects, host-scheduled jobs and OpenTelemetry

- Status: accepted
- Date: 2026-09-04
- Decisions: D72, D73, D74, D75

## Context

Architecture 28 requires recovery from complete server loss with an RPO under one hour and an
RTO under four hours, point-in-time recovery, an independent recovery path for objects,
off-server encrypted copies, periodic proven restores, and backup health visible in the
application with alerts. Architecture 26.8 asks for OpenTelemetry to be evaluated as the
technical telemetry layer next to the administrator-facing processing traces.

## Decision

**Database.** pgBackRest inside the database container, which the TimescaleDB image ships.
Continuous WAL archiving through `archive_command`, a weekly full and hourly incremental
backup, an S3-compatible repository at another provider, AES-256 encryption with a passphrase
kept outside the server, retention in full-backup generations. WAL archiving is always on;
a wrapper (`protect-pgbackrest`) drops segments until backups are enabled, removes the empty
or inapplicable options that compose cannot leave out, and is the command a restored
cluster's `restore_command` calls.

**Objects.** The MinIO client mirrors every bucket to the same backup bucket under a prefix,
incrementally and without propagating deletions; a daily check confirms that the objects the
database references exist there.

**Jobs and status.** Host cron installed by Ansible runs the scripts, as AddaxAI Connect does,
because a container with the Docker socket is root on the host. Every run is a row in
`backup_runs`; the page and the alerts derive from those rows and from `pg_stat_archiver`,
so a job that never ran is as visible as one that failed. The weekly restore test restores
into a second compose project on the same host with its own network, names and volumes.

**Telemetry.** OpenTelemetry in every service, off until an OTLP endpoint is configured; the
`observability` compose profile provides Grafana with a collector for a development machine
or a small server. Spans carry the processing trace id so both layers join.

## Alternatives

- WAL-G: not in the image; a custom database image or sidecar for no gain.
- MinIO bucket replication: requires MinIO on the target; most providers are not.
- A backup container holding the Docker socket: simpler wiring, root on the host.
- Prometheus metrics only: no distributed traces, no correlation with processing traces.

## Consequences

- A production deployment is complete only when Backup and recovery shows every item green;
  the page and the `SYSTEM_BACKUP` alert make that state visible without shell access.
- Recovery needs three things kept off the server: the vaulted host vars, the cipher
  passphrase and the bucket credentials. Losing the passphrase loses the backups.
- The restore test needs about twice the database size in free disk space while it runs.
- The clean-server recovery timed against the four-hour target waits for a throwaway VM.
