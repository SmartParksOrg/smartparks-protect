"""The settings Protect knows per OpenCollar device through the API (decisions D228 to D231):
the catalogue with the known values, a person's recorded value, and the interval resolution
reading the known settings first."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from shared.bus import RedisStreamsBus
from shared.domain.device_settings import record_setting
from shared.models import DeviceSetting
from tests.api.conftest import actor, create_project
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def bus():
    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _opencollar_device(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
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
    return admin, project, device


async def test_the_catalogue_shows_what_is_known_and_a_person_records_a_value(client, db):
    admin, _project, device = await _opencollar_device(client, db)
    h = admin.headers
    device_id = uuid.UUID(device["id"])
    listed = (await client.get(f"/api/v1/devices/{device['id']}/settings", headers=h)).json()
    assert listed["driver_key"] == "opencollar" and listed["firmware"] == "7.3.0"
    assert listed["known"] == 0 and len(listed["items"]) >= 120
    interval = next(i for i in listed["items"] if i["key"] == "ublox_send_interval")
    assert (
        interval["value"] is None
        and interval["default"] == 0
        and interval["group"] == "u-blox GNSS"
    )

    # the collar reported a frame (as the decoder records it), a command was sent for another
    await record_setting(
        db,
        device_id,
        "status_send_interval",
        1800,
        source="frame",
        observed_at=datetime(2026, 5, 1, tzinfo=UTC),
        setting_id=3,
        raw_hex="08070000",
    )
    await record_setting(
        db,
        device_id,
        "ublox_send_interval",
        600,
        source="command",
        observed_at=datetime(2026, 5, 2, tzinfo=UTC),
        setting_id=2,
        status="sent",
    )
    await db.commit()
    listed = (await client.get(f"/api/v1/devices/{device['id']}/settings", headers=h)).json()
    by_key = {i["key"]: i for i in listed["items"]}
    assert listed["known"] == 2
    assert (
        by_key["status_send_interval"]["value"] == 1800
        and by_key["status_send_interval"]["source"] == "frame"
    )
    assert (
        by_key["ublox_send_interval"]["status"] == "sent"
        and by_key["ublox_send_interval"]["source"] == "command"
    )
    # an older frame does not replace a newer value; a frame confirms a sent command
    await record_setting(
        db,
        device_id,
        "status_send_interval",
        3600,
        source="frame",
        observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        setting_id=3,
    )
    row = await record_setting(
        db,
        device_id,
        "ublox_send_interval",
        600,
        source="frame",
        observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        setting_id=2,
    )
    await db.commit()
    kept = await db.get(DeviceSetting, (device_id, "status_send_interval"))
    assert kept.value == 1800 and row is not None and row.status == "observed"

    # a person records a value Protect cannot observe; the range holds
    recorded = await client.put(
        f"/api/v1/devices/{device['id']}/settings/lr_gps_interval", json={"value": 900}, headers=h
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["value"] == 900 and recorded.json()["source"] == "manual"
    assert (
        await client.put(
            f"/api/v1/devices/{device['id']}/settings/lr_gps_interval",
            json={"value": 10**9},
            headers=h,
        )
    ).status_code == 422
    assert (
        await client.put(
            f"/api/v1/devices/{device['id']}/settings/no_such", json={"value": 1}, headers=h
        )
    ).status_code == 404

    # the expected interval reads the known settings: the person's word on the LoRa GPS
    # interval comes before the command's u-blox interval and the type's defaults
    reporting = (await client.get(f"/api/v1/devices/{device['id']}/reporting", headers=h)).json()
    assert reporting["declared_fix_s"] == 900 and reporting["declared_source"] == "manual"
    assert reporting["expected_status_s"] == 1800 and reporting["status_source"] == "settings_frame"


async def test_a_bluetooth_settings_read_fills_the_known_settings(client, db, bus):
    """Decision D229: the frames a browser read over Web Bluetooth are synced as a log file of
    channel webble; the decoder turns the settings frame into known values marked as read over
    Bluetooth."""
    from tests.api.test_log_files_api import _decode

    admin, _project, device = await _opencollar_device(client, db)
    h = admin.headers
    # port 3, then the TLVs: ublox_send_interval 3600 s, status_send_interval 1800 s, data_log on
    frame = "03" + "0204100e0000" + "030408070000" + "0b0101"
    sync = await client.post(
        f"/api/v1/devices/{device['id']}/log-files/ble-sync",
        json={"frames": [frame], "label": "settings"},
        headers=h,
    )
    assert sync.status_code == 201, sync.text
    await _decode(bus, sync.json()["id"])
    listed = (await client.get(f"/api/v1/devices/{device['id']}/settings", headers=h)).json()
    by_key = {i["key"]: i for i in listed["items"]}
    assert listed["known"] == 3
    assert (
        by_key["ublox_send_interval"]["value"] == 3600
        and by_key["ublox_send_interval"]["source"] == "ble"
    )
    assert by_key["status_send_interval"]["value"] == 1800 and by_key["data_log"]["value"] is True
    assert by_key["ublox_send_interval"]["status"] == "observed"
    # the device page's expectation follows: the collar's own settings say five minutes... an hour
    reporting = (await client.get(f"/api/v1/devices/{device['id']}/reporting", headers=h)).json()
    assert reporting["declared_fix_s"] == 3600 and reporting["declared_source"] == "settings_frame"
