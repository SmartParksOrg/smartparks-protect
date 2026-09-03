#!/usr/bin/env bash
# Daily development commands for Smart Parks Protect. Run from anywhere in the repository.
#   scripts/dev.sh up | down | logs [service] | migrate | revision <msg> | bootstrap-admin <email> | test | lint | format | docs | sweep | hooks
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
    sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

need_env() {
    if [ ! -f .env ]; then
        echo "No .env file. Run: cp .env.example .env" >&2
        exit 1
    fi
}

cmd="${1:-}"
shift || true

case "$cmd" in
    up)
        need_env
        GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" docker compose up -d --build "$@"
        ;;
    down)
        docker compose --profile chirpstack down "$@"
        ;;
    logs)
        docker compose logs -f "$@"
        ;;
    migrate)
        uv run alembic -c services/api/alembic.ini upgrade head "$@"
        ;;
    revision)
        uv run alembic -c services/api/alembic.ini revision --autogenerate -m "$*"
        ;;
    bootstrap-admin)
        docker compose run --rm --no-deps api /app/.venv/bin/python -m protect_api.bootstrap "$@"
        ;;
    test)
        uv run pytest -q "$@"
        (cd services/frontend && npm run test)
        ;;
    lint)
        uv run ruff check .
        uv run ruff format --check .
        uv run mypy
        (cd services/frontend && npm run lint && npm run typecheck)
        ;;
    format)
        uv run ruff format .
        uv run ruff check --fix .
        ;;
    docs)
        uv run --only-group docs mkdocs build --strict "$@"
        ;;
    sweep)
        echo "The screenshot sweep arrives with the app shell in phase 3." >&2
        exit 1
        ;;
    hooks)
        git config core.hooksPath .githooks
        echo "Git hooks installed from .githooks"
        ;;
    *)
        usage
        ;;
esac
