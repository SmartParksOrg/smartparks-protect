"""Bluetooth contacts written and resolved on the way in (phase 30, decisions D252 to D254):
a scan of a collar whose address is known names that collar, one whose address is not is kept
as an unknown neighbour, and an address two collars could be is never attributed to either.
"""

import struct
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.bus import RedisStreamsBus
from shared.connectivity.base import InboundMessage
from shared.enums import AcquisitionChannel, ContactResolution, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource, DeviceContact
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

SCAN_AT = datetime(2026, 9, 18, 11, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


def scan_frame(addresses: list[tuple[bytes, int]], at: datetime = SCAN_AT) -> str:
    """A port 11 single scan, built to the firmware's layout (research 3.9)."""
    body = struct.pack("<I", int(at.timestamp())) + bytes([len(addresses)])
    for octets, rssi in addresses:
        body += octets + bytes([rssi + 128])
    return (bytes([0xFA, len(body)]) + body).hex()


async def _collar(client, db, project, admin, *, ble_mac: str | None):
    """An OpenCollar device in the project, with its Bluetooth address known or not."""
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
    if ble_mac:
        saved = await client.put(
            f"/api/v1/devices/{device['id']}/ble-address", json={"ble_mac": ble_mac}, headers=h
        )
        assert saved.status_code == 200, saved.text
    return device


async def _scan(db, bus, source, external_id, frame_hex):
    stored = await store_inbound(
        db,
        source,
        InboundMessage(
            external_id=external_id,
            payload={"fPort": 11, "frame_hex": frame_hex},
            provider_metadata={"f_port": 11, "frame_hex": frame_hex},
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


async def test_a_scan_resolves_names_keeps_unknowns_and_refuses_to_guess(client, db, bus):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)

    # the collar doing the scanning, and three neighbours it could see
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    known = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    twin_a = await _collar(client, db, project, admin, ble_mac="aa:bb:cc:99:88:77")
    twin_b = await _collar(client, db, project, admin, ble_mac="11:22:33:99:88:77")

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id,
            external_id=identity,
            device_id=uuid.UUID(watcher["id"]),
        )
    )
    await db.commit()

    outcome = await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame(
            [
                (bytes([0x0C, 0x41, 0x0A]), -74),  # the known collar
                (bytes([0xE1, 0x02, 0x9F]), -88),  # nobody we know
                (bytes([0x77, 0x88, 0x99]), -60),  # both twins end with these octets
            ]
        ),
    )
    assert outcome.created["contacts"] == 3
    assert outcome.ambiguous_contacts == 1

    await db.rollback()
    rows = (
        (
            await db.execute(
                select(DeviceContact)
                .where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
                .order_by(DeviceContact.address)
            )
        )
        .scalars()
        .all()
    )
    by_address = {r.address: r for r in rows}

    named = by_address["0a:41:0c"]
    assert named.resolution == ContactResolution.RESOLVED
    assert named.contact_device_id == uuid.UUID(known["id"])
    assert named.rssi_dbm == -74 and named.sightings == 1
    assert named.time == SCAN_AT, "the scan's own time, not the delivery's"
    assert named.project_id == project.id, "attributed like every canonical row"

    # decision D253: kept, and named by its octets so a repeated stranger is visible
    stranger = by_address["9f:02:e1"]
    assert stranger.resolution == ContactResolution.UNKNOWN
    assert stranger.contact_device_id is None

    # decision D254: two devices could be this, so it belongs to neither, and both are named
    unsure = by_address["99:88:77"]
    assert unsure.resolution == ContactResolution.AMBIGUOUS
    assert unsure.contact_device_id is None
    assert set(unsure.candidates) == {twin_a["id"], twin_b["id"]}


