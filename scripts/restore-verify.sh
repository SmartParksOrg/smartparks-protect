#!/bin/bash
# Proves the backups restore (architecture 28.10): builds a second compose project next to the
# running one with the newest database backup and every archived WAL segment, migrates it, starts
# the API, checks health and row counts, checks that referenced objects exist in the backup
# bucket, records the result in backup_runs of the production stack, and removes everything.
#   scripts/restore-verify.sh            # scheduled weekly by Ansible
# Needs about twice the database size in free disk space for the duration of the run.
set -uo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_DIR" || exit 2
log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }
[ "$(env_get BACKUP_ENABLED)" = "true" ] || { log "BACKUP_ENABLED is not true; nothing to do"; exit 0; }

STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; START_EPOCH=$(date +%s)
V=(docker compose -p smartparks-protect-verify -f docker-compose.yml -f docker/backup/verify.yml)
# A local repository (testing only) is read from the production state volume, see verify.yml.
if [ "$(env_get BACKUP_REPO_TYPE)" = "posix" ]; then
    export VERIFY_REPO_PATH="/mnt/production-backup/$(basename "$(env_get BACKUP_REPO_PATH)")"
fi
PGUSER="$(env_get POSTGRES_USER)"; PGDB="$(env_get POSTGRES_DB)"
tmp="$(mktemp)"

finish() {
    local status="$1" error="${2:-}"
    "${V[@]}" down -v --remove-orphans > /dev/null 2>&1
    local duration=$(( $(date +%s) - START_EPOCH ))
    local args=(record --kind restore_test --status "$status" --started "$STARTED" --duration "$duration" --host "$(hostname)")
    [ -n "$error" ] && args+=(--error "$error")
    docker compose run --rm --no-deps -T api /app/.venv/bin/python -m protect_api.backup "${args[@]}" --details-stdin < "$tmp"
    rm -f "$tmp"
    log "restore test $status (${duration}s)"
    [ "$status" = ok ]
}
fail() { log "FAILED: $1"; [ -s "$tmp" ] || echo '{}' > "$tmp"; finish failed "$1"; exit 1; }

log "removing leftovers of an earlier run"
"${V[@]}" down -v --remove-orphans > /dev/null 2>&1

log "restoring the newest backup into an empty cluster"
"${V[@]}" run --rm --no-deps --user postgres --entrypoint sh postgres -c 'mkdir -p /home/postgres/pgdata/data && protect-pgbackrest --stanza=protect --log-level-console=warn restore' \
    || fail "pgbackrest restore failed"

log "starting PostgreSQL and replaying WAL"
"${V[@]}" up -d --wait postgres redis minio > /dev/null 2>&1 || fail "infrastructure did not start"
"${V[@]}" up minio-init > /dev/null 2>&1 || fail "bucket setup failed"
for i in $(seq 1 120); do
    "${V[@]}" exec -T postgres psql -U "$PGUSER" -d "$PGDB" -Atc 'select pg_is_in_recovery()' 2>/dev/null | grep -q f && break
    sleep 5
done
"${V[@]}" exec -T postgres psql -U "$PGUSER" -d "$PGDB" -Atc 'select pg_is_in_recovery()' 2>/dev/null | grep -q f || fail "WAL replay did not finish in ten minutes"

log "migrations and API"
"${V[@]}" run --rm migrate > /dev/null 2>&1 || fail "migrations failed on the restored database"
"${V[@]}" up -d --wait api > /dev/null 2>&1 || fail "the API did not become healthy on the restored database"
health="$("${V[@]}" exec -T api python -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:8000/api/health", timeout=10).read().decode())' 2>/dev/null)"
echo "$health" | grep -q '"ok"' || fail "health check failed: $health"

counts="$("${V[@]}" exec -T postgres psql -U "$PGUSER" -d "$PGDB" -Atc "select json_build_object('users', (select count(*) from users), 'projects', (select count(*) from projects), 'devices', (select count(*) from devices), 'source_events', (select count(*) from source_events), 'positions', (select count(*) from positions), 'measurements', (select count(*) from measurements), 'latest_source_event', (select max(ingested_at) from source_events))")"
log "restored: $counts"

log "object references against the backup bucket"
# stdout only: compose prints its container lines on stderr and the last line is the JSON result
objects="$("${V[@]}" run --rm --no-deps -T api /app/.venv/bin/python -m protect_api.backup integrity --dry-run 2>/dev/null | tail -n 1)"
if ! printf '%s' "$objects" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["missing"] == 0 else 1)' 2>/dev/null; then
    printf '{"counts": %s, "objects": %s}\n' "$counts" "${objects:-null}" > "$tmp"
    fail "missing objects in the backup bucket"
fi

printf '{"counts": %s, "objects": %s}\n' "$counts" "$objects" > "$tmp"
finish ok
