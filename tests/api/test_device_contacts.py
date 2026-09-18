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
from sqlalchemy.dialects.postgresql import Range

from protect_decoder.pipeline import process_source_event
from shared.bus import RedisStreamsBus
from shared.connectivity.base import InboundMessage
from shared.enums import AcquisitionChannel, ContactResolution, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource, DeviceContact, DeviceCurrentState, Position
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

# relative to now, so the clock rule of D259 judges these as the live scans they stand for
SCAN_AT = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=20)


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


def _map_features(body) -> list:
    """The map answer wraps its collection differently per endpoint; this reads either shape."""
    features = body["features"]
    return features["features"] if isinstance(features, dict) else features


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


async def test_a_clock_far_behind_its_delivery_is_not_believed(client, db, bus):
    """Decision D259. Some OpenCollar firmware sets the clock wrongly, and a PWN reader times
    its scans 45 hours before they arrive. On a path that delivers as it happens that cannot be
    right, so the delivery decides and the device's own claim is kept beside it."""
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

    long_ago = datetime.now(UTC) - timedelta(hours=45)
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -87)], long_ago))

    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert row.time > long_ago + timedelta(hours=40), "recorded when it arrived"
    assert row.device_time is not None, "what the device claimed is kept, not thrown away"
    assert abs((row.device_time - long_ago).total_seconds()) < 2
    assert row.clock_offset_s is not None and row.clock_offset_s > 44 * 3600


async def test_a_clock_within_tolerance_is_believed(client, db, bus):
    """A scan a couple of minutes out is the ordinary drift of a device and is left alone."""
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

    recent = datetime.now(UTC) - timedelta(minutes=3)
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -87)], recent))
    await db.rollback()
    row = (
        await db.execute(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).scalar_one()
    assert abs((row.time - recent).total_seconds()) < 2, "the device's own time stands"
    assert row.device_time is None and row.clock_offset_s is None


async def test_a_tag_on_a_rabbit_is_a_device_heard_by_a_reader(client, db, bus):
    """The PWN shape (decision D257): a stationary reader, a tag that reports nothing of itself,
    and a rabbit. The tag needs no special case, because its address is a real one and the
    resolver already matches a device by the address a scanner would see."""
    from shared.models import Entity, EntityType

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    reader = await _collar(client, db, project, admin, ble_mac=None)

    tag_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("tag").replace("-", "_"),
                "label": "EdgeTag",
                "driver_key": "ble_tag",
            },
            headers=h,
        )
    ).json()
    tag = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": tag_type["id"], "name": "EdgeTag 15", "status": "active"},
            headers=h,
        )
    ).json()
    assigned = await client.post(
        f"/api/v1/devices/{tag['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    assert assigned.status_code in (200, 201), assigned.text
    # the address PWN programmed onto the tag: 00:00:0f, tag 15
    saved = await client.put(
        f"/api/v1/devices/{tag['id']}/ble-address",
        json={"ble_mac": "00:00:00:00:00:0f"},
        headers=h,
    )
    assert saved.status_code == 200, saved.text

    entity_type = EntityType(
        key=unique_name("et").replace("-", "_"),
        label="Rabbit",
        group_key="tracked",
        icon_key="wildlife.generic",
    )
    db.add(entity_type)
    await db.flush()
    rabbit = Entity(name="Rabbit 15", entity_type_id=entity_type.id, project_id=project.id)
    db.add(rabbit)
    await db.commit()
    tracked = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": tag["id"],
            "entity_id": str(rabbit.id),
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert tracked.status_code in (200, 201), tracked.text

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()

    # the frame shape PWN actually sends: one neighbour, weak signal
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0F, 0x00, 0x00]), -87)]))

    # the reader's side: it saw the tag, and the tag names the rabbit
    seen = (await client.get(f"/api/v1/devices/{reader['id']}/contacts", headers=h)).json()[
        "counterparts"
    ][0]
    assert seen["resolution"] == "resolved"
    assert seen["device_name"] == "EdgeTag 15" and seen["entity_name"] == "Rabbit 15"

    # the tag's side: it reports nothing of itself, so being heard is all there is
    mine = (await client.get(f"/api/v1/devices/{tag['id']}/contacts", headers=h)).json()
    assert mine["counterparts"] == [], "a tag scans for nothing"
    assert len(mine["heard_by"]) == 1
    assert mine["heard_by"][0]["device_name"] == reader["name"]
    assert mine["heard_by"][0]["best_rssi_dbm"] == -87

    # and being heard is the only sign the tag is alive
    await db.rollback()
    read = (await client.get(f"/api/v1/devices/{tag['id']}", headers=h)).json()
    assert read["last_seen_at"] is not None, "a tag that nothing heard would look dead for ever"


