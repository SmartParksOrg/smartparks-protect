#!/bin/bash
# Full recovery of this server from the off-server backups (architecture 28.7). Run on a clean
# server after the Ansible playbook has deployed the stack with the same .env (secrets and
# BACKUP_* from the vaulted host vars):
#   scripts/restore.sh                          # newest backup, replay every archived WAL segment
#   scripts/restore.sh "2026-09-04 03:15:00+00" # point in time, before an accidental deletion
#   scripts/restore.sh --db-only                # database only, objects untouched
#   scripts/restore.sh --test                   # a drill on another server: archiving stays off
# Stops the stack, restores the database cluster with pgBackRest (delta, so an existing cluster
# is overwritten in place), starts PostgreSQL to replay WAL to the target, copies the objects
# back from the backup bucket, starts everything and runs scripts/verify-server.sh.
#
# Recovery follows the timeline of the backup set (--target-timeline=current), never "latest":
# a drill that promoted a cluster and archived into the same stanza would otherwise be followed
# instead of the real server's history. A drill must use --test, which turns BACKUP_ENABLED off
# in .env after the restore so the drill server never archives into the production stanza.
set -euo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_DIR"
log() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] $*"; }
die() { echo "[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] ERROR: $*" >&2; exit 1; }
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }

TARGET=""; DB_ONLY=false; FORCE=false; TEST=false
for arg in "$@"; do
    case "$arg" in
        --db-only) DB_ONLY=true ;;
        --force) FORCE=true ;;
        --test) TEST=true ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) TARGET="$arg" ;;
    esac
done
[ "$(env_get BACKUP_ENABLED)" = "true" ] || die "BACKUP_ENABLED is not true in .env; the repository settings are needed to restore"

LOCK_FILE="$APP_DIR/.restore-in-progress"
touch "$LOCK_FILE"; trap 'rm -f "$LOCK_FILE"' EXIT

if [ "$FORCE" != true ]; then
    users="$(docker compose exec -T postgres psql -U "$(env_get POSTGRES_USER)" -d "$(env_get POSTGRES_DB)" -Atc 'select count(*) from users' 2>/dev/null || echo 0)"
    [ "${users:-0}" = "0" ] || die "this server has $users users; pass --force to overwrite them with the backup"
fi

log "stopping the stack"
docker compose --profile chirpstack --profile observability stop

restore_args=(--stanza=protect --delta --target-timeline=current --log-level-console=info)
if [ -n "$TARGET" ]; then
    restore_args+=(--type=time "--target=$TARGET" --target-action=promote)
fi
log "restoring the database cluster${TARGET:+ to $TARGET}"
docker compose run --rm --no-deps --user postgres --entrypoint protect-pgbackrest postgres "${restore_args[@]}" restore

if [ "$TEST" = true ]; then
    log "drill: archiving stays off on this server (BACKUP_ENABLED=false in .env)"
    sed -i 's/^BACKUP_ENABLED=true$/BACKUP_ENABLED=false/' .env
fi
log "starting PostgreSQL (WAL replay)"
docker compose up -d --wait postgres
for i in $(seq 1 120); do
    if docker compose exec -T postgres psql -U "$(env_get POSTGRES_USER)" -d "$(env_get POSTGRES_DB)" -Atc 'select pg_is_in_recovery()' 2>/dev/null | grep -q f; then
        break
    fi
    sleep 5
done
docker compose exec -T postgres psql -U "$(env_get POSTGRES_USER)" -d "$(env_get POSTGRES_DB)" -Atc 'select pg_is_in_recovery()' | grep -q f || die "PostgreSQL is still in recovery after ten minutes"

if [ "$DB_ONLY" != true ]; then
    log "restoring objects from the backup bucket"
    docker compose up -d --wait minio
    docker compose up minio-init > /dev/null
    if ! docker compose --profile backup run --rm -T -e MIRROR_DIRECTION=restore object-mirror; then
        log "WARNING: the object restore reported errors; the stack starts anyway. Rerun by hand:"
        log "  docker compose --profile backup run --rm -e MIRROR_DIRECTION=restore object-mirror"
    fi
fi

log "starting the stack"
docker compose up -d --remove-orphans
sleep 10
bash scripts/verify-server.sh --since 5m || log "verify-server reported failures; check them before enabling data sources"
log "restore finished. Data sources stay as they were; enable them under Server admin when the server is ready."
