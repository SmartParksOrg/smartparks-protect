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
    handlers = dict(worker._subscriptions)
    group = f"decoder-api-test-{uuid.uuid4().hex[:6]}"
    # start the groups at the end of the streams so old test messages are not replayed
    import contextlib

    from redis.exceptions import ResponseError

    for topic in (Topic.SOURCE_EVENT_RECEIVED, Topic.IDENTITY_REPROCESS_REQUESTED):
        with contextlib.suppress(ResponseError):
            await bus.redis.xgroup_create(topic, group, id="$", mkstream=True)
    return (
        group,
        handlers[Topic.SOURCE_EVENT_RECEIVED],
        handlers[Topic.IDENTITY_REPROCESS_REQUESTED],
    )


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_webhook_to_position_with_trace_and_duplicate(client, db, bus):
    admin, project, _, source, _device, external_id = await _setup(client, db)
    group, handler, _walk = await _decode_pending(db, bus)
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
    group, _handler, walk = await _decode_pending(db, bus)
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
    # decision D236: a source assigned to one project proposes it for the device to create
    assert identity["suggested_project_id"] is None
    from shared.models import DataSourceProjectScope

    db.add(DataSourceProjectScope(data_source_id=uuid.UUID(source["id"]), project_id=project.id))
    await db.commit()
    identities = (await client.get("/api/v1/attention/identities", headers=admin.headers)).json()[
        "items"
    ]
    identity = next(i for i in identities if i["external_id"] == unknown)
    assert identity["suggested_project_id"] == str(project.id)
    assert identity["suggested_project_name"] == project.name

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
    # the answer says how many retained events went to the decoder (decision D394)
    assert created.json()["queued"] == 1
    # linking queues the retained event for the decoder's walk (decision D121)
    await bus.consume(Topic.IDENTITY_REPROCESS_REQUESTED, group, "c1", walk, once=True)
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
    """A final decode failure is a failed source event and no dead letter (decision D349); a
    dead letter the bus did set aside is resolved one by one, or all of a topic at once, or
    all sent again."""
    from shared.bus import Message

    admin, _project, _, source, _device, external_id = await _setup(client, db)
    group, handler, _walk = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    accepted = await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        json={"device_id": external_id, "time": "garbage", "lat": 1, "lon": 2},
        headers=auth,
    )
    event_id = accepted.json()["source_event_ids"][0]
    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    topic = Topic.SOURCE_EVENT_RECEIVED
    listed = (
        await client.get(
            "/api/v1/attention/dead-letters", params={"topic": topic}, headers=admin.headers
        )
    ).json()
    assert [d for d in listed if d.get("trace_id") == accepted.json()["trace_ids"][0]] == []
    failed = (
        await client.get(
            "/api/v1/attention/source-events", params={"status": "failed"}, headers=admin.headers
        )
    ).json()
    assert any(e["id"] == event_id for e in failed)

    # what the bus does set aside (retries exhausted, a crash): one by one, or all at once
    trace = str(uuid.uuid4())
    for n in range(3):
        await bus.publish_dead(
            topic,
            Message(topic, {"source_event_id": event_id, "n": n}, trace_id=trace),
            "boom",
            "INTERNAL_ERROR",
        )
    mine = [
        d
        for d in (
            await client.get(
                "/api/v1/attention/dead-letters", params={"topic": topic}, headers=admin.headers
            )
        ).json()
        if d.get("trace_id") == trace
    ]
    assert len(mine) == 3 and mine[0]["error_code"] == "INTERNAL_ERROR"
    assert (
        await client.post(
            f"/api/v1/attention/dead-letters/{topic}/{mine[0]['id']}/resolve",
            headers=admin.headers,
        )
    ).status_code == 204
    retried = await client.post(
        f"/api/v1/attention/dead-letters/{topic}/retry-all", headers=admin.headers
    )
    assert retried.status_code == 200 and retried.json()["queued"] >= 2
    assert await bus.dead_count(topic) == 0
    await bus.publish_dead(
        topic, Message(topic, {"n": 9}, trace_id=trace), "boom", "INTERNAL_ERROR"
    )
    resolved = await client.post(
        f"/api/v1/attention/dead-letters/{topic}/resolve-all", headers=admin.headers
    )
    assert resolved.status_code == 200 and resolved.json()["resolved"] == 1
    assert await bus.dead_count(topic) == 0
    assert (
        await client.post(
            "/api/v1/attention/dead-letters/no.such/resolve-all", headers=admin.headers
        )
    ).status_code == 404
    # the retried messages are back on the stream: take them off the test group
    await bus.consume(topic, group, "c1", handler, once=True)
    await bus.consume(topic, group, "c1", handler, once=True)
    await bus.redis.xgroup_destroy(topic, group)


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