async def test_a_reader_with_a_place_puts_the_rabbit_on_the_map(client, db, bus):
    """Decisions D261 and D258, the whole PWN point: the readers do not report their positions
    because they do not move, so a person sets the place, and then a sighting is the only
    position a rabbit with no GNSS will ever have."""
    from shared.connectivity.network_location import PROXIMITY_RECORD_TYPE
    from shared.models import Entity, EntityCurrentState, EntityType, Position

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    reader = await _collar(client, db, project, admin, ble_mac=None)

    # the place of SP051345, as Tim gave it
    placed = await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=h,
    )
    assert placed.status_code == 200, placed.text
    assert placed.json()["location_source"] == "static"
    assert placed.json()["static_position"]["coordinates"] == [4.612521, 52.530929]

    # a reader that never reports a fix is on the map the moment its place is set
    await db.rollback()
    reader_state = await db.get(DeviceCurrentState, uuid.UUID(reader["id"]))
    assert reader_state is not None and reader_state.latest_position is not None

    tag_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("tag").replace("-", "_"),
                "label": "EdgeTag",
                "driver_key": "ble_tag",
            },
            headers=h,
        )
    ).json()
    tag = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": tag_type["id"], "name": "EdgeTag 11", "status": "active"},
            headers=h,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{tag['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    await client.put(
        f"/api/v1/devices/{tag['id']}/ble-address",
        json={"ble_mac": "00:00:00:00:00:0b"},
        headers=h,
    )
    entity_type = EntityType(
        key=unique_name("et").replace("-", "_"),
        label="Rabbit",
        group_key="tracked",
        icon_key="wildlife.generic",
    )
    db.add(entity_type)
    await db.flush()
    rabbit = Entity(name="Rabbit 11", entity_type_id=entity_type.id, project_id=project.id)
    db.add(rabbit)
    await db.commit()
    await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": tag["id"],
            "entity_id": str(rabbit.id),
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        headers=h,
    )

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0B, 0x00, 0x00]), -89)]))

    await db.rollback()
    # the tag has a position, at the reader, as an estimate with a radius and never as a fix
    position = (
        await db.execute(select(Position).where(Position.device_id == uuid.UUID(tag["id"])))
    ).scalar_one()
    assert position.record_type == PROXIMITY_RECORD_TYPE
    assert position.accuracy_m == 100.0
    assert position.entity_id == rabbit.id
    assert position.attributes["heard_by_name"] == reader["name"]

    # and the rabbit is on the map, which is the whole point
    state = await db.get(EntityCurrentState, rabbit.id)
    assert state is not None and state.latest_position is not None
    assert state.latest_position_kind == PROXIMITY_RECORD_TYPE
    assert state.latest_accuracy_m == 100.0


async def test_a_reader_without_a_place_only_records_the_contact(client, db, bus):
    """A sighting says where something was only when the device that heard it has a place."""
    from shared.models import Position

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    reader = await _collar(client, db, project, admin, ble_mac=None)
    tag = await _collar(client, db, project, admin, ble_mac="00:00:00:00:00:0b")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0B, 0x00, 0x00]), -89)]))
    await db.rollback()
    rows = (
        (await db.execute(select(Position).where(Position.device_id == uuid.UUID(tag["id"]))))
        .scalars()
        .all()
    )
    assert rows == [], "no place for the reader means no place for what it heard"


