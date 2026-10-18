"""Offload stations end to end (phase 42, decisions D319 to D324): a tracker's LP0 credentials
on its device, a station's card uploaded as a zip, every frame verified and decrypted with its
own tracker's keys, repeats and unknown addresses, the station as a gateway linked to its
device, the Offload station card, and the keys never returned."""

import base64
import io
import json
import uuid
import zipfile

import pytest
import pytest_asyncio
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.bus import RedisStreamsBus, Topic
from shared.connectivity.adapters.lp0_station import SOURCE_ID as LP0_SOURCE_ID
from shared.device_drivers.opencollar import OpenCollarDriver
from shared.enums import AcquisitionChannel, Role
from shared.ingest import commit_and_publish, store_inbound
from shared.models import (
    DataSource,
    DeviceType,
    Entity,
    EntityType,
    ExternalIdentity,
    Gateway,
    GatewayReception,
    Position,
    SourceDelivery,
    SourceEvent,
)
from shared.station_decode import decode_station_frame, unwrap_station_frame
from shared.timeutil import utc_now
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_ingest_and_attention import _decode_pending
from tests.api.test_log_files_api import _decode
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name
from tests.decoder.conftest import inbound
from tests.decoder.test_logfiles import FLASH, SHORT_13
from tests.shared.test_lp0_lorawan import APP_S_KEY, NWK_S_KEY, build_uplink
from tests.shared.test_lp0_lorawan import Credentials as Keys

pytestmark = pytest.mark.asyncio

STATION_EUI = "0016C001F0ABCDEF"
ADDR_A = "26010203"
ADDR_B = "26010204"
KEYS_A = Keys(ADDR_A, APP_S_KEY, NWK_S_KEY)
ADDR_C = "26010209"  # the second test's tracker; the test database is shared
KEYS_C = Keys(ADDR_C, APP_S_KEY, NWK_S_KEY)
KEYS_B = Keys(ADDR_B, bytes(range(16, 32)), bytes(range(32, 48)))
OTHER_KEYS = Keys(ADDR_A, bytes(range(1, 17)), bytes(range(2, 18)))
RECORDS = bytes.fromhex(FLASH)


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


def line(
    phy: bytes,
    *,
    time: str = "2026-10-12T08:50:31Z",
    rssi: int = -71,
    lp0: dict | None = None,
    station: str = STATION_EUI,
) -> str:
    document: dict = {"gatewayEui": station}
    if lp0 is not None:
        document["lp0"] = lp0
    return json.dumps(
        {
            **document,
            "rxpk": {
                "time": time,
                "tmst": 1791795031,
                "freq": 864.629,
                "chan": 0,
                "rfch": 0,
                "stat": 1,
                "modu": "LORA",
                "datr": "SF7BW250",
                "codr": "4/5",
                "rssi": rssi,
                "lsnr": 9,
                "size": len(phy),
                "data": base64.b64encode(phy).decode(),
            },
        }
    )


async def _opencollar_type(client, h) -> dict:
    return (
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


async def _device(
    client,
    h,
    type_id: str,
    project_id,
    *,
    serial: str | None = None,
    valid_from: str = "2023-01-01T00:00:00+00:00",
) -> dict:
    body = {"device_type_id": type_id, "name": unique_name("dev"), "status": "active"}
    if serial:
        body["serial_number"] = serial
    device = (await client.post("/api/v1/devices", json=body, headers=h)).json()
    response = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project_id), "valid_from": valid_from},
        headers=h,
    )
    assert response.status_code == 201, response.text
    return device


def card_zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return buffer.getvalue()


