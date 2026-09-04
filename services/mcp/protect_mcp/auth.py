"""Bearer verification for the MCP server: the JWT access tokens the API issues (audience: this
server), verified locally with the shared secret. No database access here (architecture 27.1)."""

from mcp.server.auth.provider import AccessToken

from shared.oauth import decode_access_token, issuer_url


class JWTTokenVerifier:
    """Implements `mcp.server.auth.provider.TokenVerifier`."""

    async def verify_token(self, token: str) -> AccessToken | None:
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
