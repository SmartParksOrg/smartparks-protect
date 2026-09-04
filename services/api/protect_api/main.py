"""FastAPI application for Smart Parks Protect."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from protect_api.health import router as health_router
from protect_api.middleware import RequestIdMiddleware
from protect_api.oauth.middleware import MCPAccessMiddleware
from protect_api.oauth.routes import install_oauth_routes
from protect_api.ratelimit import RateLimitMiddleware
from protect_api.realtime import broadcaster
from protect_api.routers import v1_router
from shared.config import get_settings
from shared.logger import configure_logging, get_logger
from shared.telemetry import configure_telemetry
from shared.version import __version__

log = get_logger("protect_api")


class VersionResponse(BaseModel):
    version: str
    commit: str


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("api", level=settings.log_level, log_format=settings.log_format)
    telemetry = configure_telemetry("api")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await broadcaster.stop()

    app = FastAPI(
        title="Smart Parks Protect",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    # Added first, so it runs inside the request id middleware and its audit rows carry the id.
    app.add_middleware(MCPAccessMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(v1_router, prefix="/api/v1")
    install_oauth_routes(app)
    if telemetry:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health,api/version")

    @app.get("/api/version", response_model=VersionResponse, tags=["health"])
    async def version() -> VersionResponse:
        return VersionResponse(version=__version__, commit=os.environ.get("GIT_COMMIT", "unknown"))

    log.info("api configured", version=__version__, environment=settings.environment)
    return app


app = create_app()