async def test_card_upload_decodes_each_tracker_with_its_own_keys(client, db, bus):
    admin, project, _entity, source, live_device, live_external = await _setup(client, db)
    h = admin.headers
    project_id = project.id  # a later rollback expires the row; keep the id in hand
    oc = await _opencollar_type(client, h)
    station = await _device(client, h, oc["id"], project_id, serial=STATION_EUI)
    tracker_a = await _device(client, h, oc["id"], project_id)
    tracker_b = await _device(client, h, oc["id"], project_id)

    # the keys are set on the device and never come back
    put = await client.put(
        f"/api/v1/devices/{tracker_a['id']}/lp0-credentials",
        json={
            "dev_addr": "26:01:02:03",
            "app_s_key": APP_S_KEY.hex(),
            "nwk_s_key": NWK_S_KEY.hex(),
        },
        headers=h,
    )
    assert put.status_code == 200, put.text
    assert put.json()["dev_addr"] == ADDR_A and put.json()["keys_set"] is True
    # the keys are visible and changeable to whoever may set them (Tim, 2026-10-15)
    assert put.json()["app_s_key"] == APP_S_KEY.hex().upper()
    assert put.json()["nwk_s_key"] == NWK_S_KEY.hex().upper()
    shown = (
        await client.get(f"/api/v1/devices/{tracker_a['id']}/lp0-credentials", headers=h)
    ).json()
    assert shown["app_s_key"] == APP_S_KEY.hex().upper() and shown["keys_set"] is True
    taken = await client.put(
        f"/api/v1/devices/{tracker_b['id']}/lp0-credentials",
        json={"dev_addr": ADDR_A, "app_s_key": APP_S_KEY.hex(), "nwk_s_key": NWK_S_KEY.hex()},
        headers=h,
    )
    assert taken.status_code == 409 and tracker_a["name"] in taken.text
    bad = await client.put(
        f"/api/v1/devices/{tracker_b['id']}/lp0-credentials",
        json={"dev_addr": "xyz", "app_s_key": "00", "nwk_s_key": "00"},
        headers=h,
    )
    assert bad.status_code == 422
    identity = await db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == LP0_SOURCE_ID, ExternalIdentity.external_id == ADDR_A
        )
    )
    assert identity is not None and str(identity.device_id) == tracker_a["id"]
    assert identity.identity_type == "dev_addr"

    # the second record of the stream came over LoRaWAN first, so the card repeats it
    live_source = await db.get(DataSource, uuid.UUID(source["id"]))
    stored = await store_inbound(
        db,
        live_source,
        inbound(
            live_external,
            {"fPort": 13, "data": base64.b64encode(bytes.fromhex(SHORT_13)).decode()},
            acquisition_channel=AcquisitionChannel.LORAWAN,
        ),
    )
    await commit_and_publish(db, bus, [stored])
    # the live device is a generic JSON one; make it tracker A's twin by moving its identity
    live_event = stored.source_event
    live_event.device_id = uuid.UUID(tracker_a["id"])
    await db.commit()
    await process_source_event(db, live_event.id, live_event.ingested_at)
    await db.commit()

    frames = [
        build_uplink(KEYS_A, 1, 29, RECORDS),  # three stored fixes
        build_uplink(KEYS_A, 1, 29, RECORDS),  # the station saved it again (lost receipt)
        build_uplink(KEYS_B, 5, 29, RECORDS),  # an address nobody set yet
        build_uplink(OTHER_KEYS, 2, 29, RECORDS),  # tracker A's address, the wrong keys
    ]
    first = "\n".join(["", line(frames[0]), line(frames[1]), line(frames[2])]) + "\n"
    second = "\n".join(["", line(frames[3], time="1970-01-06T00:00:00Z", rssi=-90)]) + "\n"
    upload = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={
            "file": (
                "card.zip",
                card_zip(
                    {
                        f"LOG_1/{STATION_EUI}_1791795031.jsonl": first,
                        f"LOG_2/{STATION_EUI}_1791796000.jsonl": second,
                        "LOG_2/notes.txt": "hello",
                    }
                ),
                "application/zip",
            )
        },
        headers=h,
    )
    assert upload.status_code == 201, upload.text
    result = upload.json()
    assert [f["original_filename"] for f in result["files"]] == [
        f"{STATION_EUI}_1791795031.jsonl",
        f"{STATION_EUI}_1791796000.jsonl",
    ]
    assert [s["name"] for s in result["skipped"]] == ["LOG_2/notes.txt"]
    assert result["other_station"] == []
    rows = {f["original_filename"]: f for f in result["files"]}
    assert all(f["acquisition_channel"] == "lp0" for f in rows.values())
    assert rows[f"{STATION_EUI}_1791795031.jsonl"]["attributes"]["folder"] == "LOG_1"

    again = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": (f"{STATION_EUI}_1791795031.jsonl", first.encode(), "text/plain")},
        headers=h,
    )
    assert again.status_code == 422 and "uploaded before" in again.text

    for f in result["files"]:
        await _decode(bus, f["id"])
    await db.rollback()
    one = (
        await client.get(
            f"/api/v1/log-files/{rows[f'{STATION_EUI}_1791795031.jsonl']['id']}", headers=h
        )
    ).json()
    assert one["status"] == "complete", one
    assert (one["frames_total"], one["frames_done"], one["frames_failed"]) == (3, 3, 0)
    # the first frame: three records, one of them known from the air; the second a repeat;
    # the third retained for an unknown address
    assert (one["records_new"], one["records_duplicate"]) == (2, 1)
    assert one["attributes"]["frames_repeated"] == 1 and one["attributes"]["frames_retained"] == 1
    trackers = one["attributes"]["trackers"]
    assert trackers[ADDR_A]["frames"] == 1 and trackers[ADDR_A]["repeats"] == 1
    assert trackers[ADDR_B]["retained"] == 1 and trackers[ADDR_B]["device_id"] is None
    two = (
        await client.get(
            f"/api/v1/log-files/{rows[f'{STATION_EUI}_1791796000.jsonl']['id']}", headers=h
        )
    ).json()
    assert two["status"] == "complete" and two["frames_failed"] == 1
    assert two["attributes"]["errors"] == {"PAYLOAD_DECODE_FAILED": 1}

    events = (
        await db.scalars(
            select(SourceEvent)
            .where(SourceEvent.data_source_id == LP0_SOURCE_ID)
            .order_by(SourceEvent.id)
        )
    ).all()
    by_counter: dict = {}
    for e in events:  # the first event under an address and counter; the repeat comes later
        by_counter.setdefault((e.external_id, e.provider_metadata.get("f_cnt")), e)
    assert by_counter[(ADDR_A, 1)].processing_status == "processed"
    assert by_counter[(ADDR_A, 1)].provider_metadata["mic_ok"] is True
    assert by_counter[(ADDR_A, 1)].provider_metadata["station_eui"] == STATION_EUI
    assert by_counter[(ADDR_A, 1)].network_received_at is not None
    repeats = [
        e for e in events if e.external_id == ADDR_A and e.provider_metadata.get("duplicate_of")
    ]
    assert len(repeats) == 1 and repeats[0].processing_status == "duplicate"
    assert by_counter[(ADDR_B, 5)].processing_status == "unassigned"
    assert by_counter[(ADDR_B, 5)].device_id is None
    failed = by_counter[(ADDR_A, 2)]
    assert failed.processing_status == "failed" and failed.error_code == "PAYLOAD_DECODE_FAILED"
    assert failed.network_received_at is None  # 1970: the station's clock is not believed
    assert failed.provider_metadata["received_at"].startswith("1970")

    positions = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tracker_a["id"])))
    ).all()
    assert len(positions) == 3
    # the same frame through the shared decode path gives the same records (phase 43 P6):
    # Protect Go decodes a card on a laptop with these two calls and nothing else
    opened = unwrap_station_frame(
        frames[0],
        KEYS_A,
        device_name="a",
        device_eui=None,
        source_eui=None,
        lp0_version=None,
        last_f_cnt=None,
    )
    shared_records = decode_station_frame(
        OpenCollarDriver(),
        opened,
        document=json.loads(line(frames[0])),
        received_at=None,
        fallback_time=utc_now(),
        firmware_version=None,
    )
    assert sorted(p.time for p in shared_records.positions) == sorted(p.time for p in positions)
    assert sorted(
        (round(p.latitude, 5), round(p.longitude, 5)) for p in shared_records.positions
    ) == sorted((round(to_shape(p.geom).y, 5), round(to_shape(p.geom).x, 5)) for p in positions)
    # the newest verified counter is kept per device (firmware issue 772: a frame carries 16
    # bits of it; the next one is read in the right half)
    from shared.models import DeviceLp0Credentials

    row = await db.get(DeviceLp0Credentials, uuid.UUID(tracker_a["id"]))
    assert row is not None and row.last_f_cnt == 1
    assert row.last_frame_at is not None and row.last_frame_at.year == 2026
    deliveries = (
        await db.scalars(
            select(SourceDelivery).where(
                SourceDelivery.canonical_type == "position",
                SourceDelivery.canonical_id.in_([p.id for p in positions]),
            )
        )
    ).all()
    assert sorted(d.acquisition_channel for d in deliveries) == ["lorawan", "lp0", "lp0", "lp0"]

    # the station is a gateway of the source, linked to its device, with a reception per frame
    gateway = await db.scalar(
        select(Gateway).where(
            Gateway.data_source_id == LP0_SOURCE_ID, Gateway.external_id == STATION_EUI.lower()
        )
    )
    assert gateway is not None and str(gateway.device_id) == station["id"]
    assert gateway.name == station["name"] and gateway.attributes["kind"] == "offload_station"
    receptions = (
        await db.scalars(
            select(GatewayReception).where(GatewayReception.gateway_id == STATION_EUI.lower())
        )
    ).all()
    assert len(receptions) == 4 and {r.rssi for r in receptions} == {-71.0, -90.0}

    # the unknown address waits on Needs attention; setting its keys walks the frame
    identities = (await client.get("/api/v1/attention/identities", headers=h)).json()["items"]
    waiting = next(i for i in identities if i["external_id"] == ADDR_B)
    assert waiting["identity_type"] == "dev_addr"
    # the project's Offload page: the station, tracker A, and address B as unknown
    page = (await client.get(f"/api/v1/projects/{project_id}/offload", headers=h)).json()
    assert [s["device_id"] for s in page["stations"]] == [station["id"]]
    listed = page["stations"][0]
    assert listed["station_eui"] == STATION_EUI and listed["gateway_id"] is not None
    assert (listed["files"], listed["frames"], listed["frames_retained"]) == (2, 4, 1)
    assert (listed["receptions"], listed["trackers"]) == (4, 1)
    assert listed["last_reception_at"] is not None and listed["card_ok"] is None
    assert [t["device_id"] for t in page["trackers"]] == [tracker_a["id"]]
    assert page["trackers"][0]["dev_addr"] == ADDR_A and page["trackers"][0]["keys_set"] is True
    assert page["trackers"][0]["receptions"] == 3 and page["trackers"][0]["stations"] == 1
    assert page["trackers"][0]["last_station_device_id"] == station["id"]
    assert page["trackers"][0]["last_f_cnt"] == 1
    assert APP_S_KEY.hex().upper() not in json.dumps(page)
    assert [u["dev_addr"] for u in page["unknown"]] == [ADDR_B]
    assert page["unknown"][0]["receptions"] == 1 and page["unknown"][0]["last_seen_at"]
    without_before = page["devices_without_address"]
    assert without_before >= 1  # tracker B at least

    group, _handler, walk = await _decode_pending(db, bus)
    before = (
        await client.get(f"/api/v1/devices/{tracker_b['id']}/lp0-credentials", headers=h)
    ).json()
    assert before["keys_set"] is False and before["frames_waiting"] == 0
    put = await client.put(
        f"/api/v1/devices/{tracker_b['id']}/lp0-credentials",
        json={
            "dev_addr": ADDR_B,
            "app_s_key": KEYS_B.app_s_key.hex(),
            "nwk_s_key": KEYS_B.nwk_s_key.hex(),
        },
        headers=h,
    )
    assert put.status_code == 200, put.text
    assert put.json()["queued"] == 1
    await bus.consume(Topic.IDENTITY_REPROCESS_REQUESTED, group, "c1", walk, once=True)
    await db.rollback()
    event_b = await db.scalar(
        select(SourceEvent).where(
            SourceEvent.data_source_id == LP0_SOURCE_ID, SourceEvent.external_id == ADDR_B
        )
    )
    assert event_b is not None and event_b.processing_status == "processed"
    assert str(event_b.device_id) == tracker_b["id"]
    positions_b = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tracker_b["id"])))
    ).all()
    assert len(positions_b) == 3
    linked = await db.scalar(
        select(GatewayReception).where(
            GatewayReception.source_event_id == event_b.id, GatewayReception.device_id.is_not(None)
        )
    )
    assert linked is not None

    # the page after the link: B is a tracker now, nothing unknown, one device fewer without
    page = (await client.get(f"/api/v1/projects/{project_id}/offload", headers=h)).json()
    assert {t["device_id"] for t in page["trackers"]} == {tracker_a["id"], tracker_b["id"]}
    b_row = next(t for t in page["trackers"] if t["device_id"] == tracker_b["id"])
    assert b_row["receptions"] == 1 and b_row["dev_addr"] == ADDR_B
    assert page["unknown"] == []
    assert page["devices_without_address"] == without_before - 1

    # the station card
    card = (await client.get(f"/api/v1/devices/{station['id']}/offload", headers=h)).json()
    assert card["is_station"] is True and card["station_eui"] == STATION_EUI
    assert (card["files"], card["frames"], card["records_new"], card["records_known"]) == (
        2,
        4,
        2,
        1,
    )
    assert card["frames_repeated"] == 1 and card["frames_retained"] == 1
    served = {t["device_id"]: t for t in card["trackers"]}
    assert served[tracker_a["id"]]["frames"] == 3 and served[tracker_a["id"]]["dev_addr"] == ADDR_A
    assert served[tracker_b["id"]]["frames"] == 1
    not_station = (await client.get(f"/api/v1/devices/{tracker_a['id']}/offload", headers=h)).json()
    assert not_station["is_station"] is False and not_station["files"] == 0

    # the connectivity tab of a tracker names the station
    connectivity = (
        await client.get(f"/api/v1/devices/{tracker_a['id']}/connectivity", headers=h)
    ).json()
    block = next(s for s in connectivity["sources"] if s["channel"] == "lp0")
    # one frame decoded, one repeat, one that did not verify
    assert (
        block["offload"]["frames"],
        block["offload"]["repeats"],
        block["offload"]["failed"],
    ) == (
        1,
        1,
        1,
    )
    assert block["offload"]["stations"][0]["station_eui"] == STATION_EUI
    assert block["offload"]["stations"][0]["device_id"] == station["id"]

    # the traffic rows carry the reception
    traffic = (
        await client.get(
            f"/api/v1/projects/{project_id}/traffic",
            params={"device_id": tracker_a["id"]},
            headers=h,
        )
    ).json()
    lp0_rows = [r for r in traffic if r["acquisition_channel"] == "lp0"]
    first_frame = next(
        r for r in lp0_rows if r["f_cnt"] == 1 and r["processing_status"] == "processed"
    )
    assert first_frame["best_rssi"] == -71.0 and first_frame["f_port"] == 29
    assert first_frame["time"] == "2026-10-12T08:50:31Z"
    assert first_frame["receptions"][0]["gateway_id"] == STATION_EUI.lower()

    # a viewer reads the card and the credentials' summary, never the keys; cannot set them
    await db.refresh(project)  # expired by the rollbacks above
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (
        await client.get(f"/api/v1/devices/{station['id']}/offload", headers=viewer.headers)
    ).status_code == 200
    for_viewer = await client.get(f"/api/v1/projects/{project_id}/offload", headers=viewer.headers)
    assert for_viewer.status_code == 200 and len(for_viewer.json()["stations"]) == 1
    assert APP_S_KEY.hex().upper() not in for_viewer.text
    summary = await client.get(
        f"/api/v1/devices/{tracker_a['id']}/lp0-credentials", headers=viewer.headers
    )
    assert summary.status_code == 200 and summary.json()["keys_set"] is True
    assert summary.json()["app_s_key"] is None and summary.json()["nwk_s_key"] is None
    assert APP_S_KEY.hex().upper() not in summary.text
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    for_operator = (
        await client.get(
            f"/api/v1/devices/{tracker_a['id']}/lp0-credentials", headers=operator.headers
        )
    ).json()
    assert for_operator["app_s_key"] == APP_S_KEY.hex().upper()
    forbidden = await client.put(
        f"/api/v1/devices/{tracker_a['id']}/lp0-credentials",
        json={"dev_addr": ADDR_A, "app_s_key": APP_S_KEY.hex(), "nwk_s_key": NWK_S_KEY.hex()},
        headers=viewer.headers,
    )
    assert forbidden.status_code == 403
    cleared = await client.delete(f"/api/v1/devices/{tracker_a['id']}/lp0-credentials", headers=h)
    assert cleared.status_code == 204
    after = (
        await client.get(f"/api/v1/devices/{tracker_a['id']}/lp0-credentials", headers=h)
    ).json()
    assert after["keys_set"] is False and after["dev_addr"] is None
    await db.rollback()
    identity = await db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == LP0_SOURCE_ID, ExternalIdentity.external_id == ADDR_A
        )
    )
    assert identity is not None and identity.device_id is None
    await bus.redis.xgroup_destroy(Topic.IDENTITY_REPROCESS_REQUESTED, group)
    _ = DeviceType, live_device


