"""ASGI entry point: `uvicorn protect_mcp.main:app`. Streamable HTTP at /mcp, stateless so any
replica can answer any request; protected resource metadata at both RFC 9728 paths; a health
endpoint for compose and the verify script."""

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from protect_mcp.api import ProtectApi
from protect_mcp.server import build_server
from shared.config import get_settings
from shared.logger import configure_logging, get_logger
from shared.oauth import READ_SCOPES, issuer_url, mcp_resource_url
from shared.version import __version__

log = get_logger("protect_mcp")


def create_app(api: ProtectApi | None = None) -> Starlette:
    """The ASGI app. Tests pass an API client bound to the API app in process."""
    settings = get_settings()
    configure_logging("mcp", level=settings.log_level, log_format=settings.log_format)
    server = build_server(api or ProtectApi())
    log.info("mcp configured", version=__version__, resource=mcp_resource_url())
    # nginx terminates TLS and checks the Host header; the SDK's DNS rebinding guard would
    # need every public host name and blocks the container-internal health check.
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    # The SDK serves the path-suffixed metadata document; clients probe the root one as well.
    app.add_route("/.well-known/oauth-protected-resource", protected_resource_root, methods=["GET"])
    app.add_route("/health", health, methods=["GET"])
    return app


async def protected_resource_root(_: Request) -> Response:
    return JSONResponse(
        {
            "resource": mcp_resource_url(),
            "authorization_servers": [issuer_url()],
            "scopes_supported": list(READ_SCOPES),
            "bearer_methods_supported": ["header"],
            "resource_name": "Smart Parks Protect",
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


app = create_app()
