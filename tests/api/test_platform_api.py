"""Phase 13 through the API: manual events, project icons, dashboards, Movebank exports, the
AI action policy and the AI action endpoint with its confirmation flow."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from shared.bus import RedisStreamsBus
from shared.connectivity.adapters.chirpstack import ChirpStackCommands
from shared.enums import Role
from shared.oauth import ALL_SCOPES, READ_SCOPES, mint_access_token
from tests.api.conftest import project_actor
from tests.api.test_control_api import fake_submit
from tests.api.test_curation_api import _rows
from tests.api.test_log_files_api import _opencollar_device
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="currentColor"/></svg>'


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_manual_events_icons_and_dashboards(client, db):
    admin, project, entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}"
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)

    # a viewer reports an event with a place; it appears in the list and on the map layer
    reported = await client.post(
        f"{base}/events",
        json={
            "event_type": "SIGHTING",
            "title": "Rhino 14 seen at the dam",
            "severity": "info",
            "entity_id": entity["id"],
            "latitude": -24.9,
            "longitude": 31.5,
            "create_alert": True,
        },
        headers=viewer.headers,
    )
    assert reported.status_code == 201, reported.text
    event = reported.json()
    assert (
        event["event_type"] == "SIGHTING"
        and event["alert_id"]
        and event["context"]["reported_by"] == str(viewer.user.id)
    )
    assert (
        await client.post(
            f"{base}/events", json={"event_type": "bad type", "title": "x"}, headers=h
        )
    ).status_code == 422
    listed = (await client.get(f"{base}/events", params={"limit": 5}, headers=h)).json()["items"]
    assert listed[0]["id"] == event["id"]

    # icons: validation, upload, override key, list, delete
    for bad in (
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil/x.png"/></svg>',
        "<div/>",
    ):
        response = await client.post(f"{base}/icons", json={"label": "Bad", "svg": bad}, headers=h)
        assert response.status_code == 422, bad
    uploaded = await client.post(
        f"{base}/icons", json={"label": "Pangolin walking", "svg": GOOD_SVG}, headers=h
    )
    assert uploaded.status_code == 201, uploaded.text
    icon = uploaded.json()
    assert icon["key"] == "project.pangolin_walking" and icon["svg"].startswith("<svg")
    assert (
        await client.post(
            f"{base}/icons",
            json={"label": "Pangolin walking", "svg": GOOD_SVG},
            headers=viewer.headers,
        )
    ).status_code == 403
    icons = (await client.get(f"{base}/icons", headers=viewer.headers)).json()
    assert [i["key"] for i in icons] == ["project.pangolin_walking"]
    typed = await client.post(
        "/api/v1/entity-types",
        json={
            "key": unique_name("pango").replace("-", "_"),
            "label": "Pangolin",
            "group_key": "tracked",
            "icon_key": "project.pangolin_walking",
        },
        headers=h,
    )
    assert typed.status_code == 201, typed.text
    assert (
        await client.delete(f"{base}/icons/project.pangolin_walking", headers=h)
    ).status_code == 204
    assert (await client.get(f"{base}/icons", headers=h)).json() == []

    # dashboards: saved view tiles must belong to the project
    view = (
        await client.post(
            f"{base}/analytics/saved-views",
            json={
                "name": "Battery",
                "view": {"metric": ["battery_voltage"], "range": ["7d"]},
                "schema_version": 1,
            },
            headers=h,
        )
    ).json()
    created = await client.post(
        f"{base}/dashboards",
        json={
            "name": "Operations",
            "tiles": [
                {"id": "map", "kind": "map", "size": "l"},
                {"id": "chart", "kind": "saved_view", "size": "m", "saved_view_id": view["id"]},
                {"id": "alerts", "kind": "alerts"},
            ],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    dashboard = created.json()
    assert [t["kind"] for t in dashboard["tiles"]] == ["map", "saved_view", "alerts"]
    wrong = await client.post(
        f"{base}/dashboards",
        json={
            "name": "Wrong",
            "tiles": [{"id": "x", "kind": "saved_view", "saved_view_id": str(uuid.uuid4())}],
        },
        headers=h,
    )
    assert wrong.status_code == 422
    assert (
        await client.post(f"{base}/dashboards", json={"name": "Operations", "tiles": []}, headers=h)
    ).status_code == 409
    updated = await client.patch(
        f"{base}/dashboards/{dashboard['id']}",
        json={"tiles": [{"id": "events", "kind": "events", "size": "s"}]},
        headers=h,
    )
    assert updated.status_code == 200 and [t["kind"] for t in updated.json()["tiles"]] == ["events"]
    assert (await client.get(f"{base}/dashboards", headers=viewer.headers)).json()["items"][0][
        "name"
    ] == "Operations"
    assert (
        await client.patch(
            f"{base}/dashboards/{dashboard['id']}", json={"name": "Nope"}, headers=viewer.headers
        )
    ).status_code == 403
    assert (
        await client.delete(f"{base}/dashboards/{dashboard['id']}", headers=h)
    ).status_code == 204


async def test_movebank_exports(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    await _rows(db, str(project.id), device["id"], entity["id"], count=2)
    base = f"/api/v1/projects/{project.id}/exports/direct"
    window = {"time_from": "2026-06-01T00:00:00+00:00", "time_to": "2026-08-01T00:00:00+00:00"}
    events = await client.get(
        base, params={"dataset": "movebank_events", "format": "csv", **window}, headers=h
    )
    assert events.status_code == 200, events.text
    lines = events.text.strip().splitlines()
    assert lines[0].split(",")[:6] == [
        "timestamp",
        "location-long",
        "location-lat",
        "sensor-type",
        "individual-local-identifier",
        "tag-local-identifier",
    ]
    assert (
        len(lines) == 3
        and ",GPS," in lines[1]
        and "Rhino 14" in lines[1]
        and lines[1].startswith("2026-07-01 03:14:00.000")
    )
    reference = await client.get(
        base, params={"dataset": "movebank_reference", "format": "csv", **window}, headers=h
    )
    assert reference.status_code == 200, reference.text
    rows = reference.text.strip().splitlines()
    assert rows[0].startswith("animal-id,tag-id,deploy-on-date,deploy-off-date,animal-taxon")
    assert (
        len(rows) == 2 and rows[1].startswith("Rhino 14,") and "2026-01-01 00:00:00.000" in rows[1]
    )
    assert (
        await client.get(
            base, params={"dataset": "movebank_events", "format": "gpx", **window}, headers=h
        )
    ).status_code == 422


async def test_ai_policy_and_action_flow(client, db, bus, monkeypatch):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    await _opencollar_device(client, db, device, h)
    policy = (await client.get("/api/v1/admin/ai-policy", headers=h)).json()
    assert (
        policy["policy"]["create_event"] == "confirmation"
        and policy["policy"]["high_impact_control"] == "disabled"
    )
    assert (
        await client.put(
            "/api/v1/admin/ai-policy", json={"policy": {"create_event": "sometimes"}}, headers=h
        )
    ).status_code == 422
    assert (
        await client.put(
            "/api/v1/admin/ai-policy",
            json={"policy": {"high_impact_control": "allowed"}},
            headers=h,
        )
    ).status_code == 422
    member = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    token, _ = mint_access_token(member.user.id, "claude", list(ALL_SCOPES))
    ai = {"Authorization": f"Bearer {token}"}
    # people cannot use the AI endpoint; AI tokens without the scope cannot either
    assert (
        await client.post(
            "/api/v1/mcp/actions",
            json={"action": "create_event", "parameters": {}},
            headers=member.headers,
        )
    ).status_code == 403
    read_only, _ = mint_access_token(member.user.id, "claude", list(READ_SCOPES))
    assert (
        await client.post(
            "/api/v1/mcp/actions",
            json={"action": "create_event", "parameters": {}},
            headers={"Authorization": f"Bearer {read_only}"},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/mcp/policy", headers=ai)).status_code == 200

    # default policy: confirmation, then execution by the same person and client
    params = {
        "project_id": str(project.id),
        "event_type": "SIGHTING",
        "title": "Seen by an AI assistant",
        "entity_id": entity["id"],
        "latitude": -24.9,
        "longitude": 31.5,
    }
    proposed = await client.post(
        "/api/v1/mcp/actions", json={"action": "create_event", "parameters": params}, headers=ai
    )
    assert proposed.status_code == 200, proposed.text
    pending = proposed.json()
    assert (
        pending["status"] == "confirmation_required"
        and "Seen by an AI assistant" in pending["summary"]
    )
    events_before = (
        await client.get(f"/api/v1/projects/{project.id}/events", params={"limit": 50}, headers=h)
    ).json()["items"]
    assert not any(e["title"] == "Seen by an AI assistant" for e in events_before)
    other_token, _ = mint_access_token(member.user.id, "chatgpt", list(ALL_SCOPES))
    assert (
        await client.post(
            f"/api/v1/mcp/actions/{pending['id']}/confirm",
            headers={"Authorization": f"Bearer {other_token}"},
        )
    ).status_code == 404
    confirmed = await client.post(f"/api/v1/mcp/actions/{pending['id']}/confirm", headers=ai)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "executed" and confirmed.json()["result"]["event_id"]
    assert (
        await client.post(f"/api/v1/mcp/actions/{pending['id']}/confirm", headers=ai)
    ).status_code == 409
    state = (await client.get(f"/api/v1/mcp/actions/{pending['id']}", headers=ai)).json()
    assert state["status"] == "executed"
    events = (
        await client.get(f"/api/v1/projects/{project.id}/events", params={"limit": 50}, headers=h)
    ).json()["items"]
    created = next(e for e in events if e["title"] == "Seen by an AI assistant")
    assert created["context"]["actor"] == "mcp" and created["context"]["client_id"] == "claude"

    # allowed: executed at once; disabled: refused
    assert (
        await client.put(
            "/api/v1/admin/ai-policy",
            json={"policy": {"acknowledge_alert": "allowed", "request_device_status": "disabled"}},
            headers=h,
        )
    ).status_code == 200
    alert_event = (
        await client.post(
            f"/api/v1/projects/{project.id}/events",
            json={"event_type": "TEST", "title": "needs a person", "create_alert": True},
            headers=h,
        )
    ).json()
    acked = await client.post(
        "/api/v1/mcp/actions",
        json={
            "action": "acknowledge_alert",
            "parameters": {
                "project_id": str(project.id),
                "alert_id": alert_event["alert_id"],
                "note": "AI on it",
            },
        },
        headers=ai,
    )
    assert (
        acked.status_code == 200
        and acked.json()["status"] == "executed"
        and acked.json()["result"]["status"] == "acknowledged"
    )
    refused = await client.post(
        "/api/v1/mcp/actions",
        json={"action": "request_device_status", "parameters": {"device_id": device["id"]}},
        headers=ai,
    )
    assert refused.status_code == 403 and "disabled" in refused.json()["detail"]

    # operational control through the normal command path, with the MCP actor
    assert (
        await client.put(
            "/api/v1/admin/ai-policy",
            json={"policy": {"request_device_position": "allowed"}},
            headers=h,
        )
    ).status_code == 200
    submit, _calls = fake_submit(
        [{"provider_ref": "q1", "statuses": ["accepted_by_network", "queued"]}]
    )
    monkeypatch.setattr(ChirpStackCommands, "submit", submit)
    positioned = await client.post(
        "/api/v1/mcp/actions",
        json={"action": "request_device_position", "parameters": {"device_id": device["id"]}},
        headers=ai,
    )
    assert positioned.status_code == 200, positioned.text
    result = positioned.json()["result"]
    assert result["action_key"] == "REQUEST_POSITION" and result["status"] == "queued"
    detail = (await client.get(f"/api/v1/commands/{result['command_id']}", headers=h)).json()
    assert (
        detail["command"]["actor"]["kind"] == "mcp"
        and detail["command"]["actor"]["client"] == "claude"
    )
    # a viewer lacks device control: refused with the permission
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    viewer_token, _ = mint_access_token(viewer.user.id, "claude", list(ALL_SCOPES))
    assert (
        await client.post(
            "/api/v1/mcp/actions",
            json={"action": "request_device_position", "parameters": {"device_id": device["id"]}},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
    ).status_code == 403
    # expired proposals cannot be confirmed
    from shared.models import McpPendingAction

    row = await db.get(McpPendingAction, uuid.UUID(pending["id"]))
    row.executed_at = None
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    assert (
        await client.post(f"/api/v1/mcp/actions/{pending['id']}/confirm", headers=ai)
    ).status_code == 409
