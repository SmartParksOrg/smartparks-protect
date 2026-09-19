"""Fence lines and traps through the whole path (phase 32, decisions D263 to D266): a fence
line drawn, two monitors on it, their FenceEdge readings arriving, the line's sections and
events; a TrapEdge's switch shutting a trap and opening it again."""

import struct
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.bus import RedisStreamsBus
from shared.connectivity.base import InboundMessage
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource, Event, ExternalIdentity, Measurement
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


#: A fence running east for about a kilometre at 52.5 north.
LINE = {"type": "LineString", "coordinates": [[4.6000, 52.5000], [4.6147, 52.5000]]}


def fence_frame(voltage_v: int, pulses: int = 5, result: int = 0) -> str:
    """A port 12 fence measurement (research 3.10): id, length, result, pulses, voltage, energy."""
    return (bytes([0x92, 0x06]) + struct.pack("<BBHH", result, pulses, voltage_v, 40)).hex()


def switch_frame(active: bool, duration_s: int = 600) -> str:
    """A port 19 switch change (research 3.15)."""
    return (bytes([0x98, 0x05]) + struct.pack("<BI", int(active), duration_s * 1000)).hex()


async def _device(client, db, project, admin, *, entity_type_key: str, name: str, place):
    """An OpenCollar device on a new entity of the given catalogue type, with a fixed place."""
    h = admin.headers
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("oc").replace("-", "_"),
                "label": "OpenCollar Edge",
                "driver_key": "opencollar",
            },
            headers=h,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("SP"),
                "status": "active",
            },
            headers=h,
        )
    ).json()
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    assert assigned.status_code in (200, 201), assigned.text
    catalogue = (await client.get("/api/v1/entity-types?limit=400", headers=h)).json()
    entity_type = next(t for t in catalogue["items"] if t["key"] == entity_type_key)
    made = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": entity_type["id"], "name": name},
        },
        headers=h,
    )
    assert made.status_code == 201, made.text
    placed = await client.put(
        f"/api/v1/devices/{device['id']}/static-position",
        json={"latitude": place[1], "longitude": place[0]},
        headers=h,
    )
    assert placed.status_code == 200, placed.text
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(device["id"])
        )
    )
    await db.commit()
    return device, made.json()["entity_id"], source, identity


async def _deliver(db, bus, source, identity, port: int, frame_hex: str):
    stored = await store_inbound(
        db,
        source,
        InboundMessage(
            external_id=identity,
            payload={"fPort": port, "frame_hex": frame_hex},
            provider_metadata={"f_port": port, "frame_hex": frame_hex},
            acquisition_channel=AcquisitionChannel.LORAWAN,
            ingestion_method=IngestionMethod.WEBHOOK,
            event_type="uplink",
        ),
    )
    await commit_and_publish(db, bus, [stored])
    event = stored.source_event
    outcome = await process_source_event(db, event.id, event.ingested_at)
    await db.commit()
    return outcome


async def test_a_fence_line_reads_its_sections_from_its_monitors(client, db, bus):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}"

    line = await client.post(
        f"{base}/features",
        json={"feature_type": "fence", "name": unique_name("East fence"), "geometry": LINE},
        headers=h,
    )
    assert line.status_code == 201, line.text
    fence_id = line.json()["id"]
    assert line.json()["fence_level"] == "unknown", "a line with no monitor says so"

    # two monitors, at a third and two thirds of the way along
    _west, west_entity, source_w, id_w = await _device(
        client,
        db,
        project,
        admin,
        entity_type_key="fence_monitor",
        name=unique_name("West"),
        place=(4.6049, 52.4999),
    )
    _east, east_entity, source_e, id_e = await _device(
        client,
        db,
        project,
        admin,
        entity_type_key="fence_monitor",
        name=unique_name("East"),
        place=(4.6098, 52.5001),
    )
    for entity_id in (west_entity, east_entity):
        put = await client.put(
            f"{base}/entities/{entity_id}/fence", json={"feature_id": fence_id}, headers=h
        )
        assert put.status_code == 200, put.text
        assert put.json()["feature_id"] == fence_id

    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert status["level"] == "unknown" and len(status["sections"]) == 3
    assert [round(m["position_m"], -2) for m in status["monitors"]] == [300, 700]

    # both monitors read a healthy fence
    await _deliver(db, bus, source_w, id_w, 12, fence_frame(6800))
    await _deliver(db, bus, source_e, id_e, 12, fence_frame(6500))
    await db.rollback()
    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert status["level"] == "ok"
    assert [s["level"] for s in status["sections"]] == ["ok", "ok", "ok"]
    assert status["thresholds"] == {"ok_v": 4000, "down_v": 2000, "interval_s": 60}

    # the east monitor reads low: the two sections it touches turn, the west one stays
    await _deliver(db, bus, source_e, id_e, 12, fence_frame(3100))
    await db.rollback()
    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert [s["level"] for s in status["sections"]] == ["ok", "low", "low"]
    assert status["level"] == "low"
    listed = (await client.get(f"{base}/features?feature_type=fence", headers=h)).json()
    assert listed["items"][0]["fence_level"] == "low"

    events = (
        await db.scalars(
            select(Event)
            .where(Event.project_id == project.id, Event.event_type == "FENCE_STATUS")
            .order_by(Event.time)
        )
    ).all()
    assert [e.severity for e in events] == ["info", "info", "warning"], [e.title for e in events]
    assert events[-1].context["level"] == "low" and events[-1].geom is not None
    assert events[-1].title.endswith("reads low"), events[-1].title
    assert "reads live near" in events[0].title, events[0].title

    # a failed measurement at the east end makes those sections unknown
    await _deliver(db, bus, source_e, id_e, 12, fence_frame(0, pulses=0, result=2))
    await db.rollback()
    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert [s["level"] for s in status["sections"]] == ["ok", "unknown", "unknown"]

    # taking a monitor off the line leaves the other to colour the whole line
    off = await client.put(
        f"{base}/entities/{east_entity}/fence", json={"feature_id": None}, headers=h
    )
    assert off.status_code == 200 and off.json()["feature_id"] is None
    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert [s["level"] for s in status["sections"]] == ["ok"]

    # the monitor's own read names the line and its reading
    mine = (await client.get(f"{base}/entities/{west_entity}/fence", headers=h)).json()
    assert mine["feature_id"] == fence_id and mine["monitor"]["voltage_v"] == 6800

    # a route is not a fence line
    route = await client.post(
        f"{base}/features",
        json={"feature_type": "route", "name": unique_name("Patrol"), "geometry": LINE},
        headers=h,
    )
    refused = await client.put(
        f"{base}/entities/{west_entity}/fence", json={"feature_id": route.json()["id"]}, headers=h
    )
    assert refused.status_code == 422


