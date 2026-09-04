"""The access matrix (decision D94): every operation of the API, walked with an anonymous
caller, a viewer of another project, and an AI client with read scopes. The expectations are
structural (which classes of paths must refuse whom), so a new endpoint that forgets its
dependency fails here."""

import re
import uuid

import pytest

from protect_api.main import app
from shared.enums import Role
from shared.oauth import READ_SCOPES, mint_access_token
from tests.api.conftest import create_project, project_actor

pytestmark = pytest.mark.asyncio

# Operations anyone may call (the auth flow, health, the webhook with its own token).
OPEN = {
    ("GET", "/api/health"),
    ("GET", "/api/version"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    ("GET", "/api/v1/auth/invitation"),
    ("POST", "/api/v1/ingest/http/{data_source_id}"),
}
# Paths only server admins may use, by prefix.
SERVER_ADMIN_PREFIXES = (
    "/api/v1/admin/",
    "/api/v1/backups",
    "/api/v1/data-sources",
)
# Server admin writes on the shared catalogue; reads are open to members.
CATALOG = re.compile(r"^/api/v1/(entity-types|device-types|metrics|icons)")
UUID_PARAMS = re.compile(r"\{([a-z_]*(id|ID))\}")


def operations() -> list[tuple[str, str]]:
    found = []
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            found.append((method.upper(), path))
    return sorted(found)


def fill(path: str, project_id: uuid.UUID) -> str:
    path = path.replace("{project_id}", str(project_id))
    path = UUID_PARAMS.sub(lambda m: str(uuid.uuid4()), path)
    return re.sub(r"\{[a-z_]+\}", "x", path)


def is_success(status: int) -> bool:
    return 200 <= status < 300


async def test_every_operation_is_listed():
    assert len(operations()) > 200


async def test_anonymous_callers_are_refused_everywhere(client):
    project_id = uuid.uuid4()
    leaks = []
    for method, path in operations():
        if (method, path) in OPEN:
            continue
        response = await client.request(method, fill(path, project_id))
        if response.status_code != 401:
            leaks.append((method, path, response.status_code))
    assert leaks == []


async def test_a_viewer_cannot_reach_other_projects_or_the_server_admin(client, db):
    own = await create_project(db)
    other = await create_project(db)
    viewer = await project_actor(client, db, own, Role.PROJECT_VIEWER)
    leaks = []
    for method, path in operations():
        if (method, path) in OPEN:
            continue
        if "{project_id}" in path:
            response = await client.request(
                method, fill(path, other.id), headers=viewer.headers, json={}
            )
            if response.status_code != 403:
                leaks.append(("other project", method, path, response.status_code))
        if path.startswith(SERVER_ADMIN_PREFIXES) or (CATALOG.match(path) and method != "GET"):
            response = await client.request(
                method, fill(path, own.id), headers=viewer.headers, json={}
            )
            if response.status_code != 403:
                leaks.append(("server admin", method, path, response.status_code))
    assert leaks == []


# Writes a viewer may make by design (the viewer permission set in shared/permissions.py):
# manual events and alert handling for rangers, exports, saved views, and the read-only rule
# test (a dry run over existing data).
VIEWER_WRITES_ALLOWED = {
    ("POST", "/api/v1/projects/{project_id}/events"),
    ("POST", "/api/v1/projects/{project_id}/alerts/{alert_id}/acknowledge"),
    ("POST", "/api/v1/projects/{project_id}/alerts/{alert_id}/resolve"),
    ("POST", "/api/v1/projects/{project_id}/exports"),
    ("POST", "/api/v1/projects/{project_id}/exports/{job_id}/reproduce"),
    ("POST", "/api/v1/projects/{project_id}/analytics/saved-views"),
    ("PATCH", "/api/v1/projects/{project_id}/analytics/saved-views/{view_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/analytics/saved-views/{view_id}"),
    ("POST", "/api/v1/projects/{project_id}/rules/{rule_id}/test"),
}


async def test_a_viewer_cannot_write_in_the_own_project(client, db):
    own = await create_project(db)
    viewer = await project_actor(client, db, own, Role.PROJECT_VIEWER)
    leaks = []
    for method, path in operations():
        if method == "GET" or "{project_id}" not in path or (method, path) in VIEWER_WRITES_ALLOWED:
            continue
        response = await client.request(method, fill(path, own.id), headers=viewer.headers, json={})
        if response.status_code != 403:
            leaks.append((method, path, response.status_code))
    assert leaks == []


async def test_an_ai_client_with_read_scopes_can_only_read(client, db):
    own = await create_project(db)
    admin = await project_actor(client, db, own, Role.PROJECT_ADMIN)
    token, _ = mint_access_token(admin.user.id, "matrix-client", list(READ_SCOPES))
    headers = {"Authorization": f"Bearer {token}"}
    leaks = []
    for method, path in operations():
        if (method, path) in OPEN or method == "GET":
            continue
        if path.startswith("/api/v1/mcp/actions"):
            continue  # the AI action endpoint, governed by the policy and the write scopes
        response = await client.request(method, fill(path, own.id), headers=headers, json={})
        if response.status_code != 403:
            leaks.append((method, path, response.status_code))
    assert leaks == []
