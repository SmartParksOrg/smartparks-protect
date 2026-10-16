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
