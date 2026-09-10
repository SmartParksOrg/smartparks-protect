"""The satellite session behind an Iridium delivery through the API (decisions D158 to D160):
the session on the traffic row and the trace, a redelivery kept as a duplicate, a gap in the
session counter, the last session as a health line, and the network's estimates on the map."""

import json
from pathlib import Path

import pytest

from protect_decoder.pipeline import process_source_event
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "rock7"


def delivery(momsn: int, status: int, cep: float) -> dict:
    body = json.loads((FIXTURE / "delivery_live_sp051890.json").read_text())
    body.update(
        {
            "momsn": str(momsn),
            "iridium_session_status": str(status),
            "iridium_cep": str(cep),
            "iridium_latitude": "46.5448",
            "iridium_longitude": "15.0995",
        }
    )
    return body


async def test_sessions_are_read_deduplicated_counted_and_mapped(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("oc").replace("-", "_"),
                "label": "OpenCollar",
                "driver_key": "opencollar",
            },
            headers=h,
        )
    ).json()
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("Rock7"), "adapter_key": "rock7"},
            headers=h,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type["id"], "name": "SP051890", "status": "active"},
            headers=h,
        )
    ).json()
    identity = (
        await client.post(
            f"/api/v1/data-sources/{source['id']}/identities",
            json={
                "data_source_id": source["id"],
                "external_id": "300434065263440",
                "identity_type": "imei",
            },
            headers=h,
        )
    ).json()
    assert (
        await client.patch(
            f"/api/v1/data-sources/{source['id']}/identities/{identity['id']}",
            json={"device_id": device["id"]},
            headers=h,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/devices/{device['id']}/project-assignments",
            json={"project_id": project.id.hex, "valid_from": "2026-01-01T00:00:00+00:00"},
            headers=h,
        )
    ).status_code == 201
    url = f"/api/v1/ingest/http/{source['id']}"
    query = {"token": source["webhook_token"]}

    async def post(body: dict) -> dict:
        response = await client.post(url, params=query, data=body)
        assert response.status_code == 202, response.text
        return response.json()

    async def traffic() -> list[dict]:
        rows = await client.get(
            f"/api/v1/data-sources/{source['id']}/traffic", params={"limit": 10}, headers=h
        )
        assert rows.status_code == 200, rows.text
        return rows.json()

    # a completed session with a usable estimate
    first = await post(delivery(100, 0, 4.0))
    await db.rollback()
    await process_source_event(db, first["source_event_ids"][0], _ingested(await traffic()))
    await db.commit()
    row = (await traffic())[0]
    assert row["processing_status"] == "processed"
    assert row["satellite"]["status"] == "ok" and row["satellite"]["sequence"] == 100
    assert row["satellite"]["cep_km"] == 4.0 and row["satellite"]["missed_since_last"] is None
    trace = (await client.get(f"/api/v1/traces/{row['trace_id']}", headers=h)).json()
    session_step = next(s for s in trace["steps"] if s["operation"] == "satellite session")
    assert session_step["status"] == "success"

    # the same delivery again is the platform's retry: kept, marked, not processed twice
    second = await post(delivery(100, 0, 4.0))
    assert second["source_event_ids"][0] != first["source_event_ids"][0]
    rows = await traffic()
    assert rows[0]["processing_status"] == "duplicate"
    assert rows[0]["satellite"]["duplicate_of"] == first["source_event_ids"][0]
    trace = (await client.get(f"/api/v1/traces/{rows[0]['trace_id']}", headers=h)).json()
    session_step = next(s for s in trace["steps"] if s["operation"] == "satellite session")
    assert session_step["status"] == "skipped"

    # two sessions went missing before the next one, whose estimate the network disowns
    third = await post(delivery(103, 2, 64.0))
    await db.rollback()
    await process_source_event(db, third["source_event_ids"][0], _ingested(await traffic()))
    await db.commit()
    rows = await traffic()
    assert rows[0]["satellite"]["status"] == "location_unacceptable"
    assert rows[0]["satellite"]["missed_since_last"] == 2

    # the device's health carries the last session as a line, warning about the gap
    read = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    line = next(f for f in read["health"]["fields"] if f["key"] == "satellite_session")
    assert "session 103" in line["text"] and "2 missed" in line["text"]
    assert line["level"] == "warn"

    # the map shows the estimate the network stood by, not the disowned one
    sessions = await client.get(
        f"/api/v1/projects/{project.id}/map/satellite-sessions",
        params={"hours": 24},
        headers=h,
    )
    assert sessions.status_code == 200, sessions.text
    body = sessions.json()
    assert body["total"] == 1 and not body["capped"]
    props = body["features"][0]["properties"]
    assert props["device_name"] == "SP051890" and props["cep_km"] == 4.0
    assert props["sequence"] == 100
    outside = await client.get(
        f"/api/v1/projects/{project.id}/map/satellite-sessions",
        params={"hours": 24, "bbox": "0,0,1,1"},
        headers=h,
    )
    assert outside.json()["total"] == 0
    # a viewer of another project sees nothing of this one
    other = await create_project(db)
    forbidden = await client.get(
        f"/api/v1/projects/{other.id}/map/satellite-sessions", params={"hours": 24}, headers=h
    )
    assert forbidden.status_code == 200 and forbidden.json()["total"] == 0


def _ingested(rows: list[dict]):
    from datetime import datetime

    return datetime.fromisoformat(rows[0]["ingested_at"])
