"""The field bundle for Protect Field (phase 43, decision D331): one project for a laptop in the
field, with the keys only for a caller who may set them, the stations with their EUI and place,
the area, and the download in the audit log."""

import pytest
from sqlalchemy import select

from shared.enums import Role
from shared.models import AuditLog
from tests.api.conftest import actor, project_actor
from tests.api.test_network_and_map import _setup
from tests.api.test_offload_stations import _device, _opencollar_type
from tests.conftest import unique_name
from tests.shared.test_lp0_lorawan import APP_S_KEY, NWK_S_KEY

pytestmark = pytest.mark.asyncio

STATION_EUI = "0016C001F0ABCD31"  # its own station; serials are unique across the test database


async def test_bundle_carries_the_project_with_keys_for_those_who_may_set_them(client, db):
    admin, project, entity, _source, _live, _ext = await _setup(client, db)
    h = admin.headers
    project_id = project.id
    oc = await _opencollar_type(client, h)
    station = await _device(client, h, oc["id"], project_id, serial=STATION_EUI)
    tracker = await _device(client, h, oc["id"], project_id)
    bare = await _device(client, h, oc["id"], project_id)

    put = await client.put(
        f"/api/v1/devices/{tracker['id']}/lp0-credentials",
        json={"dev_addr": "26010207", "app_s_key": APP_S_KEY.hex(), "nwk_s_key": NWK_S_KEY.hex()},
        headers=h,
    )
    assert put.status_code == 200, put.text
    assigned = await client.post(
        f"/api/v1/projects/{project_id}/entity-assignments",
        json={
            "device_id": tracker["id"],
            "entity_id": entity["id"],
            "valid_from": "2024-01-01T00:00:00+00:00",
        },
        headers=h,
    )
    assert assigned.status_code == 201, assigned.text
    setup = await client.post(
        f"/api/v1/projects/{project_id}/offload/stations",
        json={
            "device_id": station["id"],
            "entity_name": unique_name("Station"),
            "latitude": -7.75,
            "longitude": -11.3,
        },
        headers=h,
    )
    assert setup.status_code == 201, setup.text

    # a server admin: everything, keys included
    response = await client.get(f"/api/v1/projects/{project_id}/field-bundle", headers=h)
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle["format_version"] == 1 and bundle["credentials_included"] is True
    assert bundle["project"]["id"] == str(project_id)
    assert bundle["protect_version"].startswith("v")
    by_id = {d["id"]: d for d in bundle["devices"]}
    assert by_id[tracker["id"]]["lp0"]["dev_addr"] == "26010207"
    assert by_id[tracker["id"]]["lp0"]["app_s_key"] == APP_S_KEY.hex().upper()
    assert by_id[tracker["id"]]["lp0"]["nwk_s_key"] == NWK_S_KEY.hex().upper()
    assert by_id[tracker["id"]]["entity_name"] == entity["name"]
    assert by_id[tracker["id"]]["driver_key"] == "opencollar"
    assert by_id[bare["id"]]["lp0"] is None and by_id[bare["id"]]["is_station"] is False
    assert (
        by_id[station["id"]]["is_station"] is True
        and by_id[station["id"]]["dev_eui"] == STATION_EUI
    )
    (listed,) = [s for s in bundle["stations"] if s["device_id"] == station["id"]]
    assert listed["station_eui"] == STATION_EUI
    assert listed["geometry"]["coordinates"] == [-11.3, -7.75]
    assert entity["id"] in {e["id"] for e in bundle["entities"]}
    area = bundle["area"]
    assert (
        area is not None
        and area["west"] <= -11.3 <= area["east"]
        and area["south"] <= -7.75 <= area["north"]
    )

    # a viewer: the same project, the address, never a key
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    response = await client.get(
        f"/api/v1/projects/{project_id}/field-bundle", headers=viewer.headers
    )
    assert response.status_code == 200, response.text
    seen = response.json()
    assert seen["credentials_included"] is False
    lp0 = {d["id"]: d["lp0"] for d in seen["devices"]}[tracker["id"]]
    assert lp0["dev_addr"] == "26010207" and lp0["keys_set"] is True
    assert lp0["app_s_key"] is None and lp0["nwk_s_key"] is None
    assert "app_s_key" not in response.text.replace('"app_s_key":null', "")

    # an operator may control devices, so may set keys, so sees them (the device page's rule)
    operator = await project_actor(client, db, project, Role.PROJECT_OPERATOR)
    response = await client.get(
        f"/api/v1/projects/{project_id}/field-bundle", headers=operator.headers
    )
    assert response.status_code == 200 and response.json()["credentials_included"] is True

    # not a member: refused
    stranger = await actor(client, db)
    response = await client.get(
        f"/api/v1/projects/{project_id}/field-bundle", headers=stranger.headers
    )
    assert response.status_code == 403

    # every download is in the audit log, with how many keys left
    entries = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.action == "project.field_bundle_downloaded",
                AuditLog.project_id == project_id,
            )
        )
    ).all()
    assert len(entries) == 3
    assert sorted(e.details["keys"] for e in entries) == [0, 1, 1]
