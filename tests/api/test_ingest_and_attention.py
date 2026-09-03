"""Phase 2 exit criteria through the API: webhook to position with a trace, duplicate delivery,
unknown device through Needs Attention."""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from shared.bus import Topic
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _setup(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=h,
        )
    ).json()
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("Webhook"), "adapter_key": "generic_http"},
            headers=h,
        )
    ).json()
    assert (
        source["webhook_token"]
        and source["has_webhook_token"]
        and source["webhook_url"].endswith(f"/api/v1/ingest/http/{source['id']}")
    )
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("dev"),
                "status": "active",
            },
            headers=h,
        )
    ).json()
    external_id = uuid.uuid4().hex[:16].upper()
    await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": external_id},
        headers=h,
    )
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project.id.hex, "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    return admin, project, device_type, source, device, external_id


async def _decode_pending(db, bus):
    """Run the decoder over what the API published. The worker is not running in tests."""
    from protect_decoder.main import build_worker

    worker = build_worker()
    worker.bus = bus
    handler = worker._subscriptions[0][1]
    group = f"decoder-api-test-{uuid.uuid4().hex[:6]}"
    # start the group at the end of the stream so old test messages are not replayed
    import contextlib

    from redis.exceptions import ResponseError

    with contextlib.suppress(ResponseError):
        await bus.redis.xgroup_create(Topic.SOURCE_EVENT_RECEIVED, group, id="$", mkstream=True)
    return group, handler


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_webhook_to_position_with_trace_and_duplicate(client, db, bus):
    admin, project, _, source, _device, external_id = await _setup(client, db)
    group, handler = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    body = {
        "device_id": external_id,
        "time": "2026-03-20T10:00:00+00:00",
        "lat": -24.9,
        "lon": 31.5,
        "measurements": {"battery_voltage": 3.7},
    }

    assert (await client.post(f"/api/v1/ingest/http/{source['id']}", json=body)).status_code == 401
    assert (
        await client.post(
            f"/api/v1/ingest/http/{source['id']}",
            json=body,
            headers={"Authorization": "Bearer wrong"},
        )
    ).status_code == 401
    accepted = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    assert accepted.status_code == 202, accepted.text
    first_event = accepted.json()["source_event_ids"][0]
    trace_id = accepted.json()["trace_ids"][0]

    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)

    positions = await client.get(
        f"/api/v1/projects/{project.id}/positions",
        params={"from": "2026-03-20T00:00:00+00:00", "to": "2026-03-21T00:00:00+00:00"},
        headers=admin.headers,
    )
    assert positions.status_code == 200 and len(positions.json()) == 1
    position = positions.json()[0]
    assert position["geometry"] == {"type": "Point", "coordinates": [31.5, -24.9]}
    assert position["trace_id"] == trace_id and position["source_event_id"] == first_event

    trace = await client.get(f"/api/v1/traces/{trace_id}", headers=admin.headers)
    assert trace.status_code == 200 and trace.json()["status"] == "success"
    assert [s["operation"] for s in trace.json()["steps"]][-1] == "canonical rows written"

    # the same record again: one position, two deliveries
    again = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    second_event = again.json()["source_event_ids"][0]
    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    positions = await client.get(
        f"/api/v1/projects/{project.id}/positions",
        params={"from": "2026-03-20T00:00:00+00:00", "to": "2026-03-21T00:00:00+00:00"},
        headers=admin.headers,
    )
    assert len(positions.json()) == 1
    second = await client.get(
        f"/api/v1/source-events/{second_event}",
        params={"ingested_at": (await _ingested_at(db, second_event)).isoformat()},
        headers=admin.headers,
    )
    assert second.status_code == 200
    assert second.json()["processing_status"] == "duplicate"
    assert [(d["canonical_type"], d["first"]) for d in second.json()["deliveries"]] == [
        ("position", False),
        ("measurement", False),
    ]
    await bus.redis.xgroup_destroy(Topic.SOURCE_EVENT_RECEIVED, group)


