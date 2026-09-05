"""The administrator's window while connecting a platform: everything a data source received,
linked to a device or not."""

import uuid

import pytest

from shared.enums import Role
from tests.api.conftest import project_actor
from tests.api.test_ingest_and_attention import _setup

pytestmark = pytest.mark.asyncio


async def test_source_traffic_shows_unlinked_events(client, db):
    admin, project, _type, source, device, external_id = await _setup(client, db)
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    unknown = uuid.uuid4().hex[:16].upper()
    for identity in (external_id, unknown):
        body = {
            "device_id": identity,
            "time": "2026-03-21T10:00:00+00:00",
            "lat": -24.8,
            "lon": 31.4,
        }
        accepted = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
        assert accepted.status_code == 202, accepted.text

    rows = (
        await client.get(f"/api/v1/data-sources/{source['id']}/traffic", headers=admin.headers)
    ).json()
    by_identity = {r["external_id"]: r for r in rows}
    assert set(by_identity) == {external_id, unknown}
    assert by_identity[external_id]["device_name"] == device["name"]
    assert by_identity[unknown]["device_name"] is None and by_identity[unknown]["device_id"] is None
    assert by_identity[unknown]["data_source_name"] == source["name"]

    filtered = (
        await client.get(
            f"/api/v1/data-sources/{source['id']}/traffic",
            params={"external_id": unknown[:6].lower(), "include_payload": "true"},
            headers=admin.headers,
        )
    ).json()
    assert [r["external_id"] for r in filtered] == [unknown]
    assert filtered[0]["payload"]["lat"] == -24.8

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.get(
        f"/api/v1/data-sources/{source['id']}/traffic", headers=viewer.headers
    )
    assert refused.status_code == 403
    missing = await client.get(
        f"/api/v1/data-sources/{uuid.uuid4()}/traffic", headers=admin.headers
    )
    assert missing.status_code == 404
