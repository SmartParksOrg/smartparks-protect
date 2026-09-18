"""The battery type per device (decision D248) and the environmental data providers a server
admin sets up (decision D250)."""

import uuid

import pytest

from shared.models import DeviceType
from tests.api.test_network_and_map import _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_the_battery_type_is_set_per_device_and_falls_back(client, db, bus):  # noqa: F811
    admin, _project, _entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    base = f"/api/v1/devices/{device['id']}/battery"

    read = (await client.get(base, headers=h)).json()
    # the generic JSON driver says nothing about batteries, so nothing is assumed
    assert read["battery_type"] is None and read["source"] == "none"
    assert {t["key"] for t in read["types"]} >= {"primary_lithium", "lithium_ion"}

    # the device type's default reaches the devices of its family
    device_type = await db.get(DeviceType, uuid.UUID(device["device_type_id"]))
    device_type.default_settings = {"battery_type": "primary_lithium"}
    await db.commit()
    read = (await client.get(base, headers=h)).json()
    assert read["battery_type"] == "primary_lithium" and read["source"] == "device_type"

    # this one device carries a rechargeable cell
    saved = await client.put(base, json={"battery_type": "lithium_ion"}, headers=h)
    assert saved.status_code == 200, saved.text
    assert saved.json()["battery_type"] == "lithium_ion"
    assert saved.json()["source"] == "device"
    assert saved.json()["default_battery_type"] == "primary_lithium"

    # a type nobody knows is refused, not stored
    assert (await client.put(base, json={"battery_type": "nuclear"}, headers=h)).status_code == 422
    assert (await client.get(base, headers=h)).json()["battery_type"] == "lithium_ion"

    # cleared, the device follows its type again
    cleared = await client.put(base, json={"battery_type": None}, headers=h)
    assert cleared.json()["battery_type"] == "primary_lithium"
    assert cleared.json()["source"] == "device_type"


async def test_a_viewer_may_not_set_the_battery_type(client, db, bus):  # noqa: F811
    from shared.enums import Role
    from tests.api.conftest import actor, add_member

    _admin, project, _entity, _source, device, _ = await _setup(client, db)
    viewer = await actor(client, db)
    await add_member(db, viewer.user, project, Role.PROJECT_VIEWER)
    base = f"/api/v1/devices/{device['id']}/battery"
    assert (await client.get(base, headers=viewer.headers)).status_code == 200
    refused = await client.put(base, json={"battery_type": "lithium_ion"}, headers=viewer.headers)
    assert refused.status_code == 403


async def test_the_environmental_provider_is_set_up_by_a_server_admin(client, db):
    """Decision D250: the account lives in the database, the secret never comes back, and an
    omitted secret keeps the stored one."""
    from tests.api.conftest import actor

    admin = await actor(client, db, superuser=True)
    h = admin.headers
    listed = (await client.get("/api/v1/admin/environment/providers", headers=h)).json()
    assert [p["key"] for p in listed] == ["copernicus"]
    assert listed[0]["secret_set"] is False

    saved = await client.put(
        "/api/v1/admin/environment/providers/copernicus",
        json={"client_id": "  sh-123  ", "client_secret": "s3cret"},
        headers=h,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["client_id"] == "sh-123" and body["secret_set"] is True
    assert body["configured"] is True
    assert "s3cret" not in saved.text, "the secret never leaves the server"

    # saving the client id alone keeps the secret
    again = await client.put(
        "/api/v1/admin/environment/providers/copernicus",
        json={"client_id": "sh-456"},
        headers=h,
    )
    assert again.json()["client_id"] == "sh-456"
    assert again.json()["secret_set"] is True

    # the provider is built from the stored account
    from shared.analysis.environment import stored_providers

    await db.rollback()  # the endpoint committed in its own session
    providers = await stored_providers(db)
    assert [p.key for p in providers] == ["copernicus_openeo"]
    assert providers[0].client_secret == "s3cret"

    # switched off, nothing is built
    await client.put(
        "/api/v1/admin/environment/providers/copernicus",
        json={"enabled": False},
        headers=h,
    )
    await db.rollback()
    assert await stored_providers(db) == []

    # a plain member may not look at it at all
    member = await actor(client, db)
    assert (
        await client.get("/api/v1/admin/environment/providers", headers=member.headers)
    ).status_code == 403


async def test_the_device_bluetooth_address_is_set_and_cleared(client, db, bus):  # noqa: F811
    """Decision D252: a contact names three octets, so the device's own address has to be known
    before a sighting of it can be recognised as it."""
    from shared.enums import Role
    from tests.api.conftest import actor, add_member

    admin, project, _entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    base = f"/api/v1/devices/{device['id']}/ble-address"

    assert (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()[
        "ble_mac"
    ] is None
    saved = await client.put(base, json={"ble_mac": "D4:22:11:0A:41:0C"}, headers=h)
    assert saved.status_code == 200, saved.text
    assert saved.json()["ble_mac"] == "d4:22:11:0a:41:0c", "kept lowercase, as a scan reports it"

    # a string that is not an address is refused rather than stored and never matched
    for bad in ("d4:22:11:0a:41", "not-an-address", "d4-22-11-0a-41-0c"):
        assert (await client.put(base, json={"ble_mac": bad}, headers=h)).status_code == 422

    viewer = await actor(client, db)
    await add_member(db, viewer.user, project, Role.PROJECT_VIEWER)
    refused = await client.put(base, json={"ble_mac": "d4:22:11:0a:41:0c"}, headers=viewer.headers)
    assert refused.status_code == 403

    cleared = await client.put(base, json={"ble_mac": None}, headers=h)
    assert cleared.json()["ble_mac"] is None
