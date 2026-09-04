#!/bin/bash
# Is this server working? A read-only pass/fail gate after an update or a restore. Exit 0 only
# when every check passed.
#   cd /opt/smartparks-protect && bash scripts/verify-server.sh [--since 10m] [--max-errors 0] [--quiet]
set -uo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SINCE="10m"; MAX_ERRORS=0; QUIET=false
while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    --max-errors) MAX_ERRORS="$2"; shift 2 ;;
    --quiet) QUIET=true; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
cd "$APP_DIR" || exit 2
failed=0
say() { [ "$QUIET" = true ] || echo "$@"; }
pass() { say "  PASS  $1${2:+  $2}"; }
fail() { say "  FAIL  $1${2:+  $2}"; failed=$((failed+1)); }
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2-; }

say ""; say "Verifying $(env_get PUBLIC_URL) in $APP_DIR"; say ""

# containers: everything compose defines, minus one-shots, must be running
expected="$(docker compose config --services 2>/dev/null | grep -vE '^(migrate|minio-init)$' | sort)"
if [ -z "$expected" ]; then fail containers "docker compose config returned nothing"; else
  bad=""
  while read -r svc; do
    state="$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s{print $2}')"
    [ "$state" = "running" ] || bad="$bad $svc($state)"
  done <<< "$expected"
  [ -z "$bad" ] && pass containers "$(wc -l <<< "$expected") running" || fail containers "not running:$bad"
fi

# migrations at head
current="$(docker compose run --rm --no-deps migrate /app/.venv/bin/alembic -c services/api/alembic.ini current 2>/dev/null | grep -oE '^[0-9a-f]+' | head -1)"
heads="$(docker compose run --rm --no-deps migrate /app/.venv/bin/alembic -c services/api/alembic.ini heads 2>/dev/null | grep -oE '^[0-9a-f]+' | head -1)"
[ -n "$current" ] && [ "$current" = "$heads" ] && pass migrations "$current" || fail migrations "current=$current heads=$heads"

# health and version, with a time budget
start=$(date +%s.%N)
health="$(curl -s -m 10 http://127.0.0.1:8000/api/health)"
elapsed=$(echo "$(date +%s.%N) - $start" | bc)
echo "$health" | grep -q '"ok"' && pass health "${elapsed}s" || fail health "$health"
version="$(curl -s -m 5 http://127.0.0.1:8000/api/version | grep -oE '"version":"[^"]+"' | cut -d'"' -f4)"
[ -n "$version" ] && pass version "$version" || fail version "no answer"
curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/ | grep -q 200 && pass frontend || fail frontend

# worker heartbeats stamped within the stale window
REDIS_PASSWORD="$(env_get REDIS_PASSWORD)"
stale_minutes="$(env_get HEARTBEAT_STALE_MINUTES)"; stale_minutes="${stale_minutes:-15}"
now=$(date -u +%s)
for worker in ingest decoder export rules automation; do
  stamp="$(docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning GET "heartbeat:$worker" 2>/dev/null </dev/null | tr -d '"')"
  if [ -z "$stamp" ]; then fail "worker $worker" "no heartbeat"; else
    age=$(( now - $(date -u -d "$stamp" +%s 2>/dev/null || echo 0) ))
    [ "$age" -lt $(( stale_minutes * 60 )) ] && pass "worker $worker" "${age}s ago" || fail "worker $worker" "stale ${age}s"
  fi
done

# errors in the logs
errors="$(docker compose logs --since "$SINCE" 2>/dev/null | grep -cE '"level": ?"ERROR"|ERROR ' || true)"
[ "$errors" -le "$MAX_ERRORS" ] && pass "errors since $SINCE" "$errors" || fail "errors since $SINCE" "$errors (max $MAX_ERRORS)"

say ""; [ "$failed" -eq 0 ] && say "All checks passed" || say "$failed check(s) failed"
[ "$failed" -eq 0 ]
