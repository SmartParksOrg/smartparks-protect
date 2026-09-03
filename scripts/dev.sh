#!/usr/bin/env bash
# Daily development commands for Smart Parks Protect. Run from anywhere in the repository.
#   scripts/dev.sh up | down | logs [service] | migrate | revision <msg> | bootstrap-admin <email> | chirpstack-bootstrap [args] | simulate [args] | openapi | test | lint | format | docs | sweep | hooks
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
    chirpstack-bootstrap)
        uv run scripts/chirpstack_bootstrap.py --mint-key "$@"
        ;;
    simulate)
        uv run scripts/simulate_opencollar.py "$@"
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
    openapi)
        # The committed schema is for type generation and drift detection; its version is pinned so a release bump does not change it.
        uv run python -c "import json, pathlib; from protect_api.main import app; spec = app.openapi(); spec['info']['version'] = 'committed'; pathlib.Path('services/frontend/openapi.json').write_text(json.dumps(spec, indent=1))"
        (cd services/frontend && npx openapi-typescript openapi.json -o src/api/schema.d.ts >/dev/null && echo "src/api/schema.d.ts generated")
        ;;
    docs)
        uv run --only-group docs mkdocs build --strict "$@"
        ;;
    sweep)
        (cd services/frontend && npm run sweep)
        ;;
    hooks)
        git config core.hooksPath .githooks
        echo "Git hooks installed from .githooks"
        ;;
    *)
        usage
        ;;
esac