async def test_the_live_map_carries_the_contact_count(client, db, bus):
    """Tim, 2026-09-18: a count on the map panel says whether a device is hearing anything just
    now. It is absent for a device that reports no scans, so the panel keeps quiet about one
    that never listens."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    h = admin.headers
    reader = await _collar(client, db, project, admin, ble_mac=None)
    quiet = await _collar(client, db, project, admin, ble_mac=None)
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()
    await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame([(bytes([0x0B, 0x00, 0x00]), -89), (bytes([0x0F, 0x00, 0x00]), -80)]),
    )
    # the reader needs a place, or it is not on the device layer at all
    await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=h,
    )

    body = (
        await client.get(f"/api/v1/projects/{project.id}/map/devices?limit=100", headers=h)
    ).json()
    by_name = {f["properties"]["name"]: f["properties"] for f in body["features"]}
    assert by_name[reader["name"]]["contacts_24h"] == 2
    assert by_name[reader["name"]]["last_contact_at"] is not None
    assert by_name[quiet["name"]]["contacts_24h"] is None, (
        "a device that never listens says nothing"
    )


async def test_a_scan_for_phones_is_presence_and_never_an_identity(client, db, bus):
    """Decision D260. Under the phone filter a sighting says somebody was near the device and
    nothing more: it resolves to no device even when the octets happen to match one, because a
    phone's advertised address is random and a match would be a coincidence, and one scan raises
    one presence however many addresses it heard, since one person carries several."""
    from shared.domain.device_settings import record_setting
    from shared.models import Event, Measurement

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    watcher = await _collar(client, db, project, admin, ble_mac=None)
    # a collar in the same project whose address ends with the octets a phone happens to show
    decoy = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
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
    for name, value in (("ble_scan_interval", 600), ("ble_scan_filter", 3)):
        await record_setting(
            db,
            device_id=uuid.UUID(watcher["id"]),
            key=name,
            value=value,
            source="frame",
            observed_at=SCAN_AT - timedelta(hours=1),
        )
    await db.commit()

    await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame(
            [
                (bytes([0x0C, 0x41, 0x0A]), -61),  # the decoy collar's octets
                (bytes([0xE1, 0x02, 0x9F]), -77),  # a watch
                (bytes([0x33, 0x22, 0x11]), -83),  # earbuds
            ]
        ),
    )

    rows = (
        await db.scalars(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).all()
    assert len(rows) == 3, "every sighting is still stored, like any other"
    assert {r.resolution for r in rows} == {ContactResolution.UNKNOWN}, (
        "a phone is never a device we know, whatever its octets say"
    )
    assert all(r.contact_device_id is None for r in rows)
    decoy_state = await db.get(DeviceCurrentState, uuid.UUID(decoy["id"]))
    assert decoy_state is None or decoy_state.last_seen_at is None, (
        "the decoy was not heard; a coincidence of three octets must not bring it to life"
    )

    events = (
        await db.scalars(
            select(Event).where(
                Event.device_id == uuid.UUID(watcher["id"]), Event.event_type == "human_presence"
            )
        )
    ).all()
    assert len(events) == 1, "one scan window is one presence, not one per address"
    assert events[0].time == SCAN_AT
    assert events[0].context["addresses"] == 3
    assert events[0].context["strongest_rssi_dbm"] == -61
    assert "never an identity" in events[0].context["note"]

    # the rules engine triggers on measurements, not on events, so presence carries a number
    values = (
        await db.scalars(
            select(Measurement.value_num).where(
                Measurement.device_id == uuid.UUID(watcher["id"]),
                Measurement.metric_key == "human_presence",
            )
        )
    ).all()
    assert list(values) == [1.0], "presence in a window, not a count of people"

    body = (
        await client.get(f"/api/v1/devices/{watcher['id']}/contacts", headers=admin.headers)
    ).json()
    assert body["scanning"]["watches_for_people"] is True
    assert body["scanning"]["filter_label"] == "phones"


async def test_a_scan_for_devices_raises_no_presence(client, db, bus):
    """The other filters mean what they always meant: the same frame under filter 1 resolves a
    collar and says nothing about people."""
    from shared.domain.device_settings import record_setting
    from shared.models import Event

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
    await record_setting(
        db,
        device_id=uuid.UUID(watcher["id"]),
        key="ble_scan_filter",
        value=1,
        source="frame",
        observed_at=SCAN_AT - timedelta(hours=1),
    )
    await db.commit()

    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -61)]))

    row = (
        await db.scalars(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).one()
    assert row.resolution == ContactResolution.RESOLVED
    assert row.contact_device_id == uuid.UUID(known["id"])
    events = (
        await db.scalars(
            select(Event).where(
                Event.device_id == uuid.UUID(watcher["id"]), Event.event_type == "human_presence"
            )
        )
    ).all()
    assert events == [], "nothing about people was claimed"


async def test_an_unknown_filter_claims_nothing_either_way(client, db, bus):
    """A device whose settings Protect has never read is not assumed to be watching for people,
    and not assumed not to be: the sightings are stored and resolved as usual, and no presence
    is claimed from a guess."""
    from shared.models import Event

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

    await _scan(db, bus, source, identity, scan_frame([(bytes([0xE1, 0x02, 0x9F]), -77)]))

    assert (
        await db.scalars(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(watcher["id"]))
        )
    ).one().resolution == ContactResolution.UNKNOWN
    assert (
        await db.scalars(
            select(Event).where(
                Event.device_id == uuid.UUID(watcher["id"]), Event.event_type == "human_presence"
            )
        )
    ).all() == []


async def test_a_clock_far_behind_still_resolves_what_it_saw(client, db, bus):
    """The resolver belongs to the project the row lands in, not to the project the device's own
    clock pointed at. A reader 45 hours behind claims times from before it joined the project;
    the clock rule (D259) moves the row to the delivery, and the sighting must be read against
    the fleet of the project it is then attributed to. It was read against an empty fleet, so a
    tag standing a metre away came out as an unknown neighbour."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    known = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")

    # the reader joined the project an hour ago; its clock says two days ago
    joined = datetime.now(UTC) - timedelta(hours=1)
    reader = await _collar(client, db, project, admin, ble_mac=None)
    assignments = await client.get(f"/api/v1/devices/{reader['id']}", headers=admin.headers)
    assignment_id = assignments.json()["project_assignments"][0]["id"]
    from shared.models import DeviceProjectAssignment

    row = await db.get(DeviceProjectAssignment, uuid.UUID(assignment_id))
    row.validity = Range(joined, None, bounds="[)")
    await db.commit()

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()

    claimed = datetime.now(UTC) - timedelta(hours=45)
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)], claimed))

    contact = (
        await db.scalars(
            select(DeviceContact).where(DeviceContact.device_id == uuid.UUID(reader["id"]))
        )
    ).one()
    assert contact.project_id == project.id, "the corrected time is inside the assignment"
    assert contact.resolution == ContactResolution.RESOLVED
    assert contact.contact_device_id == uuid.UUID(known["id"])


