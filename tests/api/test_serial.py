"""The serial of an OpenCollar is its DevEUI (decision D101): the first LoRaWAN identity fills
an empty serial, wherever the identity comes from; other drivers keep the field as entered."""

import uuid

import pytest

from tests.api.conftest import actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _type(client, headers, driver_key):
    return (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name(driver_key).replace("-", "_"),
                "label": driver_key,
                "driver_key": driver_key,
            },
            headers=headers,
        )
    ).json()


async def _device(client, headers, device_type, serial=None):
    return (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("dev"),
                "status": "active",
                "serial_number": serial,
            },
            headers=headers,
        )
    ).json()


async def test_dev_eui_becomes_the_serial_of_an_opencollar(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("LoRa"), "adapter_key": "generic_http"},
            headers=h,
        )
    ).json()
    collar_type = await _type(client, h, "opencollar")
    collar = await _device(client, h, collar_type)
    dev_eui = uuid.uuid4().hex[:16]
    added = await client.post(
        f"/api/v1/devices/{collar['id']}/identities",
        json={"data_source_id": source["id"], "external_id": dev_eui},
        headers=h,
    )
    assert added.status_code == 201, added.text
    read = (await client.get(f"/api/v1/devices/{collar['id']}", headers=h)).json()
    assert read["serial_number"] == dev_eui.upper()

    # a serial entered by hand stays, and a generic device gets none from its identity
    other = await _device(client, h, collar_type, serial=unique_name("SN"))
    await client.post(
        f"/api/v1/devices/{other['id']}/identities",
        json={"data_source_id": source["id"], "external_id": uuid.uuid4().hex[:16]},
        headers=h,
    )
    assert (await client.get(f"/api/v1/devices/{other['id']}", headers=h)).json()[
        "serial_number"
    ] == other["serial_number"]
    generic = await _device(client, h, await _type(client, h, "generic_json"))
    await client.post(
        f"/api/v1/devices/{generic['id']}/identities",
        json={"data_source_id": source["id"], "external_id": uuid.uuid4().hex[:16]},
        headers=h,
    )
    assert (await client.get(f"/api/v1/devices/{generic['id']}", headers=h)).json()[
        "serial_number"
    ] is None

    # onboarding from Needs attention fills it as well
    unknown = uuid.uuid4().hex[:16].upper()
    accepted = await client.post(
        f"/api/v1/ingest/http/{source['id']}",
        json={"device_id": unknown, "time": "2026-09-06T09:00:00+00:00", "lat": 52.0, "lon": 5.1},
        headers={"Authorization": f"Bearer {source['webhook_token']}"},
    )
    assert accepted.status_code == 202
    identity = next(
        i
        for i in (await client.get("/api/v1/attention/identities?limit=500", headers=h)).json()[
            "items"
        ]
        if i["external_id"] == unknown
    )
    created = await client.post(
        "/api/v1/attention/identities/bulk-create-devices",
        json={
            "identity_ids": [identity["id"]],
            "device_type_id": collar_type["id"],
            "reprocess": False,
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    device_id = created.json()["device_ids"][0]
    assert (await client.get(f"/api/v1/devices/{device_id}", headers=h)).json()[
        "serial_number"
    ] == unknown
