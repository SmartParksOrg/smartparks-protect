# Smart Parks Protect API. Build context is the repository root:
#   docker build -f services/api/Dockerfile .
# Layer order matters: dependency metadata first, then the source, so a code change does not
# reinstall dependencies.
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
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package smartparks-protect-api

COPY shared shared
COPY services/api services/api
# VERSION exists from the first release on; the glob keeps the build working without it.
COPY VERSIO[N] ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package smartparks-protect-api

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "protect_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