async def test_a_placed_device_puts_its_entity_on_the_map_too(client, db, bus):
    """Decision D261. A scanner reports nothing, so no record will ever place the entity it is
    on: the place has to reach the entity's current state as well as the device's, whichever of
    the two came first. The entity was left blank on the live map before this."""
    from shared.models import EntityCurrentState

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    # the catalogue's own scanner sub-type, seeded by migration 0044
    catalogue = (await client.get("/api/v1/entity-types?limit=400", headers=admin.headers)).json()
    entity_type = next(t for t in catalogue["items"] if t["key"] == "scanner")

    # the place is set first, the entity made afterwards: the order a reader is really set up in
    reader = await _collar(client, db, project, admin, ble_mac=None)
    placed = await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    assert placed.status_code == 200, placed.text
    assert placed.json()["location_source"] == "static"

    made = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": reader["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": entity_type["id"], "name": unique_name("Scanner")},
        },
        headers=admin.headers,
    )
    assert made.status_code == 201, made.text
    entity_id = uuid.UUID(made.json()["entity_id"])

    placed_row = (
        await db.execute(
            select(EntityCurrentState.latest_position, EntityCurrentState.latest_position_kind)
            .where(EntityCurrentState.entity_id == entity_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    assert placed_row is not None and placed_row[0] is not None, (
        "the entity of a placed device is on the map"
    )
    assert placed_row[1] == "static"

    # and the other order: the place set while the entity is already there
    other = await _collar(client, db, project, admin, ble_mac=None)
    second = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": other["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": entity_type["id"], "name": unique_name("Scanner")},
        },
        headers=admin.headers,
    )
    assert second.status_code == 201, second.text
    await client.put(
        f"/api/v1/devices/{other['id']}/static-position",
        json={"latitude": 52.528591, "longitude": 4.609628},
        headers=admin.headers,
    )
    second_row = (
        await db.execute(
            select(EntityCurrentState.latest_position).where(
                EntityCurrentState.entity_id == uuid.UUID(second.json()["entity_id"])
            )
        )
    ).one_or_none()
    assert second_row is not None and second_row[0] is not None


async def test_a_place_set_afterwards_gives_the_old_sightings_a_position(client, db, bus):
    """Decision D258, repairing the past. A reader is put up, it scans for a week, and only then
    does somebody measure where it stands. Without this, every sighting from before that
    afternoon says when but never where, and for a rabbit wearing only a tag that is the whole
    of what could ever have been known about it."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    reader = await _collar(client, db, project, admin, ble_mac=None)
    tag = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()

    # it scans twice while nobody has measured where it stands
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))
    await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame([(bytes([0x0C, 0x41, 0x0A]), -70)], SCAN_AT + timedelta(minutes=5)),
    )
    before = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tag["id"])))
    ).all()
    assert before == [], "nothing knows where the reader is, so nothing knows where the tag was"

    placed = await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    assert placed.status_code == 200, placed.text

    after = (
        await db.scalars(
            select(Position)
            .where(Position.device_id == uuid.UUID(tag["id"]))
            .order_by(Position.time)
        )
    ).all()
    assert len(after) == 2, "both sightings, not only the newest"
    assert {p.record_type for p in after} == {"proximity"}
    assert all(p.attributes["heard_by"] == reader["id"] for p in after)

    # and setting it again writes nothing twice
    again = await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    assert again.status_code == 200
    assert (
        len(
            (
                await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tag["id"])))
            ).all()
        )
        == 2
    )


async def test_an_address_arriving_later_gives_its_sightings_a_position_too(client, db, bus):
    """The other half of the same repair. The reader had a place all along, but the tag was an
    unknown neighbour, so no position could be written for a device nobody could name. Recording
    the address resolves the sightings (decision D253); the place has to follow, or the rabbit
    stays off the map for the whole period before somebody typed its address."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    reader = await _collar(client, db, project, admin, ble_mac=None)
    tag = await _collar(client, db, project, admin, ble_mac=None)
    placed = await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    assert placed.status_code == 200
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()

    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))
    assert (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tag["id"])))
    ).all() == []

    saved = await client.put(
        f"/api/v1/devices/{tag['id']}/ble-address",
        json={"ble_mac": "d4:22:11:0a:41:0c"},
        headers=admin.headers,
    )
    assert saved.status_code == 200, saved.text

    positions = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tag["id"])))
    ).all()
    assert len(positions) == 1, "the sighting it earned when it stopped being a stranger"
    assert positions[0].record_type == "proximity"
    assert positions[0].attributes["heard_by"] == reader["id"]


