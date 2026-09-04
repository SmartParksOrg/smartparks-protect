#!/bin/bash
# Backups (architecture 28). Scheduled by Ansible on the server, runnable by hand:
#   scripts/backup.sh database incr     # hourly: pgBackRest incremental backup
#   scripts/backup.sh database full     # weekly: pgBackRest full backup
#   scripts/backup.sh objects           # daily: mirror the MinIO buckets to the backup bucket
#   scripts/backup.sh check             # daily: database object references against the backup
# Every run is recorded in backup_runs (protect_api.backup record) so the Backup and recovery
# page shows it and the system checks alert on failures and gaps. Requires BACKUP_ENABLED=true
# and the BACKUP_* variables in .env; otherwise it exits without doing anything.
set -uo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_DIR" || exit 2
log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }

if [ "$(env_get BACKUP_ENABLED)" != "true" ]; then
    log "BACKUP_ENABLED is not true; nothing to do"
    exit 0
fi

what="${1:-}"; mode="${2:-incr}"
case "$what" in database|objects|check) ;; *) sed -n '2,8p' "$0"; exit 2 ;; esac

STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH=$(date +%s)

record() {
    # record <kind> <status> [error] ; details JSON on stdin when a file is given as $4
    local kind="$1" status="$2" error="${3:-}" details_file="${4:-}"
    local duration=$(( $(date +%s) - START_EPOCH ))
    local args=(record --kind "$kind" --status "$status" --started "$STARTED" --duration "$duration" --host "$(hostname)")
    [ -n "$error" ] && args+=(--error "$error")
    if [ -n "$details_file" ]; then
        docker compose run --rm --no-deps -T api /app/.venv/bin/python -m protect_api.backup "${args[@]}" --details-stdin < "$details_file"
    else
        docker compose run --rm --no-deps -T api /app/.venv/bin/python -m protect_api.backup "${args[@]}"
    fi
}

# A restore in progress must not be overwritten by a backup of a half-restored state.
LOCK_FILE="$APP_DIR/.restore-in-progress"
if [ -f "$LOCK_FILE" ] && [ $(( $(date +%s) - $(stat -c %Y "$LOCK_FILE") )) -lt 21600 ]; then
    log "restore in progress; skipping"
    kind="object_mirror"; [ "$what" = database ] && kind="database_$mode"; [ "$what" = check ] && kind="integrity_check"
    record "$kind" skipped "restore in progress"
    exit 0
fi

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT

case "$what" in
    database)
        kind="database_$mode"
        log "pgBackRest $mode backup"
        if docker compose exec -T postgres protect-pgbackrest --stanza=protect --type="$mode" backup > "$tmp" 2>&1; then
            docker compose exec -T postgres protect-pgbackrest --stanza=protect info --output=json > "$tmp"
            record "$kind" ok "" "$tmp"
            log "done"
        else
            tail -5 "$tmp"
            record "$kind" failed "$(tail -c 1500 "$tmp")"
            log "FAILED"; exit 1
        fi
        ;;
    objects)
        log "mirroring buckets"
        if docker compose --profile backup run --rm -T object-mirror > "$tmp" 2>&1; then
            python3 -c 'import json,sys; print(json.dumps({"log": sys.stdin.read()[-4000:]}))' < "$tmp" > "$tmp.json"
            record object_mirror ok "" "$tmp.json"; rm -f "$tmp.json"
            log "done"
        else
            tail -5 "$tmp"
            record object_mirror failed "$(tail -c 1500 "$tmp")"
            log "FAILED"; exit 1
        fi
        ;;
    check)
        log "integrity check"
        # Records its own run; exits non-zero when references point at missing objects.
        docker compose run --rm --no-deps -T api /app/.venv/bin/python -m protect_api.backup integrity --started "$STARTED" --host "$(hostname)"
        ;;
esac
