# One image for every Python service (api, migrate, ingest, decoder, ...). Build context is the
# repository root; compose picks the command per service. Layer order: dependency metadata first,
# then sources, so a code change does not reinstall dependencies.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/ingest/pyproject.toml services/ingest/pyproject.toml
COPY services/decoder/pyproject.toml services/decoder/pyproject.toml
COPY services/export/pyproject.toml services/export/pyproject.toml
COPY services/rules/pyproject.toml services/rules/pyproject.toml
COPY services/automation/pyproject.toml services/automation/pyproject.toml
COPY services/integration/pyproject.toml services/integration/pyproject.toml
COPY services/mcp/pyproject.toml services/mcp/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --all-packages

COPY shared shared
COPY services/api services/api
COPY services/ingest services/ingest
COPY services/decoder services/decoder
COPY services/export services/export
COPY services/rules services/rules
COPY services/automation services/automation
COPY services/integration services/integration
COPY services/mcp services/mcp
# VERSION exists from the first release on; the glob keeps the build working without it.
COPY VERSIO[N] ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "protect_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
