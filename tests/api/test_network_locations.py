"""Network locations through the API (decisions D162 to D164): kept apart from the device's
fixes in the positions list, the tracks and the records unless asked, drawn by the map's
network locations read, and the location source set per entity and per device."""

import json
from pathlib import Path

import pytest

from protect_decoder.pipeline import process_source_event
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "rock7"


async def test_network_positions_are_kept_apart_and_opted_into(client, db):
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
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
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
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("SP051890"),
                "status": "active",
            },
            headers=h,
        )
    ).json()
    assert device["location_source"] == "device" and device["location_fallback_hours"] == 24
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
    await client.patch(
        f"/api/v1/data-sources/{source['id']}/identities/{identity['id']}",
        json={"device_id": device["id"]},
        headers=h,
    )
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project.id.hex, "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=h,
        )
    ).json()
    assert entity["location_source"] == "device"
    await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": entity["id"],
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        headers=h,
    )

    # the setting: three values, the fallback in hours, refused outside the range
    changed = await client.patch(
        f"/api/v1/projects/{project.id}/entities/{entity['id']}",
        json={"location_source": "device_else_network", "location_fallback_hours": 6},
        headers=h,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["location_source"] == "device_else_network"
    assert changed.json()["location_fallback_hours"] == 6
    assert (
        await client.patch(
            f"/api/v1/projects/{project.id}/entities/{entity['id']}",
            json={"location_source": "satellite"},
            headers=h,
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/devices/{device['id']}",
            json={"location_fallback_hours": 0},
            headers=h,
        )
    ).status_code == 422

    # a live Rock7 delivery with a good estimate: a fix and a network position
    body = json.loads((FIXTURE / "delivery_live_sp051890.json").read_text())
    body.update({"iridium_session_status": "0", "iridium_cep": "5.0"})
    accepted = await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        params={"token": source["webhook_token"]},
        data=body,
    )
    assert accepted.status_code == 202, accepted.text
    await db.rollback()
    rows = (
        await client.get(
            f"/api/v1/data-sources/{source['id']}/traffic", params={"limit": 1}, headers=h
        )
    ).json()
    from datetime import datetime

    await process_source_event(
        db, accepted.json()["source_event_ids"][0], datetime.fromisoformat(rows[0]["ingested_at"])
    )
    await db.commit()

    window = {"from": "2026-09-10T00:00:00+00:00", "to": "2026-09-11T00:00:00+00:00"}
    positions = f"/api/v1/projects/{project.id}/positions"
    default = (await client.get(positions, params=window, headers=h)).json()
    assert {p["record_type"] for p in default} == {"gnss"}
    network = (
        await client.get(positions, params={**window, "sources": "network"}, headers=h)
    ).json()
    assert len(network) == 1 and network[0]["record_type"] == "network"
    assert network[0]["accuracy_m"] == 5000.0
    both = (await client.get(positions, params={**window, "sources": "all"}, headers=h)).json()
    assert {p["record_type"] for p in both} == {"gnss", "network"}

    tracks = f"/api/v1/projects/{project.id}/tracks"
    own = (await client.get(tracks, params={**window, "device_id": device["id"]}, headers=h)).json()
    with_network = (
        await client.get(
            tracks, params={**window, "device_id": device["id"], "sources": "all"}, headers=h
        )
    ).json()
    assert with_network["total_points"] == own["total_points"] + 1

    records = f"/api/v1/projects/{project.id}/records/count"
    plain = (
        await client.get(records, params={**window, "device_id": device["id"]}, headers=h)
    ).json()
    more = (
        await client.get(
            records, params={**window, "device_id": device["id"], "sources": "all"}, headers=h
        )
    ).json()
    assert more["count"] == plain["count"] + 1

    # the map's network locations read draws it with its radius; the current position stays the fix
    drawn = (
        await client.get(
            f"/api/v1/projects/{project.id}/map/network-locations",
            params={"hours": 24 * 30},
            headers=h,
        )
    ).json()
    assert drawn["total"] == 1
    props = drawn["features"][0]["properties"]
    assert props["accuracy_m"] == 5000.0 and props["method"] == "iridium_estimate"
    assert props["device_name"] == device["name"] and props["entity_name"] == "Rhino 14"
    current = (await client.get(f"/api/v1/projects/{project.id}/map/current", headers=h)).json()
    feature = next(f for f in current["features"] if f["properties"]["entity_id"] == entity["id"])
    assert feature["properties"]["position_kind"] == "device"