async def test_being_heard_is_when_the_animal_was_last_seen(client, db, bus):
    """An animal wearing only a tag is never seen by anything but a reader, so a sighting is the
    only thing that can move its "last seen". The panel said never of a rabbit heard minutes
    before."""
    from shared.models import EntityCurrentState

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    catalogue = (await client.get("/api/v1/entity-types?limit=400", headers=admin.headers)).json()
    rabbit = next(t for t in catalogue["items"] if t["key"] == "rabbit")

    reader = await _collar(client, db, project, admin, ble_mac=None)
    await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    tag = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    made = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": tag["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": rabbit["id"], "name": unique_name("Rabbit")},
        },
        headers=admin.headers,
    )
    assert made.status_code == 201, made.text
    entity_id = uuid.UUID(made.json()["entity_id"])

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()

    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))

    seen = (
        await db.execute(
            select(EntityCurrentState.last_seen_at).where(EntityCurrentState.entity_id == entity_id)
        )
    ).scalar_one()
    assert seen == SCAN_AT, "the moment a reader heard it, not never"


async def test_an_attribution_job_does_not_blank_a_placed_device(client, db, bus):
    """Decision D261 against architecture 28.8. A rebuild of the current state reads the
    positions a device produced, and a placed device produces none, so the rebuild blanked it:
    assigning a scanner to an entity queues an attribution job, and the job took the whole
    scanner off the map a moment after it was put there. A place is not a record; no rebuild can
    find it, so it is stamped back on."""
    from shared.curation.apply import recompute_current_state
    from shared.models import EntityCurrentState

    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    catalogue = (await client.get("/api/v1/entity-types?limit=400", headers=admin.headers)).json()
    scanner_type = next(t for t in catalogue["items"] if t["key"] == "scanner")

    reader = await _collar(client, db, project, admin, ble_mac=None)
    await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    made = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": reader["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": scanner_type["id"], "name": unique_name("Scanner")},
        },
        headers=admin.headers,
    )
    assert made.status_code == 201, made.text
    entity_id = uuid.UUID(made.json()["entity_id"])

    # what the attribution job does after the assignment, in the same shape
    await recompute_current_state(db, uuid.UUID(reader["id"]), {entity_id})
    await db.commit()

    rows = (
        await db.execute(
            select(EntityCurrentState.latest_position, EntityCurrentState.latest_position_kind)
            .where(EntityCurrentState.entity_id == entity_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert rows[0] is not None, "the rebuild must not take a placed scanner off the map"
    assert rows[1] == "static"

    device_rows = (
        await db.execute(
            select(DeviceCurrentState.latest_position, DeviceCurrentState.latest_position_kind)
            .where(DeviceCurrentState.device_id == uuid.UUID(reader["id"]))
            .execution_options(populate_existing=True)
        )
    ).one()
    assert device_rows[0] is not None and device_rows[1] == "static"


async def test_the_map_names_the_reader_that_heard_a_tag(client, db, bus):
    """Tim, 2026-09-18: a proximity position is somebody else's word for where a device was, and
    the somebody is the point. The panel says "Heard by SP051313" as a link, so the map answer
    has to carry the reader's id and name on both layers."""
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    catalogue = (await client.get("/api/v1/entity-types?limit=400", headers=admin.headers)).json()
    rabbit = next(t for t in catalogue["items"] if t["key"] == "rabbit")

    reader = await _collar(client, db, project, admin, ble_mac=None)
    await client.put(
        f"/api/v1/devices/{reader['id']}/static-position",
        json={"latitude": 52.530929, "longitude": 4.612521},
        headers=admin.headers,
    )
    tag = await _collar(client, db, project, admin, ble_mac="d4:22:11:0a:41:0c")
    made = await client.post(
        f"/api/v1/projects/{project.id}/entity-assignments",
        json={
            "device_id": tag["id"],
            "valid_from": "2026-01-02T00:00:00+00:00",
            "new_entity": {"entity_type_id": rabbit["id"], "name": unique_name("Rabbit")},
        },
        headers=admin.headers,
    )
    assert made.status_code == 201, made.text

    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    identity = unique_name("eui").replace("-", "")[:16]
    from shared.models import ExternalIdentity

    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=identity, device_id=uuid.UUID(reader["id"])
        )
    )
    await db.commit()
    await _scan(db, bus, source, identity, scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74)]))

    entities = (
        await client.get(f"/api/v1/projects/{project.id}/map/current", headers=admin.headers)
    ).json()
    animal = next(
        f for f in _map_features(entities) if f["properties"].get("position_kind") == "proximity"
    )
    assert animal["properties"]["heard_by"] == reader["id"]
    assert animal["properties"]["heard_by_name"] == reader["name"]

    devices = (
        await client.get(f"/api/v1/projects/{project.id}/map/devices", headers=admin.headers)
    ).json()
    heard = next(f for f in _map_features(devices) if f["properties"]["device_id"] == tag["id"])
    assert heard["properties"]["heard_by_name"] == reader["name"]

    # the reader itself was heard by nobody: its own place is not somebody else's word
    scanner = next(
        f for f in _map_features(devices) if f["properties"]["device_id"] == reader["id"]
    )
    assert scanner["properties"]["heard_by"] is None


