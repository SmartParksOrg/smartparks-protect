"""Bulk onboarding from Needs attention (decision D96): a selection of unknown identities
becomes devices, optionally with an entity each, or is ignored, in one call."""

import uuid

import pytest
from sqlalchemy import select

from shared.enums import ProcessingStatus
from shared.models import GatewayReception, SourceEvent
from shared.timeutil import utc_now
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _unknown_identities(client, headers, count: int):
    """A generic HTTP source and `count` uplinks from DevEUIs nobody knows."""
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("Shared network"), "adapter_key": "generic_http"},
            headers=headers,
        )
    ).json()
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    euis = [unique_name("EUI").replace("-", "")[:16].upper() for _ in range(count)]
    for eui in euis:
        response = await client.post(
            f"/api/v1/ingest/http/{source['id']}",
            json={"device_id": eui, "time": "2026-09-06T10:00:00+00:00", "lat": 52.0, "lon": 5.1},
            headers=auth,
        )
        assert response.status_code == 202, response.text
    listed = (await client.get("/api/v1/attention/identities?limit=500", headers=headers)).json()
    identities = [i for i in listed["items"] if i["external_id"] in euis]
    assert len(identities) == count
    return source, identities


async def test_linking_gives_the_receptions_the_device(client, db):
    """A reception stored while the identity was unknown gets the device when the identity is
    linked, so the gateway layer sees the uplink (decision D121)."""
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
    source, (identity,) = await _unknown_identities(client, h, 1)
    event = await db.scalar(
        select(SourceEvent).where(SourceEvent.external_identity_id == uuid.UUID(identity["id"]))
    )
    assert event is not None and event.device_id is None
    db.add(
        GatewayReception(
            time=utc_now(),
            data_source_id=uuid.UUID(source["id"]),
            device_id=None,
            source_event_id=event.id,
            source_event_ingested_at=event.ingested_at,
            gateway_id="gw-test-1",
            rssi=-100.0,
        )
    )
    await db.commit()

    result = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={"identity_ids": [identity["id"]], "device_type_id": device_type["id"]},
        headers=h,
    )
    assert result.status_code == 201, result.text
    assert result.json()["queued"] == 1
    db.expire_all()
    reception = await db.scalar(
        select(GatewayReception).where(GatewayReception.source_event_id == event.id)
    )
    assert reception is not None
    assert str(reception.device_id) == result.json()["device_ids"][0]


async def test_bulk_create_devices_with_entities_names_and_skips(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
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
    source, identities = await _unknown_identities(client, h, 3)
    first, second, third = identities
    # the platform's name on one identity, as the KPN adapter stores it
    patched = await client.patch(
        f"/api/v1/data-sources/{source['id']}/identities/{first['id']}",
        json={"attributes": {"name": "SP051303"}},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    # a device that already carries the second identity's external id as its name
    taken = await client.post(
        "/api/v1/devices",
        json={
            "device_type_id": device_type["id"],
            "name": second["external_id"],
            "status": "active",
        },
        headers=h,
    )
    assert taken.status_code == 201, taken.text

    result = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [first["id"], second["id"], third["id"], first["id"]],
            "device_type_id": device_type["id"],
            "project_id": project.id.hex,
            "entity_type_id": entity_type["id"],
        },
        headers=h,
    )
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["created"] == 3 and body["entities"] == 3 and body["skipped"] == []
    assert body["queued"] == 3
    # the retained events wait for the decoder with their device (decision D121)
    events = (
        await db.scalars(
            select(SourceEvent).where(
                SourceEvent.external_identity_id.in_([uuid.UUID(i["id"]) for i in identities])
            )
        )
    ).all()
    assert len(events) == 3
    assert {e.processing_status for e in events} == {ProcessingStatus.RECEIVED}
    assert all(e.device_id is not None for e in events)
    summary = (await client.get("/api/v1/attention/summary", headers=h)).json()
    assert summary["queued_source_events"] >= 3
    devices = {
        (await client.get(f"/api/v1/devices/{device_id}", headers=h)).json()["name"]: device_id
        for device_id in body["device_ids"]
    }
    # the platform name, the external id, and the external id twice when a device took it
    assert "SP051303" in devices and third["external_id"] in devices
    assert f"{second['external_id']} {second['external_id']}" in devices
    detail = (await client.get(f"/api/v1/devices/{devices['SP051303']}", headers=h)).json()
    assert [i["external_id"] for i in detail["external_identities"]] == [first["external_id"]]
    assert detail["project_assignments"][0]["project_id"] == str(project.id)
    assert (
        detail["entity_assignments"][0]["valid_from"]
        == detail["project_assignments"][0]["valid_from"]
    )
    entities = (
        await client.get(f"/api/v1/projects/{project.id}/entities?limit=50", headers=h)
    ).json()
    assert {e["name"] for e in entities["items"]} >= {"SP051303", third["external_id"]}

    # nothing left of them in Needs attention; a second run reports why
    listed = (await client.get("/api/v1/attention/identities?limit=500", headers=h)).json()
    assert not {i["id"] for i in listed["items"]} & {first["id"], second["id"], third["id"]}
    again = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={"identity_ids": [first["id"]], "device_type_id": device_type["id"]},
        headers=h,
    )
    assert again.status_code == 201
    assert again.json()["created"] == 0
    assert again.json()["skipped"][0]["reason"] == "already linked to a device"

    # an entity needs a project
    refused = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [first["id"]],
            "device_type_id": device_type["id"],
            "entity_type_id": entity_type["id"],
        },
        headers=h,
    )
    assert refused.status_code == 422


async def test_bulk_ignore(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    _source, identities = await _unknown_identities(client, h, 2)
    ids = [i["id"] for i in identities]
    result = await client.post(
        "/api/v1/attention/identities/bulk-ignore", json={"identity_ids": ids}, headers=h
    )
    assert result.status_code == 200 and result.json() == {"ignored": 2, "skipped": []}
    listed = (await client.get("/api/v1/attention/identities?limit=500", headers=h)).json()
    assert not {i["id"] for i in listed["items"]} & set(ids)
    again = await client.post(
        "/api/v1/attention/identities/bulk-ignore", json={"identity_ids": ids[:1]}, headers=h
    )
    assert again.json()["ignored"] == 0 and again.json()["skipped"][0]["reason"] == "ignored"
    audit = (await client.get("/api/v1/admin/audit?limit=20", headers=h)).json()
    assert any(
        e["action"] == "attention.identity_ignored" and (e.get("details") or {}).get("bulk")
        for e in audit
    )
