# The analysis worker's own image (decision D314): the workspace packages plus hrHSA and its
# stack (pandas, geopandas, rasterio, statsmodels, xarray, dask), which the lean image of
# docker/python.Dockerfile does not carry and whose numpy line (below 2.5) the workspace does
# not share. Only `protect-analysis` runs from it; every other service keeps the lean image.
# The environment comes from services/analysis/image/pyproject.toml and its own uv.lock, with
# hrHSA pinned to one commit and numpy overridden for this environment alone.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# WeasyPrint for the PDF reports (decision D211) as in the lean image; git for the hrHSA pin.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*

# The path dependencies are not workspace members, so uv builds them on the first sync and
# the sources must be there: one sync after the copy, with the uv cache mount keeping a
# rebuild on a code change to seconds.
COPY shared shared
COPY services/analysis services/analysis
COPY services/api services/api
COPY VERSIO[N] ./
# INSTALL_DEV=1 adds pytest and the API package, for the CI job that runs the tests inside
# this image; a server builds without it.
ARG INSTALL_DEV=0
RUN --mount=type=cache,target=/root/.cache/uv \
    cd services/analysis/image \
    && if [ "$INSTALL_DEV" = "1" ]; then uv sync --frozen --group dev; else uv sync --frozen --no-dev; fi

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

CMD ["/app/.venv/bin/python", "-m", "protect_analysis.main"]
