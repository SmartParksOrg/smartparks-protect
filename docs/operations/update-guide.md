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

## Before a major update

Read the changelog entry for breaking changes, migration notes and configuration changes (see the [release process](release-process.md)). Take a backup first: `scripts/backup.sh` writes a full pgBackRest backup and mirrors the object storage (the [backup and recovery guide](backup-and-recovery.md)). A database dump (`docker compose exec -T postgres pg_dump -U protect smartparks_protect | gzip > backup.sql.gz`) is the lightweight alternative on a server without backups configured.
