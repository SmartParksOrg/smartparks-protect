#!/bin/bash
# Daily security check, result published to Redis for the system health page. Runs the same
# /usr/local/bin/security-check.sh ansible runs at the end of a deploy. Must run as root;
# scheduled by ansible at 02:30 UTC.
set -uo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
CHECK=/usr/local/bin/security-check.sh
KEY="security:last_check"
cd "$APP_DIR" || exit 2
env_get() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
REDIS_PASSWORD="$(env_get REDIS_PASSWORD)"
now="$(date -u +'%Y-%m-%dT%H:%M:%S+00:00')"
publish() { docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning SET "$KEY" "$1" >/dev/null 2>&1 </dev/null || true; }
if [ ! -x "$CHECK" ]; then
  publish "{\"status\":\"fail\",\"timestamp\":\"$now\",\"error\":\"security-check.sh missing, run the ansible playbook\"}"
  echo "security-check.sh missing"; exit 1
fi
output="$("$CHECK" 2>&1)"; rc=$?
passed=$(grep -c '^PASS' <<< "$output"); failed=$(grep -c '^FAIL' <<< "$output"); warned=$(grep -c '^WARN' <<< "$output")
status=$([ "$rc" -eq 0 ] && echo ok || echo fail)
publish "{\"status\":\"$status\",\"timestamp\":\"$now\",\"passed\":$passed,\"failed\":$failed,\"warnings\":$warned}"
echo "$output"; exit "$rc"
