"""A device found again on the network (decision D339): a DevEUI identity links itself to the
device whose serial it is, wherever the message comes from, and a name the network gives the
device that differs from Protect's is raised on Needs attention, to rename or to keep."""

import uuid

import pytest
from sqlalchemy import select

from shared.ingest import store_inbound
from shared.models import DataSource, ExternalIdentity
from tests.api.conftest import actor
from tests.api.test_network_and_map import _setup
from tests.api.test_offload_stations import _opencollar_type
from tests.conftest import unique_name
from tests.decoder.conftest import inbound

pytestmark = pytest.mark.asyncio


async def test_a_dev_eui_finds_the_device_with_that_serial_and_its_name_is_raised(client, db):
    admin, project, _entity, source, _live_device, _live_external = await _setup(client, db)
    h = admin.headers
    other_admin = await actor(client, db, superuser=True)
    oc = await _opencollar_type(client, h)
    eui = "0016C001F0" + uuid.uuid4().hex[:6].upper()
    # the tracker as an offload card named it: the DevEUI is its serial and its name for now
    device = (
        await client.post(
            f"/api/v1/projects/{project.id}/devices",
            json={"device_type_id": oc["id"], "name": eui, "serial_number": eui},
            headers=h,
        )
    ).json()
    live_source = await db.get(DataSource, uuid.UUID(source["id"]))
    assert live_source is not None
    network_name = unique_name("SP05")
    stored = await store_inbound(
        db,
        live_source,
        inbound(
            eui.lower(),
            {"fPort": 13, "data": "AA=="},
            identity_type="dev_eui",
            identity_attributes={"name": network_name},
        ),
    )
    await db.commit()
    identity = await db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == live_source.id,
            ExternalIdentity.external_id == eui.lower(),
        )
    )
    assert identity is not None and str(identity.device_id) == device["id"]
    assert identity.attributes.get("linked_by") == "serial"
    assert stored.source_event.device_id == uuid.UUID(device["id"])
    unknown = (await client.get("/api/v1/attention/identities", headers=h)).json()["items"]
    assert all(i["external_id"] != eui.lower() for i in unknown), "nothing waits for a known EUI"

    # the network's name differs from Protect's: raised, then taken or kept
    conflicts = (await client.get("/api/v1/attention/names", headers=h)).json()
    mine = next(c for c in conflicts if c["device_id"] == device["id"])
    assert mine["network_name"] == network_name and mine["device_name"] == eui
    assert mine["project_id"] == str(project.id)
    summary = (await client.get("/api/v1/attention/summary", headers=h)).json()
    assert summary["name_conflicts"] >= 1
    renamed = await client.post(
        f"/api/v1/attention/names/{mine['identity_id']}/rename", headers=other_admin.headers
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["device_name"] == network_name
    conflicts = (await client.get("/api/v1/attention/names", headers=h)).json()
    assert all(c["device_id"] != device["id"] for c in conflicts)
    got = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    assert got["name"] == network_name and got["serial_number"] == eui

    # an identifier is not a name: a DevEUI the network reports as the name is not raised
    await store_inbound(
        db,
        live_source,
        inbound(
            eui.lower(),
            {"fPort": 13, "data": "AA=="},
            identity_type="dev_eui",
            identity_attributes={"name": "0016C001F0ABCDEF"},
        ),
    )
    await db.commit()
    conflicts = (await client.get("/api/v1/attention/names", headers=h)).json()
    assert all(c["device_id"] != device["id"] for c in conflicts)

    # a second name from the network, kept this time
    await store_inbound(
        db,
        live_source,
        inbound(
            eui.lower(),
            {"fPort": 13, "data": "AA=="},
            identity_type="dev_eui",
            identity_attributes={"name": network_name + "b"},
        ),
    )
    await db.commit()
    conflicts = (await client.get("/api/v1/attention/names", headers=h)).json()
    mine = next(c for c in conflicts if c["device_id"] == device["id"])
    kept = await client.post(f"/api/v1/attention/names/{mine['identity_id']}/keep", headers=h)
    assert kept.status_code == 204, kept.text
    conflicts = (await client.get("/api/v1/attention/names", headers=h)).json()
    assert all(c["device_id"] != device["id"] for c in conflicts)
    got = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    assert got["name"] == network_name
