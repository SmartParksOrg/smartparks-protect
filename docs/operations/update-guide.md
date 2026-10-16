# Update guide

Servers run tagged releases. An update is a checkout of the new tag plus a rebuild; the compose stack runs the migrations before the API starts.

## With Ansible

```bash
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml --limit myserver --tags env-refresh --ask-vault-pass
```

`env-refresh` checks out `git_version` (or the newest release tag), rewrites `.env`, rebuilds the images and restarts the stack. `--tags sync-config` rewrites `.env` and restarts without a checkout, for a settings change.

## By hand

```bash
cd /opt/smartparks-protect
git fetch origin --tags && git checkout v0.5.0
docker compose build && docker compose up -d --remove-orphans
bash scripts/verify-server.sh
```

Rollback is the same with the previous tag. A migration that cannot be reversed is called out in the changelog of the release.

## What people see during an update

The playbook raises a flag (`/var/www/protect/updating`) before the containers restart and
lowers it once the API and the frontend answer again (decision D329). While it is up, and
whenever a container is down, nginx answers a page load with a small page that says Protect is
being updated and retries every ten seconds, and an API call with a JSON message and a
`Retry-After`. A tab that is open shows a bar under the top bar, asks the health endpoint every
five seconds and refreshes its data when the server is back; nothing typed is lost. By hand,
`touch /var/www/protect/updating` puts the server in that state and removing the file ends it.

## Migration 0054 (compression after 90 days)

The update of 2026-10-16 moves the compression window from 7 to 90 days (decision D328) and
decompresses the chunks of the last 90 days that were compressed under the old window, so an
import of recent weeks writes at full speed from then on. On a server with months of data the
migrate step takes minutes and the database grows by the uncompressed size of those chunks
(roughly ten times their compressed size) until the policy compresses them again after 90 days;
check the free disk before updating a large server. The compose file also preloads
`pg_stat_statements`, so the database container restarts once.

## Before a major update

Read the changelog entry for breaking changes, migration notes and configuration changes (see the [release process](release-process.md)). Take a backup first: `scripts/backup.sh` writes a full pgBackRest backup and mirrors the object storage (the [backup and recovery guide](backup-and-recovery.md)). A database dump (`docker compose exec -T postgres pg_dump -U protect smartparks_protect | gzip > backup.sql.gz`) is the lightweight alternative on a server without backups configured.
