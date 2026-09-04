"""OAuth 2.1 for AI clients (phase 9): metadata, dynamic registration, a client id metadata
document, the consent flow with PKCE, token exchange and refresh rotation, the access token on
the API (read-only, scoped, audited), connections and revocation."""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from protect_api.oauth import routes as oauth_routes
from shared.models import AuditLog
from shared.oauth import READ_SCOPES, decode_access_token
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

ISSUER = "http://localhost:3000"
RESOURCE = f"{ISSUER}/mcp"
REDIRECT = "http://localhost:4711/callback"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register(client, **overrides):
    body = {
        "client_name": "Test assistant",
        "redirect_uris": ["http://localhost/callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        **overrides,
    }
    response = await client.post("/api/v1/oauth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _authorize(client, client_id, challenge, *, scope=None, redirect=REDIRECT):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": RESOURCE,
    }
    if scope:
        params["scope"] = scope
    response = await client.get("/api/v1/oauth/authorize", params=params)
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/oauth/consent?request=")
    return parse_qs(urlparse(location).query)["request"][0]


async def _approve(client, user, request_id):
    response = await client.post(
        f"/api/v1/oauth/consent/{request_id}/approve", headers=user.headers
    )
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["redirect_to"]).query)
    assert query["state"] == ["xyz"]
    assert query["iss"] == [ISSUER]
    return query["code"][0]


async def _token(client, client_id, code, verifier, redirect=REDIRECT):
    return await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )


async def _connect(client, user, *, scope=None):
    """Register, authorize, consent and exchange: the tokens of a fresh connection."""
    registered = await _register(client)
    verifier, challenge = _pkce()
    request_id = await _authorize(client, registered["client_id"], challenge, scope=scope)
    code = await _approve(client, user, request_id)
    response = await _token(client, registered["client_id"], code, verifier)
    assert response.status_code == 200, response.text
    return registered, response.json()


async def test_authorization_server_metadata(client):
    response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["issuer"] == ISSUER
    assert metadata["authorization_endpoint"] == f"{ISSUER}/api/v1/oauth/authorize"
    assert metadata["token_endpoint"] == f"{ISSUER}/api/v1/oauth/token"
    assert metadata["registration_endpoint"] == f"{ISSUER}/api/v1/oauth/register"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["client_id_metadata_document_supported"] is True
    assert "none" in metadata["token_endpoint_auth_methods_supported"]
    assert set(READ_SCOPES) <= set(metadata["scopes_supported"])


async def test_registration_refuses_plain_http_redirects(client):
    response = await client.post(
        "/api/v1/oauth/register",
        json={
            "client_name": "Bad",
            "redirect_uris": ["http://example.org/callback"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_full_flow_and_scoped_access(client, db):
    project = await create_project(db)
    user = await project_actor(client, db, project, "project-viewer")
    registered, tokens = await _connect(client, user)
    assert tokens["token_type"] == "Bearer"
    access = decode_access_token(tokens["access_token"])
    assert access is not None
    assert access.user_id == user.user.id
    assert access.client_id == registered["client_id"]
    assert set(access.scopes) >= set(READ_SCOPES)
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Protect-MCP-Tool": "list_projects",
    }

    # Reads within scope work as the user, and every request is audited with the tool.
    projects = await client.get("/api/v1/projects", headers=headers)
    assert projects.status_code == 200, projects.text
    assert [p["id"] for p in projects.json()["items"]] == [str(project.id)]
    entities = await client.get(f"/api/v1/projects/{project.id}/entities", headers=headers)
    assert entities.status_code == 200
    rows = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.action == "mcp.request", AuditLog.user_id == user.user.id
            )
        )
    ).all()
    assert {r.details["tool"] for r in rows} == {"list_projects"}
    assert {r.actor_type for r in rows} == {"mcp"}
    assert any(r.project_id == project.id for r in rows)

    # Writes never, whatever the scopes.
    write = await client.post("/api/v1/projects", json={"name": "x", "slug": "x"}, headers=headers)
    assert write.status_code == 403
    assert write.headers["www-authenticate"].startswith('Bearer error="insufficient_scope"')

    # Paths outside the policy never.
    admin = await client.get("/api/v1/admin/users", headers=headers)
    assert admin.status_code == 403

    # A session token still works everywhere it did.
    assert (await client.get("/api/v1/projects", headers=user.headers)).status_code == 200


async def test_missing_scope_is_403_with_challenge(client, db):
    project = await create_project(db)
    user = await project_actor(client, db, project, "project-viewer")
    _, tokens = await _connect(client, user, scope="projects:read")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get("/api/v1/projects", headers=headers)).status_code == 200
    devices = await client.get("/api/v1/devices", headers=headers)
    assert devices.status_code == 403
    assert 'scope="devices:read"' in devices.headers["www-authenticate"]


