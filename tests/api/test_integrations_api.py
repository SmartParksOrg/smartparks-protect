"""Integrations through the API: connectors, CRUD with the role matrix, deliveries, retry,
test sends, backfill requests."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from shared.bus import RedisStreamsBus, Topic
from shared.enums import Role
from shared.integrations.deliveries import enqueue, event_ref
from shared.models import Event, Integration, IntegrationDelivery
from tests.api.conftest import actor, create_project, project_actor

pytestmark = pytest.mark.asyncio


async def test_integration_lifecycle(client, db, monkeypatch):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}/integrations"

    connectors = (await client.get(f"{base}/connectors", headers=h)).json()
    keys = {c["key"] for c in connectors}
    assert keys >= {"gundi", "webhook", "mqtt"}
    assert all("config_schema" in c and "supports" in c for c in connectors)

    created = await client.post(
        base,
        json={
            "name": "Ops hook",
            "connector_key": "webhook",
            "config": {"url": "https://example.org/hook"},
            "credentials": {"secret": "s"},
            "object_types": ["position", "event"],
            "event_types": ["geofence_exit"],
            "min_severity": "warning",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    integration = created.json()
    assert integration["has_credentials"] and integration["event_types"] == ["GEOFENCE_EXIT"]
    assert "credentials" not in integration
    bad = await client.post(base, json={"name": "x", "connector_key": "nope"}, headers=h)
    assert bad.status_code == 422
    unsupported = await client.post(
        base,
        json={"name": "y", "connector_key": "gundi", "object_types": ["measurement"]},
        headers=h,
    )
    assert unsupported.status_code == 422
    duplicate = await client.post(
        base, json={"name": "Ops hook", "connector_key": "webhook"}, headers=h
    )
    assert duplicate.status_code == 409

    listed = (await client.get(base, headers=h)).json()
    assert [i["name"] for i in listed["items"]] == ["Ops hook"]
    detail = (await client.get(f"{base}/{integration['id']}", headers=h)).json()
    assert detail["counts"]["queued"] == 0 and detail["counts_24h"]["sent"] == 0

    patched = await client.patch(
        f"{base}/{integration['id']}",
        json={"enabled": False, "object_types": ["event"], "credentials": {"secret": "t"}},
        headers=h,
    )
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert patched.json()["object_types"] == ["event"]

    # viewers read, admins write
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(base, headers=viewer.headers)).status_code == 200
    assert (
        await client.post(
            base, json={"name": "v", "connector_key": "webhook"}, headers=viewer.headers
        )
    ).status_code == 403
    project_admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    assert (
        await client.patch(
            f"{base}/{integration['id']}", json={"enabled": True}, headers=project_admin.headers
        )
    ).status_code == 200
    outsider = await actor(client, db)
    assert (await client.get(base, headers=outsider.headers)).status_code == 403

    # a test send goes to the target
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request)
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(**{"transport": httpx.MockTransport(handler), **kw}),
    )
    tested = await client.post(
        f"{base}/{integration['id']}/test",
        json={"latitude": -24.9, "longitude": 31.5},
        headers=h,
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] and posted[0].url.path == "/hook"
    assert "X-Protect-Signature" in posted[0].headers
    no_location = await client.post(f"{base}/{integration['id']}/test", json={}, headers=h)
    assert no_location.status_code == 200  # the webhook accepts a test without coordinates

    deleted = await client.delete(f"{base}/{integration['id']}", headers=h)
    assert deleted.status_code == 204
    assert (await client.get(f"{base}/{integration['id']}", headers=h)).status_code == 404


async def test_deliveries_retry_and_backfill(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}/integrations"
    integration = Integration(
        project_id=project.id,
        name="Hook",
        connector_key="webhook",
        config={"url": "https://example.org/x"},
        object_types=["event"],
        max_object_age_seconds=365 * 86_400,
    )
    event = Event(
        time=datetime.now(UTC) - timedelta(hours=1),
        project_id=project.id,
        event_type="BATTERY_LOW",
        severity="warning",
        title="Battery",
        context={},
    )
    db.add_all([integration, event])
    await db.commit()
    await enqueue(db, [integration], [event_ref(event)])
    await db.commit()
    delivery = await db.scalar(
        select(IntegrationDelivery).where(IntegrationDelivery.integration_id == integration.id)
    )
    assert delivery is not None
    listed = (await client.get(f"{base}/deliveries", headers=h)).json()
    assert len(listed["items"]) == 1 and listed["items"][0]["status"] == "queued"
    assert "request" not in listed["items"][0]
    filtered = (await client.get(f"{base}/deliveries", params={"status": "sent"}, headers=h)).json()
    assert filtered["items"] == []
    by_integration = (
        await client.get(
            f"{base}/deliveries", params={"integration_id": str(uuid.uuid4())}, headers=h
        )
    ).json()
    assert by_integration["items"] == []
    detail = (await client.get(f"{base}/deliveries/{delivery.id}", headers=h)).json()
    assert detail["response"] == {} and detail["object_type"] == "event"

    row = await db.get(IntegrationDelivery, delivery.id)
    row.status = "failed"
    row.error_message = "boom"
    await db.commit()
    retried = await client.post(f"{base}/deliveries/{delivery.id}/retry", headers=h)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert retried.json()["origin"] == "retry"
    row = await db.get(IntegrationDelivery, delivery.id)
    await db.refresh(row)
    row.status = "sent"
    await db.commit()
    assert (
        await client.post(f"{base}/deliveries/{delivery.id}/retry", headers=h)
    ).status_code == 409

    bus = RedisStreamsBus()
    try:
        before = await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED)
        requested = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "time_to": datetime.now(UTC).isoformat(),
            },
            headers=h,
        )
        assert requested.status_code == 200, requested.text
        assert requested.json()["backfill"]["status"] == "queued"
        assert await bus.redis.xlen(Topic.INTEGRATION_BACKFILL_REQUESTED) == before + 1
        again = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "time_to": datetime.now(UTC).isoformat(),
            },
            headers=h,
        )
        assert again.status_code == 409
        reversed_range = await client.post(
            f"{base}/{integration.id}/backfill",
            json={
                "time_from": datetime.now(UTC).isoformat(),
                "time_to": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
            },
            headers=h,
        )
        assert reversed_range.status_code == 422
    finally:
        await bus.close()
