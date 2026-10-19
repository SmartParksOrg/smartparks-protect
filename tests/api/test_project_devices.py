"""A device made inside a project (decision D326): a project admin creates it and it is in the
project from now, with its LP0 credentials when the hardware was read over Bluetooth; an
operator may not; a serial or an LP0 address another device holds is refused; the driver's
catalogue is served by device type for the Bluetooth read before the device exists."""

import uuid

import pytest
from sqlalchemy import select

from shared.connectivity.adapters.lp0_station import SOURCE_ID as LP0_SOURCE_ID
from shared.enums import Role
from shared.models import ExternalIdentity
from tests.api.conftest import actor, create_project, project_actor
from tests.api.test_offload_stations import _opencollar_type
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

APP_S_KEY = "2b7e151628aed2a6abf7158809cf4f3c"
NWK_S_KEY = "000102030405060708090a0b0c0d0e0f"


async def test_a_project_admin_creates_a_device_in_the_project(client, db):
    server_admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    oc = await _opencollar_type(client, server_admin.headers)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    url = f"/api/v1/projects/{project.id}/devices"
    eui = "0016c001f0" + uuid.uuid4().hex[:6]
    addr = "27" + uuid.uuid4().hex[:6].upper()
    body = {
        "device_type_id": oc["id"],
        "name": unique_name("RangerEdge"),
        "serial_number": eui,
        "firmware_version": "8.1",
        "attributes": {"hardware_type": "rangeredge"},
        "lp0": {"dev_addr": addr.lower(), "app_s_key": APP_S_KEY, "nwk_s_key": NWK_S_KEY},
    }

    refused = await client.post(url, json=body, headers=operator.headers)
    assert refused.status_code == 403, refused.text

    response = await client.post(url, json=body, headers=admin.headers)
    assert response.status_code == 201, response.text
    device = response.json()
    assert device["project_id"] == str(project.id)
    assert device["serial_number"] == eui.upper(), "an OpenCollar's serial is its DevEUI, upper"
    assert device["status"] == "active"
    assert device["attributes"] == {"hardware_type": "rangeredge"}

    credentials = (
        await client.get(f"/api/v1/devices/{device['id']}/lp0-credentials", headers=admin.headers)
    ).json()
    assert credentials["dev_addr"] == addr
    assert credentials["keys_set"] and credentials["source"] == "device"
    assert credentials["app_s_key"].lower() == APP_S_KEY  # the admin may set them, so sees them
    await db.rollback()
    identity = await db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == LP0_SOURCE_ID,
            ExternalIdentity.external_id == addr,
        )
    )
    assert identity is not None and identity.device_id == uuid.UUID(device["id"])

    # the device is in the project's lists and on the Offload page as a tracker
    page = (
        await client.get(f"/api/v1/projects/{project.id}/offload", headers=admin.headers)
    ).json()
    assert any(t["device_id"] == device["id"] and t["keys_set"] for t in page["trackers"])

    taken = await client.post(
        url, json={**body, "name": unique_name("again")}, headers=admin.headers
    )
    assert taken.status_code == 409, taken.text  # the serial is unique

    other_serial = {**body, "name": unique_name("other"), "serial_number": None}
    held = await client.post(url, json=other_serial, headers=admin.headers)
    assert held.status_code == 409, held.text
    assert device["name"] in held.json()["detail"]  # the LP0 address names its holder

    plain = await client.post(
        url,
        json={"device_type_id": oc["id"], "name": unique_name("tracker")},
        headers=admin.headers,
    )
    assert plain.status_code == 201, plain.text
    assert plain.json()["serial_number"] is None


async def test_the_driver_catalogue_is_served_by_device_type(client, db):
    server_admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    oc = await _opencollar_type(client, server_admin.headers)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    response = await client.get(
        f"/api/v1/device-types/{oc['id']}/driver-catalog", headers=viewer.headers
    )
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["driver_key"] == "opencollar"
    names = {s["name"] for s in catalog["catalog"]["settings"]}
    assert {"device_eui", "device_name", "lp0_dev_addr", "lp0_app_key", "lp0_network_key"} <= names
    generic = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=server_admin.headers,
        )
    ).json()
    empty = await client.get(
        f"/api/v1/device-types/{generic['id']}/driver-catalog", headers=viewer.headers
    )
    assert empty.status_code == 200 and empty.json()["catalog"] == {}