async def test_a_device_without_keys_fails_plainly_and_decodes_again_once_set(client, db, bus):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    from tests.api.conftest import create_project

    project = await create_project(db)
    oc = await _opencollar_type(client, h)
    station = await _device(client, h, oc["id"], project.id, serial="0016C001F0000001")
    tracker = await _device(client, h, oc["id"], project.id)
    # the address is known (a link from Needs attention would do the same), the keys not yet
    from shared.domain.lp0 import lp0_source

    source = await lp0_source(db)
    db.add(
        ExternalIdentity(
            data_source_id=source.id,
            device_id=uuid.UUID(tracker["id"]),
            external_id=ADDR_C,
            identity_type="dev_addr",
        )
    )
    await db.commit()
    text = "\n" + line(build_uplink(KEYS_C, 3, 29, RECORDS)) + "\n"
    upload = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": ("0016C001F0000001_1791795031.jsonl", text.encode(), "text/plain")},
        headers=h,
    )
    assert upload.status_code == 201, upload.text
    row = upload.json()["files"][0]
    await _decode(bus, row["id"])
    got = (await client.get(f"/api/v1/log-files/{row['id']}", headers=h)).json()
    assert got["status"] == "complete" and got["frames_failed"] == 1
    assert got["attributes"]["errors"] == {"CREDENTIALS_MISSING": 1}
    assert got["attributes"]["trackers"][ADDR_C]["without_keys"] == 1
    put = await client.put(
        f"/api/v1/devices/{tracker['id']}/lp0-credentials",
        json={"dev_addr": ADDR_C, "app_s_key": APP_S_KEY.hex(), "nwk_s_key": NWK_S_KEY.hex()},
        headers=h,
    )
    assert put.status_code == 200 and put.json()["queued"] == 0
    redecode = await client.post(f"/api/v1/log-files/{row['id']}/redecode", headers=h)
    assert redecode.status_code == 200
    await _decode(bus, row["id"], reprocess=True)
    got = (await client.get(f"/api/v1/log-files/{row['id']}", headers=h)).json()
    assert got["status"] == "complete" and got["frames_failed"] == 0
    assert got["records_new"] == 3