async def test_pkce_and_code_reuse(client, db):
    user = await actor(client, db)
    registered = await _register(client)
    verifier, challenge = _pkce()
    request_id = await _authorize(client, registered["client_id"], challenge)
    code = await _approve(client, user, request_id)
    wrong = await _token(client, registered["client_id"], code, "not-the-verifier")
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"
    right = await _token(client, registered["client_id"], code, verifier)
    assert right.status_code == 200
    again = await _token(client, registered["client_id"], code, verifier)
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


async def test_refresh_rotates_and_revocation_ends_the_connection(client, db):
    user = await actor(client, db)
    registered, tokens = await _connect(client, user)
    refreshed = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": registered["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    replay = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": registered["client_id"],
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"

    connections = await client.get("/api/v1/oauth/connections", headers=user.headers)
    assert connections.status_code == 200
    listed = [c for c in connections.json() if c["client_id"] == registered["client_id"]]
    assert len(listed) == 1
    assert listed[0]["client_name"] == "Test assistant"
    assert listed[0]["registration"] == "dynamic"

    revoke = await client.post(
        "/api/v1/oauth/connections/revoke",
        json={"client_id": registered["client_id"]},
        headers=user.headers,
    )
    assert revoke.status_code == 204
    after = await client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refreshed.json()["refresh_token"],
            "client_id": registered["client_id"],
        },
    )
    assert after.status_code == 400
    gone = await client.get("/api/v1/oauth/connections", headers=user.headers)
    assert all(c["client_id"] != registered["client_id"] for c in gone.json())


async def test_consent_can_be_denied_and_needs_a_user(client, db):
    user = await actor(client, db)
    registered = await _register(client)
    _, challenge = _pkce()
    request_id = await _authorize(client, registered["client_id"], challenge)
    anonymous = await client.get(f"/api/v1/oauth/consent/{request_id}")
    assert anonymous.status_code == 401
    info = await client.get(f"/api/v1/oauth/consent/{request_id}", headers=user.headers)
    assert info.status_code == 200, info.text
    assert info.json()["client_name"] == "Test assistant"
    assert info.json()["loopback_redirect"] is True
    assert {s["key"] for s in info.json()["scopes"]} >= set(READ_SCOPES)
    denied = await client.post(f"/api/v1/oauth/consent/{request_id}/deny", headers=user.headers)
    assert denied.status_code == 200
    query = parse_qs(urlparse(denied.json()["redirect_to"]).query)
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["xyz"]
    again = await client.post(f"/api/v1/oauth/consent/{request_id}/approve", headers=user.headers)
    assert again.status_code == 410


async def test_authorize_rejects_other_resources_and_unregistered_redirects(client):
    registered = await _register(client)
    _, challenge = _pkce()
    other = await client.get(
        "/api/v1/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": "https://elsewhere.example/mcp",
        },
    )
    assert other.status_code == 302
    assert "error=invalid_target" in other.headers["location"]
    foreign = await client.get(
        "/api/v1/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": "https://attacker.example/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert foreign.status_code == 400


async def test_client_id_metadata_document(client, db):
    """A client identified by the URL of its metadata document (Claude, ChatGPT): fetched,
    validated as self-referential, redirect URIs on its own host or loopback."""
    client_id = f"https://{unique_name('assistant')}.example/oauth/client.json"
    host = urlparse(client_id).hostname

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == client_id
        return httpx.Response(
            200,
            json={
                "client_id": client_id,
                "client_name": "Hosted assistant",
                "client_uri": f"https://{host}",
                "redirect_uris": [f"https://{host}/callback", "http://127.0.0.1/callback"],
                "token_endpoint_auth_method": "none",
            },
        )

    oauth_routes.provider._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        user = await actor(client, db)
        verifier, challenge = _pkce()
        # The loopback port varies per session and is ignored (RFC 8252 section 7.3).
        redirect = "http://127.0.0.1:53211/callback"
        request_id = await _authorize(client, client_id, challenge, redirect=redirect)
        info = await client.get(f"/api/v1/oauth/consent/{request_id}", headers=user.headers)
        assert info.json()["client_host"] == host
        assert info.json()["registration"] == "metadata_document"
        code = await _approve(client, user, request_id)
        response = await _token(client, client_id, code, verifier, redirect=redirect)
        assert response.status_code == 200, response.text
        assert decode_access_token(response.json()["access_token"]) is not None
    finally:
        oauth_routes.provider._http = None


async def test_metadata_document_must_be_self_referential(client):
    client_id = f"https://{unique_name('bad')}.example/client.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "client_id": "https://someone-else.example/client.json",
                "client_name": "Impostor",
                "redirect_uris": ["https://someone-else.example/callback"],
            },
        )

    oauth_routes.provider._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        _, challenge = _pkce()
        response = await client.get(
            "/api/v1/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "https://someone-else.example/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"
    finally:
        oauth_routes.provider._http = None