async def test_first_message_is_the_first_sighting_of_a_listed_identity(client, db, bus):
    """Decision D393: a platform's device list makes identities without a first sighting; the
    first message stamps it, and create-device without a start date starts there."""
    from sqlalchemy import select

    from shared.models import DeviceProjectAssignment, ExternalIdentity

    admin, project, device_type, source, _device, _external = await _setup(client, db)
    listed = uuid.uuid4().hex[:16].upper()
    identity = ExternalIdentity(
        data_source_id=uuid.UUID(source["id"]), external_id=listed, identity_type="dev_eui"
    )
    db.add(identity)
    await db.commit()
    assert identity.first_seen_at is None
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    body = {"device_id": listed, "time": "2026-03-21T10:00:00+00:00", "lat": -24.8, "lon": 31.4}
    accepted = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    assert accepted.status_code == 202
    arrived = await _ingested_at(db, accepted.json()["source_event_ids"][0])
    await db.refresh(identity)
    assert identity.first_seen_at == arrived

    created = await client.post(
        f"/api/v1/attention/identities/{identity.id}/create-device",
        json={
            "name": unique_name("listed"),
            "device_type_id": device_type["id"],
            "project_id": str(project.id),
            "reprocess": False,
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["queued"] == 0  # reprocess was not asked for
    validity = await db.scalar(
        select(DeviceProjectAssignment.validity).where(
            DeviceProjectAssignment.device_id == uuid.UUID(created.json()["id"])
        )
    )
    assert validity is not None and validity.lower == arrived
    assert await db.scalar(
        select(ExternalIdentity.device_id).where(ExternalIdentity.id == identity.id)
    ) == uuid.UUID(created.json()["id"])


async def test_walk_moves_a_first_sighting_start_back_to_the_earliest_record(client, db, bus):
    """Decision D395: a record's device time is earlier than its arrival, so a device made to
    start at its first sighting left the records of its retained uplinks without a project.
    The walk moves the new assignment back to the earliest record it decoded and queues the
    rewrite; a start given by hand stays where it was put."""
    from sqlalchemy import select

    from shared.domain.attribution import run_attribution_job
    from shared.models import AttributionJob, DeviceProjectAssignment, ExternalIdentity, Position

    admin, project, device_type, source, _device, _external = await _setup(client, db)
    group, _handler, walk = await _decode_pending(db, bus)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}

    async def retained(external_id: str) -> uuid.UUID:
        for minute in (0, 5):
            body = {
                "device_id": external_id,
                "time": f"2026-03-21T10:0{minute}:00+00:00",
                "lat": -24.8,
                "lon": 31.4,
            }
            accepted = await client.post(
                f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth
            )
            assert accepted.status_code == 202
        identity_id = await db.scalar(
            select(ExternalIdentity.id).where(ExternalIdentity.external_id == external_id)
        )
        assert identity_id is not None
        return identity_id

    async def create(identity_id: uuid.UUID, **extra: str) -> uuid.UUID:
        created = await client.post(
            f"/api/v1/attention/identities/{identity_id}/create-device",
            json={
                "name": unique_name("walked"),
                "device_type_id": device_type["id"],
                "project_id": str(project.id),
                **extra,
            },
            headers=admin.headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["queued"] == 2
        await bus.consume(Topic.IDENTITY_REPROCESS_REQUESTED, group, "c1", walk, once=True)
        return uuid.UUID(created.json()["id"])

    async def start_of(device_id: uuid.UUID) -> datetime:
        validity = await db.scalar(
            select(DeviceProjectAssignment.validity).where(
                DeviceProjectAssignment.device_id == device_id
            )
        )
        assert validity is not None
        return validity.lower

    # no start given: the assignment follows the records, and the rewrite gives them the project
    device_id = await create(await retained(uuid.uuid4().hex[:16].upper()))
    assert await start_of(device_id) == datetime.fromisoformat("2026-03-21T10:00:00+00:00")
    job = await db.scalar(select(AttributionJob).where(AttributionJob.device_id == device_id))
    assert job is not None and job.reason == "identity.history"
    await run_attribution_job({"job_id": str(job.id)})
    projects = (
        await db.scalars(select(Position.project_id).where(Position.device_id == device_id))
    ).all()
    assert projects == [project.id, project.id]

    # a start given by hand stays, and the records before it keep no project
    chosen = "2026-06-01T00:00:00+00:00"
    device_id = await create(await retained(uuid.uuid4().hex[:16].upper()), valid_from=chosen)
    assert await start_of(device_id) == datetime.fromisoformat(chosen)
    projects = (
        await db.scalars(select(Position.project_id).where(Position.device_id == device_id))
    ).all()
    assert projects == [None, None]
    await bus.redis.xgroup_destroy(Topic.IDENTITY_REPROCESS_REQUESTED, group)


async def test_first_messages_at_the_same_moment_all_arrive(client, db):
    """Decision D396: several first messages of one identity at once, for a new identity and
    for one a platform's device list made, are all accepted, counted, and the first sighting
    is the arrival of the earliest."""
    import asyncio

    from sqlalchemy import func, select

    from shared.models import ExternalIdentity, SourceEvent

    _admin, _project, _type, source, _device, _external = await _setup(client, db)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    listed = uuid.uuid4().hex[:16].upper()
    db.add(
        ExternalIdentity(
            data_source_id=uuid.UUID(source["id"]), external_id=listed, identity_type="dev_eui"
        )
    )
    await db.commit()
    for external_id in (uuid.uuid4().hex[:16].upper(), listed):
        answers = await asyncio.gather(
            *(
                client.post(
                    f"/api/v1/ingest/http/{source['id']}",
                    json={"device_id": external_id, "lat": -24.8, "lon": 31.4 + n / 1000},
                    headers=auth,
                )
                for n in range(6)
            )
        )
        assert [a.status_code for a in answers] == [202] * 6
        first_seen, count = (
            await db.execute(
                select(ExternalIdentity.first_seen_at, ExternalIdentity.event_count).where(
                    ExternalIdentity.external_id == external_id
                )
            )
        ).one()
        earliest = await db.scalar(
            select(func.min(SourceEvent.ingested_at)).where(SourceEvent.external_id == external_id)
        )
        assert count == 6
        assert first_seen == earliest


async def test_create_device_refuses_a_bad_start_and_a_second_create(client, db):
    """Decision D397: a start without a timezone or in the future is a 422, and creates for
    one identity at the same moment make one device."""
    import asyncio

    from sqlalchemy import func, select

    from shared.models import Device

    admin, project, device_type, source, _device, _external = await _setup(client, db)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    unknown = uuid.uuid4().hex[:16].upper()
    await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        json={"device_id": unknown, "lat": -24.8, "lon": 31.4},
        headers=auth,
    )
    identities = (await client.get("/api/v1/attention/identities", headers=admin.headers)).json()
    identity = next(i for i in identities["items"] if i["external_id"] == unknown)
    url = f"/api/v1/attention/identities/{identity['id']}/create-device"
    body = {"device_type_id": device_type["id"], "project_id": str(project.id)}
    prefix = unique_name("raced")
    for start in ("2026-01-01T00:00:00", "2090-01-01T00:00:00+00:00"):
        refused = await client.post(
            url, json={**body, "name": prefix, "valid_from": start}, headers=admin.headers
        )
        assert refused.status_code == 422, refused.text
    bulk = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [identity["id"]],
            "device_type_id": device_type["id"],
            "project_id": str(project.id),
            "valid_from": "2090-01-01T00:00:00+00:00",
        },
        headers=admin.headers,
    )
    assert bulk.status_code == 422, bulk.text
    answers = await asyncio.gather(
        *(
            client.post(url, json={**body, "name": f"{prefix}-{n}"}, headers=admin.headers)
            for n in range(4)
        )
    )
    assert sorted(a.status_code for a in answers) == [201, 409, 409, 409]
    made = await db.scalar(
        select(func.count()).select_from(Device).where(Device.name.like(f"{prefix}-%"))
    )
    assert made == 1
