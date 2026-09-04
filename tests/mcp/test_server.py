"""The MCP server end to end: discovery documents, the bearer requirement, tools over
streamable HTTP with a real access token against the real API, scopes and the audit trail."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from protect_api.main import app as api_app
from protect_mcp.api import ProtectApi
from protect_mcp.main import create_app
from shared.models import AuditLog
from shared.oauth import ALL_SCOPES, READ_SCOPES, mint_access_token
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

ISSUER = "http://localhost:3000"
RESOURCE = f"{ISSUER}/mcp"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@asynccontextmanager
async def mcp_session():
    """An httpx client on the MCP ASGI app whose API calls go to the API app in process. Entered
    inside the test, because the SDK's session manager must start and stop in one task."""
    api = ProtectApi(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://api")
    )
    app = create_app(api)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp") as mcp,
    ):
        yield mcp
    await api.aclose()


async def rpc(mcp_client, token, method, params=None, id_=1):
    response = await mcp_client.post(
        "/mcp",
        headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
    )
    return response


def call(mcp_client, token, name, arguments):
    return rpc(mcp_client, token, "tools/call", {"name": name, "arguments": arguments})


def result_of(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def structured(response):
    result = result_of(response)
    assert not result.get("isError"), result
    return result["structuredContent"]


async def _fixture(client, db):
    """A project with an entity, a device assigned to it and a viewer member."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    viewer = await project_actor(client, db, project, "project-viewer")
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("animal").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.rhino",
            },
            headers=admin.headers,
        )
    ).json()
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=admin.headers,
        )
    ).json()
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("collar").replace("-", "_"),
                "label": "OpenCollar",
                "driver_key": "opencollar",
            },
            headers=admin.headers,
        )
    ).json()
    device_name = unique_name("SP05")
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type["id"], "name": device_name, "status": "active"},
            headers=admin.headers,
        )
    ).json()
    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": since},
        headers=admin.headers,
    )
    assert assigned.status_code == 201, assigned.text
    attached = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={"device_id": device["id"], "entity_id": entity["id"], "valid_from": since},
        headers=admin.headers,
    )
    assert attached.status_code == 201, attached.text
    return project, viewer, entity, device


async def test_discovery_and_bearer_requirement():
    async with mcp_session() as mcp_client:
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-protected-resource/mcp",
        ):
            response = await mcp_client.get(path)
            assert response.status_code == 200, path
            document = response.json()
            assert document["resource"] == RESOURCE
            assert document["authorization_servers"] == [ISSUER]
            assert set(READ_SCOPES) <= set(document["scopes_supported"]) <= set(ALL_SCOPES)
        unauthenticated = await mcp_client.post(
            "/mcp", headers=MCP_HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        assert unauthenticated.status_code == 401
        challenge = unauthenticated.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        assert f'resource_metadata="{ISSUER}/.well-known/oauth-protected-resource/mcp"' in challenge
        bad = await mcp_client.post(
            "/mcp",
            headers={**MCP_HEADERS, "Authorization": "Bearer not-a-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert bad.status_code == 401


async def test_missing_scope_is_403_with_challenge(db, client):
    async with mcp_session() as mcp_client:
        user = await actor(client, db)
        token, _ = mint_access_token(user.user.id, "test-client", ["projects:read"])
        response = await rpc(mcp_client, token, "tools/list")
        assert response.status_code == 403
        assert 'error="insufficient_scope"' in response.headers["www-authenticate"]


async def test_tools_list_and_read_only_tools(db, client):
    async with mcp_session() as mcp_client:
        project, viewer, entity, device = await _fixture(client, db)
        token, _ = mint_access_token(viewer.user.id, "test-client", list(READ_SCOPES))

        listed = result_of(await rpc(mcp_client, token, "tools/list"))
        names = {t["name"] for t in listed["tools"]}
        assert names >= {
            "list_projects",
            "search_entities",
            "get_entity",
            "get_device",
            "get_latest_position",
            "query_measurements",
            "query_events",
            "get_processing_trace",
            "search",
            "fetch",
        }

        projects = structured(await call(mcp_client, token, "list_projects", {}))
        assert [p["id"] for p in projects["projects"]] == [str(project.id)]
        assert projects["projects"][0]["role"] == "project-viewer"

        found = structured(
            await call(
                mcp_client,
                token,
                "search_entities",
                {"project_id": str(project.id), "query": "rhino"},
            )
        )
        assert [e["name"] for e in found["entities"]] == ["Rhino 14"]
        assert found["entities"][0]["entity_type"] == "Animal"

        detail = structured(
            await call(
                mcp_client,
                token,
                "get_entity",
                {"project_id": str(project.id), "entity_id": entity["id"]},
            )
        )
        assert detail["current_devices"][0]["device_id"] == device["id"]
        assert detail["latest_position"] is None

        dev = structured(await call(mcp_client, token, "get_device", {"device_id": device["id"]}))
        assert dev["name"] == device["name"]
        assert dev["driver"] == "opencollar"
        assert dev["url"] == f"{ISSUER}/projects/{project.id}/devices/{device['id']}"

        events = structured(
            await call(mcp_client, token, "query_events", {"project_id": str(project.id)})
        )
        assert events["events"] == []

        hits = structured(await call(mcp_client, token, "search", {"query": "SP05"}))
        assert [h["id"] for h in hits["results"]] == [f"smartparks://devices/{device['id']}"]
        fetched = structured(
            await call(mcp_client, token, "fetch", {"id": hits["results"][0]["id"]})
        )
        assert fetched["title"] == device["name"]
        assert json.loads(fetched["text"])["kind"] == "device"

        # A tool error carries the API's answer, never a crash.
        missing = result_of(
            await call(
                mcp_client,
                token,
                "get_entity",
                {"project_id": str(project.id), "entity_id": str(uuid.uuid4())},
            )
        )
        assert missing["isError"] is True
        assert "404" in missing["content"][0]["text"]

        # Resources and prompts are listed and readable.
        templates = result_of(await rpc(mcp_client, token, "resources/templates/list"))
        assert {t["uriTemplate"] for t in templates["resourceTemplates"]} >= {
            "smartparks://projects/{project_id}",
            "smartparks://devices/{device_id}",
        }
        read = result_of(
            await rpc(
                mcp_client, token, "resources/read", {"uri": f"smartparks://devices/{device['id']}"}
            )
        )
        assert json.loads(read["contents"][0]["text"])["name"] == device["name"]
        prompts = result_of(await rpc(mcp_client, token, "prompts/list"))
        assert {p["name"] for p in prompts["prompts"]} == {
            "analyze_device_health",
            "investigate_missing_data",
        }

        # Every API call made by a tool is in the audit log with the tool name and the client.
        await db.rollback()
        rows = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "mcp.request", AuditLog.user_id == viewer.user.id
                )
            )
        ).all()
        tools = {r.details["tool"] for r in rows}
        # `fetch` of a device delegates to `get_device`, so the API sees that tool name.
        assert {"list_projects", "search_entities", "get_entity", "get_device", "search"} <= tools
        assert {r.details["client_id"] for r in rows} == {"test-client"}
        assert {r.actor_type for r in rows} == {"mcp"}


async def test_no_membership_means_no_data(db, client):
    async with mcp_session() as mcp_client:
        project, _, entity, _ = await _fixture(client, db)
        outsider = await actor(client, db)
        token, _ = mint_access_token(outsider.user.id, "test-client", list(READ_SCOPES))
        projects = structured(await call(mcp_client, token, "list_projects", {}))
        assert projects["projects"] == []
        refused = result_of(
            await call(
                mcp_client,
                token,
                "get_entity",
                {"project_id": str(project.id), "entity_id": entity["id"]},
            )
        )
        assert refused["isError"] is True
        assert "403" in refused["content"][0]["text"]


async def test_write_tools_follow_the_policy_and_confirmation(db, client):
    """The write tools (decision D87) go through the API's AI action endpoint: a proposal that
    needs confirmation, then `confirm_action`, then the event exists."""
    async with mcp_session() as mcp_client:
        project, _viewer, entity, _device = await _fixture(client, db)
        admin_member = await project_actor(client, db, project, "project-admin")
        token, _ = mint_access_token(admin_member.user.id, "test-client", list(ALL_SCOPES))
        listed = result_of(await rpc(mcp_client, token, "tools/list"))
        names = {t["name"] for t in listed["tools"]}
        assert {
            "create_event",
            "acknowledge_alert",
            "request_device_status",
            "request_device_position",
            "confirm_action",
            "get_ai_policy",
        } <= names
        policy = structured(await call(mcp_client, token, "get_ai_policy", {}))
        assert policy["policy"]["create_event"] == "confirmation"
        proposed = structured(
            await call(
                mcp_client,
                token,
                "create_event",
                {
                    "project_id": str(project.id),
                    "event_type": "SIGHTING",
                    "title": "Rhino 14 at the waterhole",
                    "entity_id": entity["id"],
                    "latitude": -24.9,
                    "longitude": 31.5,
                },
            )
        )
        assert (
            proposed["status"] == "confirmation_required"
            and "confirm_action" in proposed["next_step"]
        )
        done = structured(
            await call(mcp_client, token, "confirm_action", {"action_id": proposed["id"]})
        )
        assert (
            done["status"] == "executed" and done["result"]["title"] == "Rhino 14 at the waterhole"
        )
        events = (
            await client.get(
                f"/api/v1/projects/{project.id}/events",
                params={"limit": 5},
                headers=admin_member.headers,
            )
        ).json()["items"]
        assert events[0]["title"] == "Rhino 14 at the waterhole"
        # a read-only token cannot write
        read_token, _ = mint_access_token(admin_member.user.id, "test-client", list(READ_SCOPES))
        refused = result_of(
            await call(
                mcp_client,
                read_token,
                "acknowledge_alert",
                {"project_id": str(project.id), "alert_id": str(uuid.uuid4())},
            )
        )
        assert refused.get("isError") and "alerts:write" in refused["content"][0]["text"]