async def test_the_same_scan_delivered_twice_is_one_contact_each(client, db, bus):
    """A scan reaching us over the air and again in a flash log is one set of sightings."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()
    frame = scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74), (bytes([0xE1, 0x02, 0x9F]), -88)])

    first = await _scan(db, bus, source, identity, frame)
    second = await _scan(db, bus, source, identity, frame)
    assert first.created["contacts"] == 2
    assert second.created["contacts"] == 0 and second.duplicates >= 2

    await db.rollback()
    count = len(
        (
            await db.execute(
                select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert count == 2


async def test_a_device_seeing_its_own_address_does_not_meet_itself(client, db, bus):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -40)]))
    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.UNKNOWN
    assert row.contact_device_id is None


async def test_a_device_not_in_a_project_resolves_nothing_rather_than_reaching_wider(
    client, db, bus
):
    """The fleet a contact is read against is the project's, so a device in none has no fleet."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
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
    loner = (
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
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(loner["id"])
        )
    )
    await db.commit()
    outcome = await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -55)]))
    assert outcome.created["contacts"] == 1
    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(loner["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.UNKNOWN
    assert row.project_id is None


async def test_an_address_arriving_later_repairs_the_sightings_that_waited(client, db, bus):
    """A collar is usually seen before anyone asks it its own address. Nothing revisits those
    rows on its own, so an analysis months later would read "never met" from rows that hold the
    answer; setting the address repairs its own past."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    seen = await _collar(client, db, project, admin, ble_mac=None)  # not known yet
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))

    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.UNKNOWN, "nobody knew whose address that was"

    saved = await client.put(
        f"/api/v1/devices/{seen['id']}/ble-address",
        json={"ble_mac": "d4:22:11:0a:41:0c"},
        headers=admin.headers,
    )
    assert saved.status_code == 200, saved.text

    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.RESOLVED
    assert row.contact_device_id == uuid.UUID(seen["id"])


async def test_a_second_device_with_the_same_octets_makes_the_old_reading_ambiguous(
    client, db, bus
):
    """What was a confident answer stops being one the moment a second device could be it."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    first = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))
    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.RESOLVED

    # a second collar whose address ends the same way
    second = await _collar(client, db, project, admin, ble_mac="99:88:77:0a:41:0c")
    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.resolution == ContactResolution.AMBIGUOUS
    assert row.contact_device_id is None
    assert set(row.candidates) == {first["id"], second["id"]}


async def test_the_read_groups_by_neighbour_and_says_whether_the_device_was_looking(
    client, db, bus
):
    """The card's read (phase 30, C4). No contacts means "they never met" only when the device
    was scanning, so the scan settings travel with the list."""
    from shared.domain.device_settings import record_setting

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    known = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()

    base = f"/api/v1/devices/{watcher['id']}/contacts"
    empty = (await client.get(base, headers=admin.headers)).json()
    assert empty["counterparts"] == []
    assert empty["scanning"]["known"] is False, "nothing known about whether it was looking"

    await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74), (bytes([0xE1, 0x02, 0x9F]), -88)]),
    )
    # a later scan sees the same neighbour again, weaker: the group keeps the best signal
    later = SCAN_AT + timedelta(minutes=10)
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -90)], later))

    # what the device's settings say about its scanning (decisions D228 to D231)
    for name, value in (("ble_scan_interval", 600), ("ble_scan_filter", 1)):
        await record_setting(
            db,
            device_id=uuid.UUID(watcher["id"]),
            key=name,
            value=value,
            source="frame",
            observed_at=SCAN_AT,
        )
    await db.commit()

    body = (await client.get(base, headers=admin.headers)).json()
    assert body["scanning"]["enabled"] is True and body["scanning"]["known"] is True
    assert body["scanning"]["filter_label"] == "Smart Parks devices"
    by_address = {c["address"]: c for c in body["counterparts"]}
    named = by_address["0a:41:0c"]
    assert named["device_name"] == known["name"] and named["resolution"] == "resolved"
    assert named["contacts"] == 2, "two scans saw it"
    assert named["best_rssi_dbm"] == -74, "the strongest of the two, not the latest"
    assert named["last_at"] > named["first_at"], "the group spans both scans"
    stranger = by_address["9f:02:e1"]
    assert stranger["resolution"] == "unknown" and stranger["device_name"] is None
    assert body["unknown"] == 1 and body["ambiguous"] == 0


async def test_an_ambiguous_neighbour_names_the_devices_it_could_be(client, db, bus):
    """Decision D254: the reader is given the candidates rather than a guess."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    a = await _collar(client, db, project, admin, ble_mac="aa:bb:cc:99:88:77")
    b = await _collar(client, db, project, admin, ble_mac="11:22:33:99:88:77")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(watcher["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x77, 0x88, 0x99]), -60)]))

    body = (
        await client.get(f"/api/v1/devices/{watcher['id']}/contacts", headers=admin.headers)
    ).json()
    unsure = body["counterparts"][0]
    assert unsure["resolution"] == "ambiguous" and unsure["device_name"] is None
    assert set(unsure["candidate_names"]) == {a["name"], b["name"]}
    assert body["ambiguous"] == 1
