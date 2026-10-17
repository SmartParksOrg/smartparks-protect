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

# WeasyPrint (the PDF reports of analysis runs, decision D211) draws text through Pango and
# HarfBuzz and needs a font on the system; nothing else in the image wants system packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# go-pmtiles cuts the offline maps of Protect Go from a Protomaps planet build (phase 43 P3).
# One static binary, pinned; the digest was computed on 2026-10-17 since the release publishes
# none. The image is built for amd64; another architecture fails here on purpose.
ARG PMTILES_VERSION=1.31.2
ARG PMTILES_SHA256=3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f
RUN python3 - "$PMTILES_VERSION" "$PMTILES_SHA256" <<'PY' \
    && tar -xzf /tmp/pmtiles.tgz -C /usr/local/bin pmtiles && rm /tmp/pmtiles.tgz
import hashlib, platform, sys, urllib.request
version, expected = sys.argv[1], sys.argv[2]
if platform.machine() not in ("x86_64", "AMD64"):
    sys.exit(f"pmtiles is pinned for x86_64; this image builds on {platform.machine()}")
url = f"https://github.com/protomaps/go-pmtiles/releases/download/v{version}/go-pmtiles_{version}_Linux_x86_64.tar.gz"
data = urllib.request.urlopen(url, timeout=120).read()
if hashlib.sha256(data).hexdigest() != expected:
    sys.exit("pmtiles download does not match its pinned digest")
open("/tmp/pmtiles.tgz", "wb").write(data)
PY

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
COPY services/analysis/pyproject.toml services/analysis/pyproject.toml
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
COPY services/analysis services/analysis
# VERSION exists from the first release on; the glob keeps the build working without it.
COPY VERSIO[N] ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "protect_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