async def test_a_stale_monitor_reads_unknown_without_a_new_measurement(client, db, bus):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}"
    line = await client.post(
        f"{base}/features",
        json={
            "feature_type": "fence",
            "name": unique_name("Old fence"),
            "geometry": LINE,
            "attributes": {"fence": {"interval_s": 1}},
        },
        headers=h,
    )
    fence_id = line.json()["id"]
    _, entity_id, source, identity = await _device(
        client,
        db,
        project,
        admin,
        entity_type_key="fence_monitor",
        name=unique_name("Lone"),
        place=(4.6049, 52.4999),
    )
    await client.put(f"{base}/entities/{entity_id}/fence", json={"feature_id": fence_id}, headers=h)
    await _deliver(db, bus, source, identity, 12, fence_frame(7000))
    await db.rollback()
    # the reading is a second old at most; two seconds later the line no longer trusts it
    import asyncio

    await asyncio.sleep(2.2)
    status = (await client.get(f"{base}/features/{fence_id}/fence", headers=h)).json()
    assert status["level"] == "unknown"
    assert status["monitors"][0]["voltage_v"] == 7000


async def test_a_trap_shuts_and_opens(client, db, bus):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    device, entity_id, source, identity = await _device(
        client, db, project, admin, entity_type_key="trap", name="Trap 3", place=(4.61, 52.51)
    )
    wiring = (await client.get(f"/api/v1/devices/{device['id']}/trap", headers=h)).json()
    assert wiring == {"closed_when_active": True, "set_by_hand": False}

    await _deliver(db, bus, source, identity, 19, switch_frame(True))
    await db.rollback()
    events = (
        await db.scalars(select(Event).where(Event.project_id == project.id).order_by(Event.time))
    ).all()
    kinds = [e.event_type for e in events]
    assert "TRAP_CLOSED" in kinds and "switch_activated" in kinds, kinds
    closed = next(e for e in events if e.event_type == "TRAP_CLOSED")
    assert closed.title == "Trap Trap 3 closed" and closed.entity_id == uuid.UUID(entity_id)
    readings = (
        await db.scalars(
            select(Measurement.value_bool).where(
                Measurement.device_id == uuid.UUID(device["id"]),
                Measurement.metric_key == "trap_triggered",
            )
        )
    ).all()
    assert readings == [True]

    # the same state again is no news; opening is
    await _deliver(
        db, bus, source, identity, 20, (bytes([0x99, 0x05]) + struct.pack("<BI", 1, 1)).hex()
    )
    await _deliver(db, bus, source, identity, 19, switch_frame(False))
    await db.rollback()
    kinds = [
        e.event_type
        for e in (
            await db.scalars(
                select(Event).where(Event.project_id == project.id).order_by(Event.time)
            )
        ).all()
    ]
    assert kinds.count("TRAP_CLOSED") == 1 and kinds.count("TRAP_OPENED") == 1

    # the wiring can be turned round, and then an inactive switch is a shut trap
    turned = await client.put(
        f"/api/v1/devices/{device['id']}/trap", json={"closed_when_active": False}, headers=h
    )
    assert turned.status_code == 200 and turned.json()["set_by_hand"] is True
    await _deliver(db, bus, source, identity, 19, switch_frame(False, duration_s=5))
    await db.rollback()
    newest = await db.scalar(
        select(Measurement.value_bool)
        .where(
            Measurement.device_id == uuid.UUID(device["id"]),
            Measurement.metric_key == "trap_triggered",
        )
        .order_by(Measurement.time.desc())
        .limit(1)
    )
    assert newest is True