async def test_a_file_that_is_not_a_card_is_refused(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    from tests.api.conftest import create_project

    project = await create_project(db)
    oc = await _opencollar_type(client, h)
    station = await _device(client, h, oc["id"], project.id)
    response = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": ("raw.txt", b"AAEC\n", "text/plain")},
        headers=h,
    )
    assert response.status_code == 422 and "Not a station file" in response.text
    response = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": ("card.zip", card_zip({"readme.txt": "x"}), "application/zip")},
        headers=h,
    )
    assert response.status_code == 422 and "holds no station file" in response.text


async def test_cards_uploaded_on_the_offload_page_find_their_stations(client, db):
    """Tim, 2026-10-18: the person who collected the cards uploads them on the Offload page,
    and each file goes to the station its name carries; a file of a station the project does
    not have is skipped with its EUI, never guessed."""
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    project_id = project.id
    oc = await _opencollar_type(client, h)
    first = await _device(client, h, oc["id"], project_id, serial="0016C001F0AB1001")
    second = await _device(client, h, oc["id"], project_id, serial="0016C001F0AB1002")
    frame = line(build_uplink(KEYS_A, 1, 29, RECORDS))
    frame_two = line(build_uplink(KEYS_A, 2, 29, RECORDS), station="0016C001F0AB1002")
    frame_other = line(build_uplink(KEYS_A, 3, 29, RECORDS), station="0016C001F0AB1999")
    archive = card_zip(
        {
            "LOG_1/0016C001F0AB1001_1791795031.jsonl": frame + "\n",
            "LOG_1/0016C001F0AB1002_1791795032.jsonl": frame_two + "\n",
            "LOG_2/0016C001F0AB1999_1791795033.jsonl": frame_other + "\n",
        }
    )

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    refused = await client.post(
        f"/api/v1/projects/{project_id}/offload-files",
        files={"file": ("cards.zip", archive, "application/zip")},
        headers=viewer.headers,
    )
    assert refused.status_code == 403

    upload = await client.post(
        f"/api/v1/projects/{project_id}/offload-files",
        files={"file": ("cards.zip", archive, "application/zip")},
        headers=h,
    )
    assert upload.status_code == 201, upload.text
    result = upload.json()
    by_name = {f["original_filename"]: f for f in result["files"]}
    assert set(by_name) == {
        "0016C001F0AB1001_1791795031.jsonl",
        "0016C001F0AB1002_1791795032.jsonl",
    }
    assert by_name["0016C001F0AB1001_1791795031.jsonl"]["device_id"] == first["id"]
    assert by_name["0016C001F0AB1001_1791795031.jsonl"]["device_name"] == first["name"]
    assert by_name["0016C001F0AB1002_1791795032.jsonl"]["device_id"] == second["id"]
    assert by_name["0016C001F0AB1002_1791795032.jsonl"]["device_name"] == second["name"]
    assert all(f["acquisition_channel"] == "lp0" for f in result["files"])
    assert result["skipped"] == [
        {
            "name": "0016C001F0AB1999_1791795033.jsonl",
            "reason": "no offload station of this project has EUI 0016C001F0AB1999",
        }
    ]

    # a lone file finds its station too, and the same file twice is skipped
    again = await client.post(
        f"/api/v1/projects/{project_id}/offload-files",
        files={
            "file": ("0016C001F0AB1001_1791795031.jsonl", (frame + "\n").encode(), "text/plain")
        },
        headers=h,
    )
    assert again.status_code == 422 and "uploaded before" in again.text
    lone = await client.post(
        f"/api/v1/projects/{project_id}/offload-files",
        files={
            "file": (
                "0016C001F0AB1002_1791795040.jsonl",
                (
                    line(build_uplink(KEYS_A, 4, 29, RECORDS), station="0016C001F0AB1002") + "\n"
                ).encode(),
                "text/plain",
            )
        },
        headers=h,
    )
    assert lone.status_code == 201, lone.text
    assert lone.json()["files"][0]["device_id"] == second["id"]

    # a station of another project is not this project's
    elsewhere = await create_project(db)
    stranger = await _device(client, h, oc["id"], elsewhere.id, serial="0016C001F0AB1003")
    strange = await client.post(
        f"/api/v1/projects/{project_id}/offload-files",
        files={
            "file": (
                "0016C001F0AB1003_1791795050.jsonl",
                (
                    line(build_uplink(KEYS_A, 5, 29, RECORDS), station="0016C001F0AB1003") + "\n"
                ).encode(),
                "text/plain",
            )
        },
        headers=h,
    )
    assert strange.status_code == 422 and "0016C001F0AB1003" in strange.text
    assert stranger["id"] not in strange.text


