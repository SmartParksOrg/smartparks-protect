"""A source event read carries what it decoded into, so the traffic view can say what a
delivery meant (Tim's observation on the Bluetooth rows, 2026-09-06)."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_source_event_lists_its_decoded_records(client, db, bus):  # noqa: F811
    admin, _project, _entity, source, _device, external_id = await _setup(client, db)
    h = admin.headers
    when = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=3)
    stored = await _feed(db, bus, source["id"], external_id, when, -24.9, 31.5)
    event = stored.source_event
    read = await client.get(
        f"/api/v1/source-events/{event.id}",
        params={"ingested_at": event.ingested_at.isoformat()},
        headers=h,
    )
    assert read.status_code == 200, read.text
    records = read.json()["records"]
    assert [(p["latitude"], p["longitude"]) for p in records["positions"]] == [(-24.9, 31.5)]
    assert [(m["metric_key"], m["value"]) for m in records["measurements"]] == [
        ("battery_voltage", 3.8)
    ]
    assert records["states"] == [] and records["events"] == []
