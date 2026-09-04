"""The authorization server provider behind the MCP SDK's OAuth handlers (decisions D68, D69,
D70). Clients register dynamically (RFC 7591) or by a client id metadata document fetched
from the client id URL; authorization codes wait for the user's consent on the frontend;
refresh tokens are stored hashed and rotated; access tokens are JWTs from `shared.oauth`."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.database import session_scope
from shared.enums import OAuthClientKind
from shared.logger import get_logger
from shared.models import OAuthAuthorizationCode, OAuthClient, OAuthRefreshToken, User
from shared.oauth import (
    ALL_SCOPES,
    OFFLINE_ACCESS,
    decode_access_token,
    issuer_url,
    mcp_resource_url,
    mint_access_token,
)
from shared.secrets import decrypt_json, encrypt_json

log = get_logger("api.oauth")

SUPPORTED_SCOPES: tuple[str, ...] = (*ALL_SCOPES, OFFLINE_ACCESS)
METADATA_DOCUMENT_MAX_BYTES = 65_536
METADATA_DOCUMENT_CACHE = timedelta(hours=1)
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def is_loopback(url: AnyUrl | str) -> bool:
    parsed = urlparse(str(url))
    return parsed.scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS


def _same_ignoring_port(a: AnyUrl | str, b: AnyUrl | str) -> bool:
    pa, pb = urlparse(str(a)), urlparse(str(b))
    return (pa.scheme, pa.hostname, pa.path, pa.query) == (
        pb.scheme,
        pb.hostname,
        pb.path,
        pb.query,
    )


class RegisteredClient(OAuthClientInformationFull):
    """A client as the handlers see it. Loopback redirect URIs match with the port ignored
    (RFC 8252 section 7.3): native clients bind an ephemeral port at runtime."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and is_loopback(redirect_uri):
            for registered in self.redirect_uris or []:
                if is_loopback(registered) and _same_ignoring_port(registered, redirect_uri):
                    return redirect_uri
            raise InvalidRedirectUriError(
                f"Redirect URI '{redirect_uri}' not registered for client"
            )
        return super().validate_redirect_uri(redirect_uri)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _client_from_row(row: OAuthClient) -> RegisteredClient:
    secret = None
    if row.client_secret_encrypted is not None:
        secret = str(decrypt_json(row.client_secret_encrypted)["secret"])
    return RegisteredClient.model_validate(
        {
            **row.document,
            "client_id": row.client_id,
            "client_secret": secret,
            "client_secret_expires_at": row.client_secret_expires_at,
            "token_endpoint_auth_method": row.token_endpoint_auth_method,
        }
    )


def _validate_redirect_uris(uris: list[AnyUrl] | None, *, same_host_as: str | None) -> None:
    """Every redirect URI is HTTPS or loopback (MCP authorization, communication security); a
    metadata document's URIs also share the document's host (client id metadata document,
    security considerations)."""
    if not uris:
        raise RegistrationError("invalid_redirect_uri", "redirect_uris is required")
    for uri in uris:
        parsed = urlparse(str(uri))
        if is_loopback(uri):
            continue
        if parsed.scheme != "https":
            raise RegistrationError(
                "invalid_redirect_uri", f"redirect URI {uri} must use https or loopback"
            )
        if same_host_as is not None and parsed.hostname != same_host_as:
            raise RegistrationError(
                "invalid_redirect_uri", f"redirect URI {uri} is not on the client's host"
            )


