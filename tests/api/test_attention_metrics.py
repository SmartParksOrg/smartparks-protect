"""New metrics register themselves and wait in Needs attention for a label, unit and
category (decision D102)."""

import uuid

import pytest
import pytest_asyncio

from shared.bus import Topic
from tests.api.conftest import actor
from tests.api.test_ingest_and_attention import _decode_pending
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def test_new_metric_is_listed_with_its_reporters_and_defined_in_one_call(client, db, bus):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
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
    metric_key = unique_name("soil_moisture").replace("-", "_")[:40]
    group, handler = await _decode_pending(db, bus)
    accepted = await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        json={
            "device_id": external_id,
            "time": "2026-09-06T09:00:00+00:00",
            "measurements": {metric_key: 31.5},
        },
        headers={"Authorization": f"Bearer {source['webhook_token']}"},
    )
    assert accepted.status_code == 202, accepted.text
    await bus.consume(Topic.SOURCE_EVENT_RECEIVED, group, "c1", handler, once=True)
    await db.rollback()

    summary = (await client.get("/api/v1/attention/summary", headers=h)).json()
    assert summary["uncategorized_metrics"] >= 1
    listed = (await client.get("/api/v1/attention/metrics", headers=h)).json()
    mine = next(m for m in listed["items"] if m["key"] == metric_key)
    assert mine["devices"] == 1 and mine["sample"] == 31.5
    assert mine["last_time"].startswith("2026-09-06T09:00:00")
    assert "device_health" in listed["categories"] and "uncategorized" not in listed["categories"]

    defined = await client.patch(
        f"/api/v1/metrics/{metric_key}",
        json={"label": "Soil moisture", "unit": "%", "category": "environment"},
        headers=h,
    )
    assert defined.status_code == 200, defined.text
    listed = (await client.get("/api/v1/attention/metrics", headers=h)).json()
    assert all(m["key"] != metric_key for m in listed["items"])