async def _ingested_at(db, source_event_id: int) -> datetime:
    from sqlalchemy import select

    from shared.models import SourceEvent

    value = await db.scalar(
        select(SourceEvent.ingested_at).where(SourceEvent.id == source_event_id)
    )
    assert value is not None
    return value


async def test_unknown_device_needs_attention_then_processed(client, db, bus):
    admin, project, device_type, source, _device, _external = await _setup(client, db)
    group, handler = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    unknown = uuid.uuid4().hex[:16].upper()
    body = {"device_id": unknown, "time": "2026-03-21T10:00:00+00:00", "lat": -24.8, "lon": 31.4}
    accepted = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    assert accepted.status_code == 202
    event_id = accepted.json()["source_event_ids"][0]

    summary = (await client.get("/api/v1/attention/summary", headers=admin.headers)).json()
    assert summary["unknown_identities"] >= 1 and summary["unassigned_source_events"] >= 1
    identities = (await client.get("/api/v1/attention/identities", headers=admin.headers)).json()[
        "items"
    ]
    identity = next(i for i in identities if i["external_id"] == unknown)
    assert identity["event_count"] == 1 and identity["data_source_name"] == source["name"]

    created = await client.post(
        f"/api/v1/attention/identities/{identity['id']}/create-device",
        json={
            "name": unique_name("found"),
            "device_type_id": device_type["id"],
            "project_id": str(project.id),
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    positions = (
        await client.get(
            f"/api/v1/projects/{project.id}/positions",
            params={
                "from": "2026-03-21T00:00:00+00:00",
                "to": "2026-03-22T00:00:00+00:00",
                "device_id": created.json()["id"],
            },
            headers=admin.headers,
        )
    ).json()
    assert len(positions) == 1 and positions[0]["source_event_id"] == event_id
    identities = (await client.get("/api/v1/attention/identities", headers=admin.headers)).json()[
        "items"
    ]
    assert all(i["external_id"] != unknown for i in identities)
    audit = (
        await client.get("/api/v1/admin/audit", params={"limit": 20}, headers=admin.headers)
    ).json()
    assert any(e["action"] == "attention.device_created" for e in audit)
    await bus.redis.xgroup_destroy(Topic.SOURCE_EVENT_RECEIVED, group)


async def test_dead_letter_admin(client, db, bus):
    admin, _project, _, source, _device, external_id = await _setup(client, db)
    group, handler = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    accepted = await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        json={"device_id": external_id, "time": "garbage", "lat": 1, "lon": 2},
        headers=auth,
    )
    event_id = accepted.json()["source_event_ids"][0]
    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    dead = (
        await client.get(
            "/api/v1/attention/dead-letters",
            params={"topic": Topic.SOURCE_EVENT_RECEIVED},
            headers=admin.headers,
        )
    ).json()
    mine = [d for d in dead if d.get("trace_id") == accepted.json()["trace_ids"][0]]
    assert mine and mine[0]["error_code"] == "TIMESTAMP_INVALID"
    failed = (
        await client.get(
            "/api/v1/attention/source-events", params={"status": "failed"}, headers=admin.headers
        )
    ).json()
    assert any(e["id"] == event_id for e in failed)
    assert (
        await client.post(
            f"/api/v1/attention/dead-letters/{Topic.SOURCE_EVENT_RECEIVED}/{mine[0]['id']}/resolve",
            headers=admin.headers,
        )
    ).status_code == 204
    await bus.redis.xgroup_destroy(Topic.SOURCE_EVENT_RECEIVED, group)


async def test_viewer_cannot_see_attention_or_other_project_positions(client, db):
    from shared.enums import Role
    from tests.api.conftest import project_actor

    project = await create_project(db)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (
        await client.get("/api/v1/attention/summary", headers=viewer.headers)
    ).status_code == 403
    other = await create_project(db)
    assert (
        await client.get(f"/api/v1/projects/{other.id}/positions", headers=viewer.headers)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/projects/{project.id}/positions", headers=viewer.headers)
    ).status_code == 200