async def test_every_scan_counts_as_a_number_even_when_it_saw_nothing(client, db, bus):
    """A scanner's activity draws as a line like a battery does (Tim, 2026-09-18), so every scan
    window leaves one `ble_contacts` sample. A scan that saw nothing is a zero and not a gap:
    the gaps are the times the device was not looking, which is the other thing worth telling
    apart."""
    from shared.models import Measurement

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

    await _scan(
        db,
        bus,
        source,
        identity,
        scan_frame([(bytes([0x0C, 0x41, 0x0A]), -74), (bytes([0xE1, 0x02, 0x9F]), -88)]),
    )
    await _scan(db, bus, source, identity, scan_frame([], SCAN_AT + timedelta(minutes=10)))

    values = (
        await db.scalars(
            select(Measurement.value_num)
            .where(
                Measurement.device_id == uuid.UUID(watcher["id"]),
                Measurement.metric_key == "ble_contacts",
            )
            .order_by(Measurement.time)
        )
    ).all()
    assert list(values) == [2.0, 0.0], "the empty scan is a zero, not a missing sample"


async def test_the_read_says_what_was_detected_beside_what_arrived(client, db, bus):
    """Tim, 2026-09-18: the scan message carries the device's own count of what it detected, and
    that is the important number. Only what fits in one payload is sent, so counting the
    sightings that arrived understates what was there; both are reported, because they answer
    different questions."""
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

    # a scan that says it saw nine and carries two: the air cut it short
    body = struct.pack("<I", int(SCAN_AT.timestamp())) + bytes([9])
    for octets, rssi in ((bytes([0x0C, 0x41, 0x0A]), -70), (bytes([0xE1, 0x02, 0x9F]), -80)):
        body += octets + bytes([rssi + 128])
    await _scan(db, bus, source, identity, (bytes([0xFA, len(body)]) + body).hex())

    read = (
        await client.get(f"/api/v1/devices/{watcher['id']}/contacts", headers=admin.headers)
    ).json()
    assert read["scans"] == 1
    assert read["detected"] == 9, "the device's own count, not what fitted in the message"
    assert read["reported"] == 2
    assert sum(c["contacts"] for c in read["counterparts"]) == 2, "two could be named"


async def test_a_flash_log_counts_each_scan_on_its_own(client, db, bus):
    """A stored log carries many scans into one delivery. The count of what a scan reported has
    to be that scan's, and it was the whole delivery's: the second scan in a stream claimed to
    have reported its own sightings plus every sighting before it."""
    from shared.device_drivers.base import DecodedRecords
    from shared.device_drivers.registry import get_driver

    driver = get_driver("opencollar")
    records = DecodedRecords()
    for index in range(3):
        at = SCAN_AT + timedelta(minutes=index)
        body = struct.pack("<I", int(at.timestamp())) + bytes([2])
        body += bytes([0x0C, 0x41, 0x0A]) + bytes([-70 + 128])
        body += bytes([0xE1, 0x02, 0x9F]) + bytes([-80 + 128])
        driver._decode_ble_scan(body, at, records)

    reported = [s.state["ble_scan"]["reported"] for s in records.states if "ble_scan" in s.state]
    assert reported == [2, 2, 2], "each scan reported two, not two then four then six"
    assert len(records.contacts) == 6