class ProtectAuthorizationServerProvider:
    """Implements `mcp.server.auth.provider.OAuthAuthorizationServerProvider`."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    # Clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with session_scope() as session:
            row = await session.get(OAuthClient, client_id)
            if row is not None and row.kind == OAuthClientKind.DYNAMIC:
                return _client_from_row(row)
            fresh = (
                row is not None
                and row.fetched_at is not None
                and _now() - row.fetched_at < METADATA_DOCUMENT_CACHE
            )
            if row is not None and fresh:
                return _client_from_row(row)
        if not _looks_like_metadata_url(client_id):
            return None
        document = await self._fetch_metadata_document(client_id)
        if document is None:
            return None
        async with session_scope() as session:
            row = await session.get(OAuthClient, client_id)
            if row is None:
                row = OAuthClient(client_id=client_id, kind=OAuthClientKind.METADATA_DOCUMENT)
                session.add(row)
            row.client_name = document.get("client_name")
            row.client_uri = document.get("client_uri")
            row.token_endpoint_auth_method = "none"
            row.document = document
            row.fetched_at = _now()
            await session.commit()
            return _client_from_row(row)

    async def _fetch_metadata_document(self, client_id: str) -> dict[str, Any] | None:
        """The client id metadata document at the client id URL, validated: self-referential,
        redirect URIs on its own host or loopback, a public client (authenticates with PKCE)."""
        headers = {"Accept": "application/json"}
        try:
            if self._http is not None:
                response = await self._http.get(client_id, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=5.0) as http:
                    response = await http.get(client_id, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("client metadata document unreachable", client_id=client_id, error=str(exc))
            return None
        if response.status_code != 200 or len(response.content) > METADATA_DOCUMENT_MAX_BYTES:
            log.warning(
                "client metadata document refused",
                client_id=client_id,
                status=response.status_code,
                size=len(response.content),
            )
            return None
        try:
            raw = response.json()
            data = raw if isinstance(raw, dict) else None
            if data is None or data.get("client_id") != client_id:
                raise ValueError("client_id in the document does not match its URL")
            metadata = OAuthClientInformationFull.model_validate(
                {
                    **data,
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "scope": " ".join(SUPPORTED_SCOPES),
                }
            )
            if not metadata.client_name:
                raise ValueError("client_name is required")
            _validate_redirect_uris(
                metadata.redirect_uris, same_host_as=urlparse(client_id).hostname
            )
        except (ValueError, RegistrationError) as exc:
            log.warning("client metadata document invalid", client_id=client_id, error=str(exc))
            return None
        stored = metadata.model_dump(mode="json", exclude_none=True)
        stored.pop("client_secret", None)
        return stored

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        _validate_redirect_uris(client_info.redirect_uris, same_host_as=None)
        document = client_info.model_dump(mode="json", exclude_none=True)
        document.pop("client_secret", None)
        async with session_scope() as session:
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    kind=OAuthClientKind.DYNAMIC,
                    client_name=client_info.client_name,
                    client_uri=str(client_info.client_uri) if client_info.client_uri else None,
                    token_endpoint_auth_method=client_info.token_endpoint_auth_method or "none",
                    client_secret_encrypted=(
                        encrypt_json({"secret": client_info.client_secret})
                        if client_info.client_secret
                        else None
                    ),
                    client_secret_expires_at=client_info.client_secret_expires_at,
                    document=document,
                )
            )
            await session.commit()
        log.info("oauth client registered", client_id=client_info.client_id)

    # Authorization

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource is not None and params.resource.rstrip("/") != mcp_resource_url():
            raise AuthorizeError(
                "invalid_target", f"This server issues tokens for {mcp_resource_url()} only"
            )
        # A client that asks for nothing gets everything it may hold; the person consents to
        # the list and the AI action policy gates every write (architecture 27.6).
        scopes = params.scopes or list(ALL_SCOPES)
        unknown = [s for s in scopes if s not in SUPPORTED_SCOPES]
        if unknown:
            raise AuthorizeError("invalid_scope", f"Unknown scopes: {', '.join(unknown)}")
        settings = get_settings()
        async with session_scope() as session:
            row = OAuthAuthorizationCode(
                client_id=client.client_id,
                scopes=scopes,
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource,
                state=params.state,
                expires_at=_now() + timedelta(seconds=settings.oauth_consent_lifetime_seconds),
            )
            session.add(row)
            await session.commit()
            request_id = row.id
        return f"{issuer_url()}/oauth/consent?request={request_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(OAuthAuthorizationCode).where(
                    OAuthAuthorizationCode.code == authorization_code,
                    OAuthAuthorizationCode.client_id == client.client_id,
                    OAuthAuthorizationCode.used_at.is_(None),
                    OAuthAuthorizationCode.user_id.is_not(None),
                )
            )
            if row is None or row.code_expires_at is None:
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=list(row.scopes),
                expires_at=row.code_expires_at.timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
                resource=row.resource,
                subject=str(row.user_id),
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        async with session_scope() as session:
            consumed = (
                await session.execute(
                    update(OAuthAuthorizationCode)
                    .where(
                        OAuthAuthorizationCode.code == authorization_code.code,
                        OAuthAuthorizationCode.used_at.is_(None),
                    )
                    .values(used_at=_now())
                    .returning(OAuthAuthorizationCode.user_id)
                )
            ).scalar_one_or_none()
            if consumed is None:
                raise TokenError("invalid_grant", "authorization code already used")
            user = await session.get(User, consumed)
            if user is None or not user.is_active:
                raise TokenError("invalid_grant", "user is not active")
            tokens = await self._issue(session, user, client.client_id, authorization_code.scopes)
            await session.commit()
        return tokens

    # Refresh tokens

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.token_hash == _hash(refresh_token),
                    OAuthRefreshToken.client_id == client.client_id,
                    OAuthRefreshToken.revoked_at.is_(None),
                )
            )
            if row is None:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=list(row.scopes),
                expires_at=int(row.expires_at.timestamp()),
                subject=str(row.user_id),
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        async with session_scope() as session:
            row = (
                await session.execute(
                    update(OAuthRefreshToken)
                    .where(
                        OAuthRefreshToken.token_hash == _hash(refresh_token.token),
                        OAuthRefreshToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=_now(), last_used_at=_now())
                    .returning(OAuthRefreshToken)
                )
            ).scalar_one_or_none()
            if row is None:
                raise TokenError("invalid_grant", "refresh token is revoked")
            user = await session.get(User, row.user_id)
            if user is None or not user.is_active:
                raise TokenError("invalid_grant", "user is not active")
            tokens = await self._issue(session, user, client.client_id, scopes)
            await session.commit()
        return tokens

    async def _issue(
        self, session: AsyncSession, user: User, client_id: str, scopes: list[str]
    ) -> OAuthToken:
        settings = get_settings()
        access_token, expires_in = mint_access_token(user.id, client_id, scopes)
        refresh = secrets.token_urlsafe(48)
        session.add(
            OAuthRefreshToken(
                token_hash=_hash(refresh),
                client_id=client_id,
                user_id=user.id,
                scopes=scopes,
                resource=mcp_resource_url(),
                expires_at=_now() + timedelta(days=settings.oauth_refresh_token_lifetime_days),
            )
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # Tokens

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = decode_access_token(token)
        if access is None:
            return None
        return AccessToken(
            token=token,
            client_id=access.client_id,
            scopes=access.scopes,
            expires_at=int(access.expires_at.timestamp()),
            resource=access.resource,
            subject=str(access.user_id),
            claims={"iss": issuer_url()},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with session_scope() as session:
            if isinstance(token, RefreshToken):
                condition = OAuthRefreshToken.token_hash == _hash(token.token)
            else:
                if token.subject is None:
                    return
                condition = (OAuthRefreshToken.client_id == token.client_id) & (
                    OAuthRefreshToken.user_id == token.subject
                )
            await session.execute(
                update(OAuthRefreshToken)
                .where(condition, OAuthRefreshToken.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
            await session.commit()

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "identity assertions are not supported")


def _looks_like_metadata_url(client_id: str) -> bool:
    parsed = urlparse(client_id)
    if parsed.scheme == "https" and parsed.hostname and parsed.path not in ("", "/"):
        return True
    # Loopback HTTP documents are accepted outside production so the flow can be exercised locally.
    return (
        parsed.scheme == "http"
        and (parsed.hostname or "") in LOOPBACK_HOSTS
        and get_settings().environment != "production"
    )
