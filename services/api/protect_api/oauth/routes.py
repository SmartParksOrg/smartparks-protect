"""OAuth endpoints: the SDK handlers for the protocol, FastAPI endpoints for the consent page
and the user's connections, and the authorization server metadata at the well-known path."""

import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.shared.auth import OAuthMetadata
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.oauth.provider import (
    SUPPORTED_SCOPES,
    ProtectAuthorizationServerProvider,
    _now,
    is_loopback,
)
from protect_api.schemas.oauth import (
    ConnectionRead,
    ConnectionRevoke,
    ConsentDecision,
    ConsentInfo,
    ScopeInfo,
)
from shared.config import get_settings
from shared.database import get_session
from shared.enums import OAuthClientKind
from shared.models import OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken, User
from shared.oauth import SCOPE_DESCRIPTIONS, issuer_url

OAUTH_PREFIX = "/api/v1/oauth"
METADATA_PATH = "/.well-known/oauth-authorization-server"

router = APIRouter(prefix="/oauth", tags=["oauth"])
provider = ProtectAuthorizationServerProvider()


def authorization_server_metadata() -> OAuthMetadata:
    """RFC 8414 metadata. The issuer is the public URL; the endpoints live under the API prefix
    so nginx routes them like every other API path."""
    base = issuer_url()
    # Plain strings: the model keeps a path-less issuer without a trailing slash, a URL object
    # built outside the model would carry one (RFC 8414 compares issuers exactly).
    return OAuthMetadata(
        issuer=base,
        authorization_endpoint=f"{base}{OAUTH_PREFIX}/authorize",
        token_endpoint=f"{base}{OAUTH_PREFIX}/token",
        registration_endpoint=f"{base}{OAUTH_PREFIX}/register",
        revocation_endpoint=f"{base}{OAUTH_PREFIX}/revoke",
        scopes_supported=list(SUPPORTED_SCOPES),
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post", "client_secret_basic"],
        revocation_endpoint_auth_methods_supported=[
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        code_challenge_methods_supported=["S256"],
        client_id_metadata_document_supported=True,
        authorization_response_iss_parameter_supported=True,
        service_documentation=get_settings().documentation_url,
    )


def install_oauth_routes(app: FastAPI) -> None:
    """Mount the protocol endpoints. They are plain Starlette routes, outside the OpenAPI
    document: their shape is the OAuth specification, not ours."""
    registration = ClientRegistrationOptions(
        enabled=True,
        valid_scopes=list(SUPPORTED_SCOPES),
        default_scopes=list(SUPPORTED_SCOPES),
    )
    authenticator = ClientAuthenticator(provider)
    authorize = AuthorizationHandler(provider)
    token = TokenHandler(provider, authenticator)
    register = RegistrationHandler(provider, options=registration)
    revoke = RevocationHandler(provider, authenticator)

    async def metadata(_: Request) -> Response:
        return JSONResponse(
            authorization_server_metadata().model_dump(mode="json", exclude_none=True),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    app.add_route(METADATA_PATH, metadata, methods=["GET"], include_in_schema=False)
    app.add_route(
        f"{OAUTH_PREFIX}/authorize",
        authorize.handle,
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    app.add_route(f"{OAUTH_PREFIX}/token", token.handle, methods=["POST"], include_in_schema=False)
    app.add_route(
        f"{OAUTH_PREFIX}/register", register.handle, methods=["POST"], include_in_schema=False
    )
    app.add_route(
        f"{OAUTH_PREFIX}/revoke", revoke.handle, methods=["POST"], include_in_schema=False
    )


# Consent


async def _pending_request(session: AsyncSession, request_id: Any) -> OAuthAuthorizationCode:
    row = await session.get(OAuthAuthorizationCode, request_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Authorization request not found")
    if row.user_id is not None or row.used_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "This authorization request was already answered")
    if row.expires_at < _now():
        raise HTTPException(status.HTTP_410_GONE, "This authorization request has expired")
    return row


def _client_host(client: OAuthClient) -> str | None:
    if client.kind == OAuthClientKind.METADATA_DOCUMENT:
        return urlparse(client.client_id).hostname
    return urlparse(client.client_uri).hostname if client.client_uri else None


@router.get("/consent/{request_id}", response_model=ConsentInfo)
async def consent_info(
    request_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentInfo:
    row = await _pending_request(session, request_id)
    client = await session.get(OAuthClient, row.client_id)
    assert client is not None
    return ConsentInfo(
        request_id=row.id,
        client_id=client.client_id,
        client_name=client.client_name,
        client_uri=client.client_uri,
        client_host=_client_host(client),
        registration=client.kind,
        redirect_uri=row.redirect_uri,
        redirect_host=urlparse(row.redirect_uri).hostname or row.redirect_uri,
        loopback_redirect=is_loopback(row.redirect_uri),
        scopes=[ScopeInfo(key=s, description=SCOPE_DESCRIPTIONS.get(s, s)) for s in row.scopes],
        expires_at=row.expires_at,
    )


@router.post("/consent/{request_id}/approve", response_model=ConsentDecision)
async def approve_consent(
    request_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentDecision:
    row = await _pending_request(session, request_id)
    row.user_id = user.id
    row.code = secrets.token_urlsafe(32)
    row.code_expires_at = _now() + timedelta(seconds=get_settings().oauth_code_lifetime_seconds)
    await record_audit(
        session,
        user=user,
        action="oauth.consent_granted",
        object_type="oauth_client",
        object_id=row.client_id[:128],
        details={"scopes": row.scopes, "redirect_uri": row.redirect_uri},
    )
    await session.commit()
    return ConsentDecision(
        redirect_to=construct_redirect_uri(
            row.redirect_uri, code=row.code, state=row.state, iss=issuer_url()
        )
    )


@router.post("/consent/{request_id}/deny", response_model=ConsentDecision)
async def deny_consent(
    request_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> ConsentDecision:
    row = await _pending_request(session, request_id)
    row.used_at = _now()
    await record_audit(
        session,
        user=user,
        action="oauth.consent_denied",
        object_type="oauth_client",
        object_id=row.client_id[:128],
    )
    await session.commit()
    return ConsentDecision(
        redirect_to=construct_redirect_uri(
            row.redirect_uri,
            error="access_denied",
            error_description="The user denied the request",
            state=row.state,
            iss=issuer_url(),
        )
    )


# Connections: the AI clients a user has authorized


@router.get("/connections", response_model=list[ConnectionRead])
async def list_connections(
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[ConnectionRead]:
    """Clients holding a live refresh token for the caller, one row per client."""
    now = _now()
    rows = (
        await session.execute(
            select(
                OAuthClient,
                func.min(OAuthRefreshToken.created_at),
                func.max(OAuthRefreshToken.last_used_at),
                func.count(OAuthRefreshToken.id),
            )
            .join(OAuthRefreshToken, OAuthRefreshToken.client_id == OAuthClient.client_id)
            .where(
                OAuthRefreshToken.user_id == user.id,
                OAuthRefreshToken.revoked_at.is_(None),
                OAuthRefreshToken.expires_at > now,
            )
            .group_by(OAuthClient.client_id)
            .order_by(func.min(OAuthRefreshToken.created_at))
            .limit(limit)
        )
    ).all()
    result = []
    for client, first, last_used, count in rows:
        latest = await session.scalar(
            select(OAuthRefreshToken.scopes)
            .where(
                OAuthRefreshToken.user_id == user.id,
                OAuthRefreshToken.client_id == client.client_id,
                OAuthRefreshToken.revoked_at.is_(None),
            )
            .order_by(OAuthRefreshToken.created_at.desc())
            .limit(1)
        )
        result.append(
            ConnectionRead(
                client_id=client.client_id,
                client_name=client.client_name,
                client_uri=client.client_uri,
                client_host=_client_host(client),
                registration=client.kind,
                scopes=list(latest or []),
                first_authorized_at=first,
                last_used_at=last_used,
                active_tokens=count,
            )
        )
    return result


@router.post("/connections/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connection(
    body: ConnectionRevoke,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Ends every session of one client for the caller: refresh tokens are revoked at once and
    the access token expires within its lifetime."""
    tokens = (
        await session.scalars(
            select(OAuthRefreshToken).where(
                OAuthRefreshToken.user_id == user.id,
                OAuthRefreshToken.client_id == body.client_id,
                OAuthRefreshToken.revoked_at.is_(None),
            )
        )
    ).all()
    if not tokens:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active connection for this client")
    for token in tokens:
        token.revoked_at = _now()
    await record_audit(
        session,
        user=user,
        action="oauth.connection_revoked",
        object_type="oauth_client",
        object_id=body.client_id[:128],
        details={"tokens": len(tokens)},
    )
    await session.commit()
