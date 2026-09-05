"""Server admin, Traffic: inbound events across sources, outbound deliveries across projects,
commands across devices, and the hourly summary."""

import uuid
from datetime import UTC, datetime

import pytest

from shared.enums import Role
from shared.models import Command, Integration, IntegrationDelivery
from tests.api.conftest import project_actor
from tests.api.test_ingest_and_attention import _setup

pytestmark = pytest.mark.asyncio


async def test_traffic_across_the_server(client, db):
    admin, project, _type, source, device, external_id = await _setup(client, db)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    body = {
        "device_id": external_id,
        "time": "2026-03-21T10:00:00+00:00",
        "lat": -24.8,
        "lon": 31.4,
    }
    assert (
        await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    ).status_code == 202

    integration = Integration(
        project_id=project.id,
        name="Partner",
        connector_key="webhook",
        config={"url": "https://partner.example/hook"},
        object_types=["position"],
    )
    db.add(integration)
    await db.flush()
    db.add(
        IntegrationDelivery(
            integration_id=integration.id,
            project_id=project.id,
            object_type="position",
            object_id="1",
            object_time=datetime(2026, 3, 21, 10, 0, tzinfo=UTC),
            status="failed",
            attempts=3,
            error_message="partner answered 503",
        )
    )
    db.add(
        Command(
            device_id=uuid.UUID(device["id"]),
            project_id=project.id,
            action_key="REQUEST_STATUS",
            driver_key="generic_json",
            parameters={},
            status="queued",
            actor={"kind": "user"},
        )
    )
    await db.commit()

    inbound = (
        await client.get(
            "/api/v1/admin/traffic/inbound",
            params={"data_source_id": source["id"]},
            headers=admin.headers,
        )
    ).json()
    assert [r["external_id"] for r in inbound] == [external_id]
    assert (
        inbound[0]["data_source_name"] == source["name"]
        and inbound[0]["device_name"] == device["name"]
    )

    outbound = (
        await client.get(
            "/api/v1/admin/traffic/outbound", params={"status": "failed"}, headers=admin.headers
        )
    ).json()
    mine = [d for d in outbound["items"] if d["integration_id"] == str(integration.id)]
    assert len(mine) == 1 and mine[0]["integration_name"] == "Partner"
    assert mine[0]["project_name"] == project.name and mine[0]["connector_key"] == "webhook"
    detail = (
        await client.get(f"/api/v1/admin/traffic/outbound/{mine[0]['id']}", headers=admin.headers)
    ).json()
    assert detail["error_message"] == "partner answered 503" and detail["response"] == {}

    commands = (
        await client.get(
            "/api/v1/admin/traffic/commands",
            params={"project_id": str(project.id)},
            headers=admin.headers,
        )
    ).json()
    assert [c["action_key"] for c in commands["items"]] == ["REQUEST_STATUS"]
    assert (
        commands["items"][0]["device_name"] == device["name"]
        and commands["items"][0]["project_name"] == project.name
    )

    summary = (await client.get("/api/v1/admin/traffic/summary", headers=admin.headers)).json()
    assert summary["inbound_events"] >= 1 and summary["outbound_by_status"].get("failed", 0) >= 1
    assert summary["commands_by_status"].get("queued", 0) >= 1

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    for path in ("summary", "inbound", "outbound", "commands"):
        assert (
            await client.get(f"/api/v1/admin/traffic/{path}", headers=viewer.headers)
        ).status_code == 403
