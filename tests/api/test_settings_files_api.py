"""Settings files per device through the API (decisions D426 to D429): a file of the
ble-settings-app uploaded and downloaded as it was, the credentials kept from a reader, the
snapshot of a Bluetooth read, and who may do what."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.device_drivers.opencollar import OpenCollarDriver
from shared.domain.device_settings import record_setting
from shared.enums import Role
from shared.models import DataSource, DeviceSetting, DeviceSettingsFile, ExternalIdentity
from tests.api.conftest import actor, project_actor
from tests.api.test_device_settings_api import _opencollar_device
from tests.conftest import unique_name
from tests.shared.test_opencollar_settings_file import APP_FILE

pytestmark = pytest.mark.asyncio


def _url(device: dict, tail: str = "") -> str:
    return f"/api/v1/devices/{device['id']}/settings-files{tail}"


async def _identity(db, device: dict, eui: str) -> None:
    source = DataSource(name=unique_name("cs"), adapter_key="chirpstack", config={})
    db.add(source)
    await db.flush()
    db.add(
        ExternalIdentity(
            data_source_id=source.id, external_id=eui, device_id=uuid.UUID(device["id"])
        )
    )
    await db.commit()


async def test_a_file_of_the_app_is_kept_and_comes_back_as_it_was(client, db):
    admin, _project, device = await _opencollar_device(client, db)
    h = admin.headers
    device_id = uuid.UUID(device["id"])
    await _identity(db, device, "0016c001f016d24a")
    # a frame newer than the export, and one older
    exported = datetime.now(UTC) - timedelta(hours=2)
    await record_setting(
        db,
        device_id,
        "ublox_send_interval",
        300,
        source="frame",
        observed_at=exported + timedelta(hours=1),
    )
    await record_setting(
        db,
        device_id,
        "status_send_interval",
        60,
        source="frame",
        observed_at=exported - timedelta(hours=1),
    )
    await db.commit()
    body = {
        "filename": "SP051463_20261127_101500.json",
        "document": {**APP_FILE, "no_such_setting": 1},
        "exported_at": exported.isoformat(),
    }
    stored = await client.post(_url(device), json=body, headers=h)
    assert stored.status_code == 200, stored.text
    result = stored.json()
    assert result["created"] is True and result["unknown"] == ["no_such_setting"]
    assert result["file"]["source"] == "upload" and result["file"]["has_credentials"] is True
    assert result["file"]["settings_count"] == len(APP_FILE) + 1
    assert result["recorded"] == len(APP_FILE) - 1  # all but the one a newer frame told
    db.expire_all()
    assert (await db.get(DeviceSetting, (device_id, "ublox_send_interval"))).value == 300
    status_interval = await db.get(DeviceSetting, (device_id, "status_send_interval"))
    assert status_interval.value == 3600 and status_interval.source == "file"
    assert (await db.get(DeviceSetting, (device_id, "device_pin"))).value == "01020304"

    # the same file again adds nothing
    again = (await client.post(_url(device), json=body, headers=h)).json()
    assert again["created"] is False and again["file"]["id"] == result["file"]["id"]
    listed = (await client.get(_url(device), headers=h)).json()
    assert listed["total"] == 1 and listed["can_download_credentials"] is True

    file_id = result["file"]["id"]
    whole = await client.get(_url(device, f"/{file_id}/download?credentials=true"), headers=h)
    assert whole.status_code == 200 and whole.json() == body["document"]
    assert "SP051463_20261127_101500.json" in whole.headers["content-disposition"]
    assert list(whole.json()) == list(body["document"])  # the keys in the file's order
    bare = (await client.get(_url(device, f"/{file_id}/download"), headers=h)).json()
    assert "app_key" not in bare and "device_pin" not in bare and bare["led_enabled"] is False

    # what Protect knows now, as a file the app imports: the newer frame's interval in it
    current = await client.get(_url(device, "/current/download?credentials=true"), headers=h)
    assert current.status_code == 200
    assert current.json() == {**APP_FILE, "ublox_send_interval": 300}
    assert current.headers["content-disposition"].startswith('attachment; filename="SP051463_')

    gone = await client.delete(_url(device, f"/{file_id}"), headers=h)
    assert gone.status_code == 204
    assert (await client.get(_url(device), headers=h)).json()["total"] == 0
    assert (await client.get(_url(device, f"/{file_id}/download"), headers=h)).status_code == 404


async def test_a_file_without_a_time_only_fills_in_what_protect_does_not_know(client, db):
    admin, _project, device = await _opencollar_device(client, db)
    device_id = uuid.UUID(device["id"])
    await record_setting(
        db,
        device_id,
        "ublox_send_interval",
        300,
        source="frame",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await db.commit()
    stored = await client.post(
        _url(device),
        json={
            "filename": "export.json",
            "document": {"ublox_send_interval": 900, "led_enabled": True},
        },
        headers=admin.headers,
    )
    assert stored.status_code == 200 and stored.json()["recorded"] == 1
    db.expire_all()
    assert (await db.get(DeviceSetting, (device_id, "ublox_send_interval"))).value == 300
    assert (await db.get(DeviceSetting, (device_id, "led_enabled"))).value is True


async def test_another_devices_file_and_what_is_no_settings_file_are_refused(client, db):
    admin, _project, device = await _opencollar_device(client, db)
    h = admin.headers
    await _identity(db, device, "0016C001F0000001")
    other = await client.post(
        _url(device), json={"filename": "other.json", "document": APP_FILE}, headers=h
    )
    assert other.status_code == 422 and "0016C001F016D24A" in other.json()["detail"]
    # without credentials a file names no device and is taken
    plain = {k: v for k, v in APP_FILE.items() if k != "device_eui"}
    assert (
        await client.post(_url(device), json={"filename": "p.json", "document": plain}, headers=h)
    ).status_code == 200
    nothing = await client.post(
        _url(device), json={"filename": "x.json", "document": {"name": "x"}}, headers=h
    )
    assert nothing.status_code == 422
    huge = await client.post(
        _url(device),
        json={"filename": "x.json", "document": {"ublox_send_interval": 1, "pad": "x" * 70000}},
        headers=h,
    )
    assert huge.status_code == 413


def _read(firmware: str, values: dict) -> list[dict]:
    """A read as the browser sends it: catalogue id and bytes per setting."""
    from shared.domain.reporting_rules import encode_setting_value

    catalog = {s["name"]: s for s in OpenCollarDriver.catalog(firmware)["settings"]}
    out = []
    for name, item in catalog.items():
        value = values.get(name, item["default"])
        if item["type"] in ("byte_array", "string") and name not in values:
            value = "00" * item["length"] if item["type"] == "byte_array" else ""
        out.append({"id": item["id"], "hex": encode_setting_value(item, value).hex()})
    return out


async def test_a_bluetooth_read_becomes_known_and_a_snapshot_when_it_changed(client, db):
    admin, _project, device = await _opencollar_device(client, db)
    h = admin.headers
    device_id = uuid.UUID(device["id"])
    now = datetime.now(UTC)
    # the device runs 8.0.3 by its status, the server still thinks 7.3
    body = {
        "values": _read("8.0.3", {"ublox_send_interval": 900, "device_name": "SP051463"}),
        "firmware": "8.0.3",
        "read_at": now.isoformat(),
        "complete": True,
    }
    first = await client.post(_url(device, "/snapshot"), json=body, headers=h)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["created"] is True and result["recorded"] == len(body["values"])
    assert result["file"]["source"] == "ble" and result["file"]["firmware_version"] == "8.0.3"
    assert result["file"]["filename"].startswith("SP051463_")
    db.expire_all()
    row = await db.get(DeviceSetting, (device_id, "ublox_send_interval"))
    assert row.value == 900 and row.source == "ble"
    document = (
        await client.get(
            _url(device, f"/{result['file']['id']}/download?credentials=true"), headers=h
        )
    ).json()
    assert document["ublox_send_interval"] == 900 and document["device_name"] == "SP051463"
    assert "tracker_type" not in document and isinstance(document["led_enabled"], bool)

    # a second read without a change keeps the one file
    body["read_at"] = (now + timedelta(seconds=30)).isoformat()
    second = (await client.post(_url(device, "/snapshot"), json=body, headers=h)).json()
    assert second["created"] is False and second["file"]["id"] == result["file"]["id"]
    # a changed value makes the second file
    body["values"] = _read("8.0.3", {"ublox_send_interval": 600, "device_name": "SP051463"})
    third = (await client.post(_url(device, "/snapshot"), json=body, headers=h)).json()
    assert third["created"] is True
    # a read that stopped half way is known but no snapshot
    body["values"] = _read("8.0.3", {"ublox_send_interval": 300})[:90]
    body["complete"] = False
    partial = (await client.post(_url(device, "/snapshot"), json=body, headers=h)).json()
    assert partial["file"] is None and partial["created"] is False
    files = (
        await db.scalars(
            DeviceSettingsFile.__table__.select().where(DeviceSettingsFile.device_id == device_id)
        )
    ).all()
    assert len(files) == 2


async def test_who_may_read_upload_and_download_the_credentials(client, db):
    admin, project, device = await _opencollar_device(client, db)
    stored = (
        await client.post(
            _url(device), json={"filename": "f.json", "document": APP_FILE}, headers=admin.headers
        )
    ).json()
    file_id = stored["file"]["id"]
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    stranger = await actor(client, db)
    upload = {"filename": "g.json", "document": {"ublox_send_interval": 1200}}
    snapshot = {
        "values": [],
        "read_at": datetime.now(UTC).isoformat(),
        "complete": False,
    }

    # a viewer reads the list and a file without its credentials, and nothing more
    listed = await client.get(_url(device), headers=viewer.headers)
    assert listed.status_code == 200 and listed.json()["can_download_credentials"] is False
    bare = await client.get(_url(device, f"/{file_id}/download"), headers=viewer.headers)
    assert bare.status_code == 200 and "app_key" not in bare.json()
    for path in (f"/{file_id}/download?credentials=true", "/current/download?credentials=true"):
        assert (await client.get(_url(device, path), headers=viewer.headers)).status_code == 403
    assert (
        await client.get(_url(device, "/current/download"), headers=viewer.headers)
    ).status_code == 200
    assert (await client.post(_url(device), json=upload, headers=viewer.headers)).status_code == 403
    assert (
        await client.post(_url(device, "/snapshot"), json=snapshot, headers=viewer.headers)
    ).status_code == 403
    assert (
        await client.delete(_url(device, f"/{file_id}"), headers=viewer.headers)
    ).status_code == 403

    # an operator controls devices: the whole file, an upload, a snapshot, a delete
    whole = await client.get(
        _url(device, f"/{file_id}/download?credentials=true"), headers=operator.headers
    )
    assert whole.status_code == 200 and whole.json()["app_key"] == APP_FILE["app_key"]
    assert (
        await client.post(_url(device), json=upload, headers=operator.headers)
    ).status_code == 200
    assert (
        await client.post(_url(device, "/snapshot"), json=snapshot, headers=operator.headers)
    ).status_code == 200
    assert (
        await client.delete(_url(device, f"/{file_id}"), headers=operator.headers)
    ).status_code == 204

    # someone outside the project does not see the device at all
    assert (await client.get(_url(device), headers=stranger.headers)).status_code == 404
    assert (
        await client.post(_url(device), json=upload, headers=stranger.headers)
    ).status_code == 404