async def test_a_device_becomes_a_station_from_the_offload_page(client, db):
    """The Offload page's setup (Tim, 2026-10-16): one call gives a device of the project its
    Offload station entity, its place and its gateway row, so the page lists the station before
    its first card; a second call changes nothing that is set; an operator may not make it; a
    device whose DevEUI is not known is refused by name, since the card's files carry it."""
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    oc = await _opencollar_type(client, h)
    eui = "0016C001F0" + uuid.uuid4().hex[:6].upper()
    station = await _device(client, h, oc["id"], project.id, serial=eui)
    nameless = await _device(client, h, oc["id"], project.id)
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    url = f"/api/v1/projects/{project.id}/offload/stations"

    refused = await client.post(url, json={"device_id": station["id"]}, headers=operator.headers)
    assert refused.status_code == 403, refused.text

    response = await client.post(
        url,
        json={"device_id": station["id"], "latitude": -17.9, "longitude": 25.8},
        headers=h,
    )
    assert response.status_code == 201, response.text
    made = response.json()
    assert made["station_eui"] == eui
    assert made["entity_created"] and not made["entity_kept"]
    assert made["placed"] and made["gateway_created"]
    assert made["entity_name"] == station["name"]

    await db.rollback()  # the API committed in another session
    type_key = await db.scalar(
        select(EntityType.key)
        .join(Entity, Entity.entity_type_id == EntityType.id)
        .where(Entity.id == uuid.UUID(made["entity_id"]))
    )
    assert type_key == "offload_station"
    gateway = await db.scalar(
        select(Gateway).where(
            Gateway.data_source_id == LP0_SOURCE_ID, Gateway.external_id == eui.lower()
        )
    )
    assert gateway is not None
    assert gateway.device_id == uuid.UUID(station["id"])
    assert gateway.name == station["name"]
    assert gateway.attributes["kind"] == "offload_station"
    assert gateway.last_seen_at is None  # nothing was received yet, and the row says so

    device = (await client.get(f"/api/v1/devices/{station['id']}", headers=h)).json()
    assert device["entity_id"] == made["entity_id"]
    assert device["static_position"]["coordinates"] == [25.8, -17.9]

    page = (await client.get(f"/api/v1/projects/{project.id}/offload", headers=h)).json()
    rows = {s["device_id"]: s for s in page["stations"]}
    assert station["id"] in rows, "a station without a card is listed by its entity"
    row = rows[station["id"]]
    assert row["files"] == 0 and row["receptions"] == 0
    assert row["has_location"] is True
    assert row["location"]["coordinates"] == [25.8, -17.9]  # the Offload page's map
    assert row["gateway_id"] == str(gateway.id)
    assert row["entity_name"] == station["name"]
    assert all(t["device_id"] != station["id"] for t in page["trackers"])

    again = (await client.post(url, json={"device_id": station["id"]}, headers=h)).json()
    assert again["entity_id"] == made["entity_id"]
    assert again["entity_kept"] and not again["entity_created"]
    assert not again["placed"] and not again["gateway_created"]

    refused = await client.post(url, json={"device_id": nameless["id"]}, headers=h)
    assert refused.status_code == 409, refused.text
    assert "DevEUI" in refused.json()["detail"]


