"""Records (phase 20, decision D142): one row per device timestamp with the position and the
measurements of that moment, newest first, paged on a time and device cursor with a count; a
measurement-only moment is its own row; the selection filters by entity or device; 403 for a
stranger; the all scope for a server admin."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.enums import Role
from shared.models import Measurement
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_records_rows_pages_and_count(client, db, bus):  # noqa: F811
    admin, project, entity, source, device, external_id = await _setup(client, db)
    start = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    for i in range(3):
        await _feed(
            db, bus, source["id"], external_id, start + timedelta(minutes=i), -24.9, 31.5 + i / 100
        )
    # a status message: measurements without a position, at its own moment
    status_time = start + timedelta(minutes=5)
    db.add(
        Measurement(
            time=status_time,
            device_id=uuid.UUID(device["id"]),
            project_id=project.id,
            entity_id=uuid.UUID(entity["id"]),
            metric_key="temperature",
            canonical_key=f"{device['id']}|temperature|status",
            value_num=21.5,
        )
    )
    await db.commit()
    base = f"/api/v1/projects/{project.id}/records"
    window = {
        "from": (start - timedelta(hours=1)).isoformat(),
        "to": (start + timedelta(hours=1)).isoformat(),
    }

    count = await client.get(
        f"{base}/count", params={**window, "entity_id": entity["id"]}, headers=admin.headers
    )
    assert count.status_code == 200, count.text
    assert count.json()["count"] == 4

    page = await client.get(
        base, params={**window, "entity_id": entity["id"]}, headers=admin.headers
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["next_cursor"] is None
    rows = body["items"]
    assert [r["time"][:19] for r in rows] == [
        (start + timedelta(minutes=m)).isoformat()[:19] for m in (5, 2, 1, 0)
    ]
    status_row, newest_fix = rows[0], rows[1]
    assert status_row["position"] is None
    assert status_row["measurements"] == {"temperature": 21.5}
    assert status_row["device_name"] == device["name"] and status_row["entity_name"] == "Rhino 14"
    assert newest_fix["position"]["lon"] == pytest.approx(31.52)
    assert newest_fix["measurements"] == {"battery_voltage": 3.8}
    assert newest_fix["position"]["source_event_id"] == newest_fix["source_event_id"]

    # pages of two, newest first, the cursor carrying on
    first = (
        await client.get(
            base, params={**window, "entity_id": entity["id"], "limit": 2}, headers=admin.headers
        )
    ).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = (
        await client.get(
            base,
            params={
                **window,
                "entity_id": entity["id"],
                "limit": 2,
                "cursor": first["next_cursor"],
            },
            headers=admin.headers,
        )
    ).json()
    assert [r["time"][:19] for r in first["items"] + second["items"]] == [
        r["time"][:19] for r in rows
    ]
    assert second["next_cursor"] is None

    by_device = (
        await client.get(base, params={**window, "device_id": device["id"]}, headers=admin.headers)
    ).json()
    assert len(by_device["items"]) == 4
    nobody = (
        await client.get(
            base, params={**window, "entity_id": str(uuid.uuid4())}, headers=admin.headers
        )
    ).json()
    assert nobody["items"] == []
    assert (await client.get(base, params=window, headers=admin.headers)).status_code == 422
    assert (
        await client.get(
            base,
            params={**window, "entity_id": entity["id"], "cursor": "nonsense"},
            headers=admin.headers,
        )
    ).status_code == 422

    other = await create_project(db)
    stranger = await project_actor(client, db, other, Role.PROJECT_VIEWER)
    assert (
        await client.get(
            base, params={**window, "entity_id": entity["id"]}, headers=stranger.headers
        )
    ).status_code == 403

    superuser = await actor(client, db, superuser=True)
    everywhere = await client.get(
        "/api/v1/projects/all/records",
        params={**window, "entity_id": entity["id"]},
        headers=superuser.headers,
    )
    assert everywhere.status_code == 200 and len(everywhere.json()["items"]) == 4