async def test_a_project_admin_manages_the_devices_of_the_project(client, db):
    """Decision D337 (Tim, 2026-10-19: a project admin had to be made server admin to add
    stations): a device in a project is its project admins' to manage, its name, type, location
    source and identities, while server admins keep devices outside a project, imports and the
    data sources themselves."""
    server_admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    elsewhere = await create_project(db)
    oc = await _opencollar_type(client, server_admin.headers)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    stranger = await project_actor(client, db, elsewhere, Role.PROJECT_ADMIN)
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    device = (
        await client.post(
            f"/api/v1/projects/{project.id}/devices",
            json={"device_type_id": oc["id"], "name": unique_name("RangerEdge")},
            headers=admin.headers,
        )
    ).json()

    # the sources by name, for the identity form; their settings stay with the server admin
    sources = await client.get(
        f"/api/v1/projects/{project.id}/data-sources", headers=operator.headers
    )
    assert sources.status_code == 200, sources.text
    assert sources.json()
    assert all(set(s) == {"id", "name", "adapter_key", "enabled"} for s in sources.json())
    assert (await client.get("/api/v1/data-sources", headers=admin.headers)).status_code == 403

    renamed = await client.patch(
        f"/api/v1/devices/{device['id']}",
        json={"name": device["name"] + " north", "location_source": "network"},
        headers=admin.headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["location_source"] == "network"
    for who in (operator, stranger):
        refused = await client.patch(
            f"/api/v1/devices/{device['id']}", json={"name": "x"}, headers=who.headers
        )
        assert refused.status_code == 403, refused.text

    eui = "0016C001F0" + uuid.uuid4().hex[:6].upper()
    linked = await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": str(LP0_SOURCE_ID), "external_id": eui},
        headers=admin.headers,
    )
    assert linked.status_code == 201, linked.text
    refused = await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": str(LP0_SOURCE_ID), "external_id": eui + "1"},
        headers=stranger.headers,
    )
    assert refused.status_code == 403
    cleared = await client.delete(f"/api/v1/devices/{device['id']}/picture", headers=admin.headers)
    assert cleared.status_code == 200, cleared.text

    # a device in no project is the server admin's alone
    loose = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": oc["id"], "name": unique_name("loose"), "status": "active"},
            headers=server_admin.headers,
        )
    ).json()
    refused = await client.patch(
        f"/api/v1/devices/{loose['id']}", json={"name": "y"}, headers=admin.headers
    )
    assert refused.status_code == 403


async def test_a_device_is_made_with_its_address_alone_and_the_keys_follow(client, db):
    """Decision D338: the Offload page's "Add the tracker" makes the device with the LP0
    address a card named and no keys; the address is the device's identity from then, the
    keys follow on the device page, and the same address is refused to a second device."""
    server_admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    oc = await _opencollar_type(client, server_admin.headers)
    admin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    addr = "27" + uuid.uuid4().hex[:6].upper()
    url = f"/api/v1/projects/{project.id}/devices"
    half = await client.post(
        url,
        json={
            "device_type_id": oc["id"],
            "name": unique_name("found"),
            "lp0": {"dev_addr": addr, "app_s_key": APP_S_KEY},
        },
        headers=admin.headers,
    )
    assert half.status_code == 422, "both keys or neither"
    made = await client.post(
        url,
        json={
            "device_type_id": oc["id"],
            "name": unique_name("found"),
            "lp0": {"dev_addr": addr, "source": "person"},
        },
        headers=admin.headers,
    )
    assert made.status_code == 201, made.text
    device = made.json()
    read = (
        await client.get(f"/api/v1/devices/{device['id']}/lp0-credentials", headers=admin.headers)
    ).json()
    assert read["dev_addr"] == addr and read["keys_set"] is False
    assert read["frames_waiting"] == 0
    page = (
        await client.get(f"/api/v1/projects/{project.id}/offload", headers=admin.headers)
    ).json()
    row = next(t for t in page["trackers"] if t["device_id"] == device["id"])
    assert row["dev_addr"] == addr and row["keys_set"] is False
    again = await client.post(
        url,
        json={
            "device_type_id": oc["id"],
            "name": unique_name("twin"),
            "lp0": {"dev_addr": addr, "source": "person"},
        },
        headers=admin.headers,
    )
    assert again.status_code == 409 and device["name"] in again.text
    keys = await client.put(
        f"/api/v1/devices/{device['id']}/lp0-credentials",
        json={"dev_addr": addr, "app_s_key": APP_S_KEY, "nwk_s_key": NWK_S_KEY},
        headers=admin.headers,
    )
    assert keys.status_code == 200, keys.text
    assert keys.json()["keys_set"] is True and keys.json()["queued"] == 0