def v5(eui: str, *, session: int = 1, window: int = 1, slot: int = 0, version: int = 5) -> dict:
    """The `lp0` object a v5 station writes beside `rxpk`."""
    return {
        "version": version,
        "source_eui": eui,
        "session": session,
        "window": window,
        "slot": slot,
    }


async def test_a_v5_card_is_read_per_device_and_contradictions_are_refused(client, db, bus):
    """LP0 v5 (decision D327): one station file with the frames of two trackers under their own
    keys, written out of order, a repeat, a counter wrapping from 65535 to 0, an address nobody
    set yet named by its EUI, a frame whose station-given EUI contradicts the address, a frame
    under the wrong keys, a line of a metadata version Protect does not read, two unreadable
    lines; then the same file again under another name, which adds nothing."""
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    project_id = project.id
    oc = await _opencollar_type(client, h)
    station_eui = "0016C001F0" + uuid.uuid4().hex[:6].upper()
    station = await _device(client, h, oc["id"], project_id, serial=station_eui)
    eui_a = "0016C001F1" + uuid.uuid4().hex[:6].upper()
    eui_b = "0016C001F2" + uuid.uuid4().hex[:6].upper()
    eui_c = "0016C001F3" + uuid.uuid4().hex[:6].upper()
    tracker_a = await _device(client, h, oc["id"], project_id, serial=eui_a)
    tracker_b = await _device(client, h, oc["id"], project_id, serial=eui_b)
    addr_a = "27A" + uuid.uuid4().hex[:5].upper()
    addr_b = "27B" + uuid.uuid4().hex[:5].upper()
    addr_c = "27C" + uuid.uuid4().hex[:5].upper()
    keys_a = Keys(addr_a, APP_S_KEY, NWK_S_KEY)
    keys_b = Keys(addr_b, bytes(range(16, 32)), bytes(range(32, 48)))
    keys_c = Keys(addr_c, bytes(range(48, 64)), bytes(range(64, 80)))
    wrong_a = Keys(addr_a, bytes(range(1, 17)), bytes(range(2, 18)))
    for tracker, keys in ((tracker_a, keys_a), (tracker_b, keys_b)):
        put = await client.put(
            f"/api/v1/devices/{tracker['id']}/lp0-credentials",
            json={
                "dev_addr": keys.dev_addr,
                "app_s_key": keys.app_s_key.hex(),
                "nwk_s_key": keys.nwk_s_key.hex(),
            },
            headers=h,
        )
        assert put.status_code == 200, put.text

    a_high = build_uplink(keys_a, 0xFFFF, 29, RECORDS)  # the counter's last value
    a_low = build_uplink(keys_a, 0, 29, RECORDS)  # the next frame, after the wrap
    b_one = build_uplink(keys_b, 7, 29, RECORDS)
    c_one = build_uplink(keys_c, 3, 29, RECORDS)  # an address nobody set
    a_claimed_b = build_uplink(keys_a, 9, 29, RECORDS)  # A's frame, the station names B
    a_wrong = build_uplink(wrong_a, 11, 29, RECORDS)  # A's address, other keys
    a_future = build_uplink(keys_a, 12, 29, RECORDS)  # a metadata version Protect has not read
    text = (
        "\n".join(
            [
                "",
                line(
                    b_one,
                    time="2026-10-12T09:00:00Z",
                    lp0=v5(eui_b, session=2),
                    station=station_eui,
                ),
                line(
                    a_low, time="2026-10-12T08:50:41Z", lp0=v5(eui_a, slot=1), station=station_eui
                ),
                line(a_high, time="2026-10-12T08:50:31Z", lp0=v5(eui_a), station=station_eui),
                line(a_high, time="2026-10-12T08:50:32Z", lp0=v5(eui_a), station=station_eui),
                line(
                    c_one,
                    time="2026-10-12T08:52:00Z",
                    lp0=v5(eui_c, session=3),
                    station=station_eui,
                ),
                line(
                    a_claimed_b,
                    time="2026-10-12T08:53:00Z",
                    lp0=v5(eui_b, session=4),
                    station=station_eui,
                ),
                line(
                    a_wrong,
                    time="2026-10-12T08:54:00Z",
                    lp0=v5(eui_a, session=5),
                    station=station_eui,
                ),
                line(
                    a_future,
                    time="2026-10-12T08:55:00Z",
                    lp0=v5(eui_a, version=6),
                    station=station_eui,
                ),
                "not json at all",
                json.dumps({"gatewayEui": station_eui, "rxpk": {"data": "QA=="}}),
            ]
        )
        + "\n"
    )
    name = f"{station_eui}_1791795031.jsonl"
    upload = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": (name, text.encode(), "text/plain")},
        headers=h,
    )
    assert upload.status_code == 201, upload.text
    row_id = upload.json()["files"][0]["id"]
    await _decode(bus, row_id)
    await db.rollback()
    row = (await client.get(f"/api/v1/log-files/{row_id}", headers=h)).json()
    assert row["status"] == "complete", row
    # ten lines: eight frames and two unreadable; five frames failed (the two unreadable, the
    # contradiction, the wrong keys, the unread version)
    assert (row["frames_total"], row["frames_failed"]) == (10, 5)
    assert (
        row["attributes"]["errors"]
        == {
            "DEVICE_IDENTITY_AMBIGUOUS": 1,
            "PAYLOAD_DECODE_FAILED": 2,
            "FILE_PARSE_FAILED": 2,
        }
        or row["attributes"]["errors"].get("DEVICE_IDENTITY_AMBIGUOUS") == 1
    )
    assert row["attributes"]["frames_repeated"] == 1 and row["attributes"]["frames_retained"] == 1

    events = (
        await db.scalars(
            select(SourceEvent)
            .where(
                SourceEvent.data_source_id == LP0_SOURCE_ID,
                SourceEvent.external_id.in_([addr_a, addr_b, addr_c]),
            )
            .order_by(SourceEvent.id)
        )
    ).all()
    assert len(events) == 8
    by_line = {int(e.provider_metadata["line"]): e for e in events}
    # B first in the file, A's frames after it: the order in the file changes nothing
    assert (
        by_line[2].processing_status == "processed" and str(by_line[2].device_id) == tracker_b["id"]
    )
    assert by_line[2].provider_metadata["lp0_version"] == 5
    assert by_line[2].provider_metadata["source_eui"] == eui_b
    assert (
        by_line[2].provider_metadata["lp0_session"],
        by_line[2].provider_metadata["lp0_window"],
    ) == (2, 1)
    # the wrap: the frame at 0 (earlier in the file) and the frame at 65535 both verify as the
    # firmware signed them (the upper half zero); they carried the same record stream, so the
    # second decoded to records already known and the canonical key kept one set of fixes;
    # the reception times are kept as the station wrote them
    high, low = by_line[4], by_line[3]
    assert low.processing_status == "processed" and low.provider_metadata["f_cnt32"] == 0
    assert high.provider_metadata["mic_ok"] is True
    assert high.provider_metadata["f_cnt32"] == 0xFFFF
    assert high.processing_status == "duplicate" and "duplicate_of" not in high.provider_metadata
    assert high.network_received_at.isoformat().startswith("2026-10-12T08:50:31")
    assert low.network_received_at.isoformat().startswith("2026-10-12T08:50:41")
    # the station saved 65535 again: a repeat of the frame itself, never decoded twice
    assert by_line[5].processing_status == "duplicate"
    assert by_line[5].provider_metadata["duplicate_of"] == high.id
    # the address nobody set waits, named by the EUI the station learnt
    assert by_line[6].processing_status == "unassigned" and by_line[6].device_id is None
    waiting = await db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == LP0_SOURCE_ID, ExternalIdentity.external_id == addr_c
        )
    )
    assert waiting is not None and waiting.attributes["name"] == eui_c
    # the station says B, the address says A: nobody gets the records
    contradiction = by_line[7]
    assert contradiction.processing_status == "failed"
    assert contradiction.error_code == "DEVICE_IDENTITY_AMBIGUOUS"
    assert "frame_hex" not in contradiction.provider_metadata
    assert (
        by_line[8].processing_status == "failed"
        and by_line[8].error_code == "PAYLOAD_DECODE_FAILED"
    )
    assert (
        by_line[9].processing_status == "failed"
        and by_line[9].error_code == "PAYLOAD_DECODE_FAILED"
    )
    # the wording ('version 6 is not one this version reads') is the unit test's
    assert APP_S_KEY.hex() not in json.dumps(row) and APP_S_KEY.hex().upper() not in json.dumps(row)

    # the records: A's two frames carried the same stream, so one set of fixes; B its own
    positions_a = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tracker_a["id"])))
    ).all()
    positions_b = (
        await db.scalars(select(Position).where(Position.device_id == uuid.UUID(tracker_b["id"])))
    ).all()
    assert (len(positions_a), len(positions_b)) == (3, 3)
    assert (row["records_new"], row["records_duplicate"]) == (6, 3)

    # the same file again, under its name or another: refused by its content
    for again_name in (name, f"{station_eui}_1791795031_001.jsonl"):
        again = await client.post(
            f"/api/v1/devices/{station['id']}/offload-files",
            files={"file": (again_name, text.encode(), "text/plain")},
            headers=h,
        )
        assert again.status_code == 422 and "uploaded before" in again.text
    # the same frames in a later file, as a station writes them after a lost receipt (other
    # reception times, so other content): every frame a repeat, nothing decoded again
    later = (
        "\n".join(
            [
                "",
                line(
                    b_one,
                    time="2026-10-12T09:30:00Z",
                    lp0=v5(eui_b, session=6),
                    station=station_eui,
                ),
                line(
                    a_low,
                    time="2026-10-12T09:30:10Z",
                    lp0=v5(eui_a, session=7),
                    station=station_eui,
                ),
                line(
                    a_high,
                    time="2026-10-12T09:30:20Z",
                    lp0=v5(eui_a, session=7),
                    station=station_eui,
                ),
            ]
        )
        + "\n"
    )
    later_name = f"{station_eui}_1791797400.jsonl"
    accepted = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": (later_name, later.encode(), "text/plain")},
        headers=h,
    )
    assert accepted.status_code == 201, accepted.text
    later_id = accepted.json()["files"][0]["id"]
    await _decode(bus, later_id)
    await db.rollback()
    second = (await client.get(f"/api/v1/log-files/{later_id}", headers=h)).json()
    assert second["status"] == "complete"
    assert (second["frames_total"], second["records_new"]) == (3, 0)
    assert second["attributes"]["frames_repeated"] == 3
    assert (
        len(
            (
                await db.scalars(
                    select(Position).where(Position.device_id == uuid.UUID(tracker_a["id"]))
                )
            ).all()
        )
        == 3
    )


async def test_a_cards_history_moves_a_new_devices_assignments_back(client, db, bus):
    """Decision D330 (Tim, 2026-10-16: after a card decoded he had to move the attribution
    window back by hand). A tracker made today, with one project assignment and one entity
    assignment, gets both moved back to the earliest record its card brought, with the
    attribution job queued; a tracker that had an earlier membership is left alone."""
    from datetime import UTC, datetime

    from shared.models import AttributionJob, DeviceEntityAssignment, DeviceProjectAssignment

    admin = await actor(client, db, superuser=True)
    h = admin.headers
    project = await create_project(db)
    project_id = project.id
    oc = await _opencollar_type(client, h)
    station_eui = "0016C001F0" + uuid.uuid4().hex[:6].upper()
    station = await _device(client, h, oc["id"], project_id, serial=station_eui)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    fresh = await _device(client, h, oc["id"], project_id, valid_from=now)  # made today
    veteran = await _device(client, h, oc["id"], project_id, valid_from=now)
    # the veteran had an earlier life: a membership that ended
    await client.post(
        f"/api/v1/devices/{veteran['id']}/project-assignments",
        json={
            "project_id": str(project_id),
            "valid_from": "2020-01-01T00:00:00+00:00",
            "valid_to": "2020-06-01T00:00:00+00:00",
        },
        headers=h,
    )
    hippo_type = next(
        t
        for t in (
            await client.get("/api/v1/entity-types", params={"limit": 500}, headers=h)
        ).json()["items"]
        if t["key"] in ("hippo", "wildlife")
    )
    assigned = await client.post(
        f"/api/v1/projects/{project_id}/entity-assignments",
        json={
            "device_id": fresh["id"],
            "valid_from": now,
            "new_entity": {"name": unique_name("Hippo"), "entity_type_id": hippo_type["id"]},
        },
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    addr_fresh = "28A" + uuid.uuid4().hex[:5].upper()
    addr_veteran = "28B" + uuid.uuid4().hex[:5].upper()
    keys_fresh = Keys(addr_fresh, APP_S_KEY, NWK_S_KEY)
    keys_veteran = Keys(addr_veteran, bytes(range(16, 32)), bytes(range(32, 48)))
    for device, keys in ((fresh, keys_fresh), (veteran, keys_veteran)):
        put = await client.put(
            f"/api/v1/devices/{device['id']}/lp0-credentials",
            json={
                "dev_addr": keys.dev_addr,
                "app_s_key": keys.app_s_key.hex(),
                "nwk_s_key": keys.nwk_s_key.hex(),
            },
            headers=h,
        )
        assert put.status_code == 200, put.text
    text = (
        "\n".join(
            [
                "",
                line(
                    build_uplink(keys_fresh, 1, 29, RECORDS),
                    lp0=v5("0016C001F1000001"),
                    station=station_eui,
                ),
                line(
                    build_uplink(keys_veteran, 1, 29, RECORDS),
                    lp0=v5("0016C001F1000002"),
                    station=station_eui,
                ),
            ]
        )
        + "\n"
    )
    upload = await client.post(
        f"/api/v1/devices/{station['id']}/offload-files",
        files={"file": (f"{station_eui}_1791795031.jsonl", text.encode(), "text/plain")},
        headers=h,
    )
    assert upload.status_code == 201, upload.text
    row_id = upload.json()["files"][0]["id"]
    await _decode(bus, row_id)
    await db.rollback()

    fresh_id = uuid.UUID(fresh["id"])
    earliest = await db.scalar(
        select(Position.time).where(Position.device_id == fresh_id).order_by(Position.time).limit(1)
    )
    assert earliest is not None and earliest.year < 2027
    membership = await db.scalar(
        select(DeviceProjectAssignment).where(DeviceProjectAssignment.device_id == fresh_id)
    )
    assert membership.validity.lower == earliest, "the only membership starts at the first record"
    tracking = await db.scalar(
        select(DeviceEntityAssignment).where(DeviceEntityAssignment.device_id == fresh_id)
    )
    assert tracking.validity.lower == earliest, "and so does the only entity assignment"
    jobs = (
        await db.scalars(select(AttributionJob).where(AttributionJob.device_id == fresh_id))
    ).all()
    assert jobs and all(j.time_from == earliest for j in jobs)
    # the file's row says what moved
    row = (await client.get(f"/api/v1/log-files/{row_id}", headers=h)).json()
    moved = row["attributes"]["attribution_extended"]
    assert sorted(m["kind"] for m in moved if m["device_id"] == fresh["id"]) == [
        "entity",
        "project",
    ]
    assert all(m["to"] == earliest.isoformat() for m in moved)
    # the veteran's current membership keeps its start: an earlier life means a gap on purpose
    veteran_id = uuid.UUID(veteran["id"])
    current = await db.scalar(
        select(DeviceProjectAssignment)
        .where(DeviceProjectAssignment.device_id == veteran_id)
        .order_by(DeviceProjectAssignment.validity.desc())
        .limit(1)
    )
    assert current.validity.lower.isoformat() == now
    assert all(m["device_id"] != veteran["id"] for m in moved)
