"""Gateways per project, detail, connectivity analysis, the server registry, the sync action
and polling cursors."""

import uuid

import pytest
from sqlalchemy import select

from shared.connectivity.base import GatewayReceptionData, GatewayUpdate, InboundMessage
from shared.connectivity.registry import ADAPTERS
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource
from tests.api.test_network_and_map import _setup, bus  # noqa: F401
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _uplink(db, bus, source, external_id, receptions, when, received_at=None):  # noqa: F811
    """A reception takes the network's receive time when the message carries one, else the
    ingest time; `received_at` dates the receptions themselves, as a real network does."""
    message = InboundMessage(
        external_id=external_id,
        event_type="uplink",
        payload={"time": when, "lat": -24.9, "lon": 31.5},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        network_received_at=received_at,
        gateway_receptions=[
            GatewayReceptionData(gateway_id=g, rssi=r, snr=s) for g, r, s in receptions
        ],
    )
    stored = await store_inbound(db, source, message)
    await commit_and_publish(db, bus, [stored])


async def test_gateways_connectivity_and_admin(client, db, bus, monkeypatch):  # noqa: F811
    admin, project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    external_id = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()[
        "external_identities"
    ][0]["external_id"]
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    for i, receptions in enumerate(
        [
            [("gw-a", -100, 8.0), ("gw-b", -115, 1.0)],
            [("gw-a", -102, 7.0)],
            [("gw-a", -98, 9.0), ("gw-b", -118, -1.0)],
        ]
    ):
        await _uplink(
            db, bus, row, external_id, receptions, (now - timedelta(minutes=i)).isoformat()
        )

    base = f"/api/v1/projects/{project.id}"
    gateways = (await client.get(f"{base}/gateways", headers=h)).json()
    assert [g["external_id"] for g in gateways] == ["gw-a", "gw-b"]
    best = gateways[0]
    assert best["receptions"] == 3 and best["devices"] == 1 and best["status"] == "online"
    assert best["display_name"] == "gw-a" and best["mean_rssi"] == -100.0
    assert best["data_source_name"] == source["name"]
    assert (await client.get(f"{base}/gateways", params={"hours": 0}, headers=h)).status_code == 422

    detail = (await client.get(f"{base}/gateways/{best['id']}", headers=h)).json()
    assert detail["gateway"]["id"] == best["id"]
    assert detail["devices"][0]["device_name"] == device["name"]
    assert detail["devices"][0]["receptions"] == 3
    # no location, no range (D374); placed 0.05 degrees east and south of the fixes, the three
    # positions it heard lie about 7.5 km away, all alike
    assert detail["gateway"]["range_positions"] == 0 and detail["gateway"]["range_max_m"] is None
    placed = await client.patch(
        f"{base}/gateways/{best['id']}/location",
        json={"latitude": -24.95, "longitude": 31.55},
        headers=h,
    )
    assert placed.status_code == 200, placed.text
    # the uplinks were stored, not decoded: the range reads positions, so decode them now
    from protect_decoder.pipeline import process_source_event
    from shared.models import SourceEvent

    for event in (
        await db.scalars(
            select(SourceEvent).where(SourceEvent.device_id == uuid.UUID(device["id"]))
        )
    ).all():
        await process_source_event(db, event.id, event.ingested_at)
    await db.commit()
    ranged = (await client.get(f"{base}/gateways/{best['id']}", headers=h)).json()["gateway"]
    assert ranged["range_positions"] == 3
    assert 7000 < ranged["range_min_m"] < 8000
    assert ranged["range_min_m"] == ranged["range_max_m"] == ranged["range_mean_m"]

    # a window the uplinks fall outside keeps the last reception (the newest of the last 30
    # days) beside empty counts, so a quiet day does not read as "never" (Tim, 2026-09-30);
    # the last hour holds the three uplinks of a minute ago, so one from two days ago is added
    two_days_ago = now - timedelta(days=2)
    await _uplink(
        db,
        bus,
        row,
        external_id,
        [("gw-d", -90, 5.0)],
        two_days_ago.isoformat(),
        received_at=two_days_ago,
    )
    hour = {
        g["external_id"]: g
        for g in (await client.get(f"{base}/gateways", params={"hours": 1}, headers=h)).json()
    }
    assert hour["gw-d"]["receptions"] == 0 and hour["gw-d"]["devices"] == 0
    assert hour["gw-d"]["mean_rssi"] is None
    assert hour["gw-d"]["last_reception_at"] is not None
    assert hour["gw-a"]["receptions"] == 3 and hour["gw-a"]["last_reception_at"] is not None
    quiet = (
        await client.get(f"{base}/gateways/{hour['gw-d']['id']}", params={"hours": 1}, headers=h)
    ).json()
    assert quiet["gateway"]["receptions"] == 0 and quiet["gateway"]["last_reception_at"] is not None
    assert quiet["devices"] == []

    connectivity = (await client.get(f"{base}/connectivity", headers=h)).json()
    assert len(connectivity) == 1
    item = connectivity[0]
    assert item["device_id"] == device["id"] and item["gateway_count"] == 2
    assert item["uplinks"] == 3 and item["receptions"] == 5
    assert item["best_gateway_id"] == best["id"] and item["best_gateway_share"] == 1.0
    assert item["gateways"][0]["external_id"] == "gw-a" and item["gateways"][1]["uplinks"] == 2

    # another project sees nothing
    from tests.api.conftest import create_project

    other = await create_project(db)
    assert (await client.get(f"/api/v1/projects/{other.id}/gateways", headers=h)).json() == []
    assert (await client.get(f"/api/v1/projects/{other.id}/connectivity", headers=h)).json() == []

    # the server registry and overrides
    registry = (
        await client.get(
            "/api/v1/admin/gateways", params={"data_source_id": source["id"]}, headers=h
        )
    ).json()
    assert {g["external_id"] for g in registry["items"]} == {"gw-a", "gw-b", "gw-d"}
    patched = await client.patch(
        f"/api/v1/admin/gateways/{best['id']}",
        json={"name_override": "North ridge", "latitude": -24.95, "longitude": 31.55},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "North ridge"
    assert patched.json()["geometry"]["coordinates"] == [31.55, -24.95]
    half = await client.patch(
        f"/api/v1/admin/gateways/{best['id']}", json={"latitude": 1}, headers=h
    )
    assert half.status_code == 422

    # sync against the platform through the adapter's management connector
    class FakeManagement:
        async def list_gateway_updates(self):
            return [
                GatewayUpdate(
                    gateway_id="gw-b",
                    name="South mast",
                    status="offline",
                    latitude=-24.7,
                    longitude=31.3,
                    # a row made from a reception had no attributes document yet (2026-09-12)
                    attributes={"description": "on the water tower"},
                ),
                GatewayUpdate(gateway_id="gw-c", name="Spare", status="unknown"),
            ]

    adapter = ADAPTERS[row.adapter_key]
    monkeypatch.setattr(
        type(adapter), "management_connector", lambda self, ctx: FakeManagement(), raising=False
    )
    synced = await client.post(f"/api/v1/data-sources/{source['id']}/sync-gateways", headers=h)
    assert synced.status_code == 200, synced.text
    assert synced.json()["synced"] == 2
    registry = (
        await client.get(
            "/api/v1/admin/gateways", params={"data_source_id": source["id"]}, headers=h
        )
    ).json()
    by_id = {g["external_id"]: g for g in registry["items"]}
    assert by_id["gw-b"]["name"] == "South mast" and by_id["gw-b"]["status"] == "offline"
    assert by_id["gw-b"]["attributes"] == {"description": "on the water tower"}
    assert by_id["gw-c"]["status"] == "unknown" and by_id["gw-c"]["geometry"] is None
    # the project page lists every gateway of its sources: the silent one last, with nothing
    # heard (decision D175); another project's sources stay out
    # the silent ones by last seen: the synced Spare was seen at the sync, gw-d two days ago
    listed = (await client.get(f"{base}/gateways", headers=h)).json()
    assert [g["external_id"] for g in listed] == ["gw-a", "gw-b", "gw-c", "gw-d"]
    assert listed[2]["display_name"] == "Spare" and listed[2]["receptions"] == 0
    assert listed[3]["receptions"] == 0 and listed[3]["last_reception_at"] is not None
    assert (await client.get(f"/api/v1/projects/{other.id}/gateways", headers=h)).json() == []

    generic = await client.post(
        "/api/v1/data-sources",
        json={"name": f"HTTP-{uuid.uuid4().hex[:6]}", "adapter_key": "generic_http"},
        headers=h,
    )
    assert (
        await client.post(f"/api/v1/data-sources/{generic.json()['id']}/sync-gateways", headers=h)
    ).status_code == 422
    # the daily pass (decision D176) takes every source that lists gateways and skips the rest
    from shared.connectivity.gateway_sync import sync_all_gateways
    from shared.timeutil import utc_now

    passed = await sync_all_gateways(db, utc_now(), require_channel=False)
    assert passed.get(source["name"]) == 2 and generic.json()["name"] not in passed

    # viewers cannot reach the server registry
    from shared.enums import Role
    from tests.api.conftest import project_actor

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(f"{base}/gateways", headers=viewer.headers)).status_code == 200
    assert (await client.get("/api/v1/admin/gateways", headers=viewer.headers)).status_code == 403


async def test_a_silent_gateway_its_days_and_the_messages_it_relayed(client, db, bus):  # noqa: F811
    """Decision D370: a gateway heard from within a day reads online, one that relayed its
    last uplink days ago reads silent, the platform's fresh word stands and its offline word
    stays; decision D369: the receptions per day and the traffic a gateway relayed."""
    from datetime import UTC, datetime, timedelta

    from shared.ingest import apply_gateway_update
    from shared.models import Gateway

    admin, project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    external_id = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()[
        "external_identities"
    ][0]["external_id"]
    now = datetime.now(UTC).replace(microsecond=0)
    three_days_ago = now - timedelta(days=3)
    await _uplink(
        db,
        bus,
        row,
        external_id,
        [("gw-old", -100, 5.0)],
        three_days_ago.isoformat(),
        received_at=three_days_ago,
    )
    await _uplink(
        db,
        bus,
        row,
        external_id,
        [("gw-now", -90, 7.0)],
        (now - timedelta(minutes=5)).isoformat(),
        received_at=now - timedelta(minutes=5),
    )
    base = f"/api/v1/projects/{project.id}"
    by_id = {
        g["external_id"]: g
        for g in (await client.get(f"{base}/gateways", params={"hours": 168}, headers=h)).json()
    }
    assert by_id["gw-now"]["status"] == "online"
    assert by_id["gw-old"]["status"] == "silent"
    assert by_id["gw-old"]["last_seen_at"] is not None

    # the platform's word: fresh, it stands whatever the receptions say (the list's lastSeenAt
    # is three days old, the word itself is of now); stale, the evidence decides; offline stays
    await apply_gateway_update(
        db,
        row.id,
        GatewayUpdate(gateway_id="gw-old", status="online", name="Hill", seen_at=three_days_ago),
        now,
    )
    await db.commit()
    detail = (await client.get(f"{base}/gateways/{by_id['gw-old']['id']}", headers=h)).json()
    assert detail["gateway"]["status"] == "online" and detail["gateway"]["display_name"] == "Hill"
    gateway = await db.get(Gateway, uuid.UUID(by_id["gw-old"]["id"]))
    assert gateway.status_source == "platform" and gateway.status_at is not None
    gateway.status_at = now - timedelta(hours=48)  # the sync has not run for two days
    await db.commit()
    detail = (await client.get(f"{base}/gateways/{by_id['gw-old']['id']}", headers=h)).json()
    assert detail["gateway"]["status"] == "silent"
    await apply_gateway_update(
        db, row.id, GatewayUpdate(gateway_id="gw-old", status="offline"), now
    )
    await db.commit()
    detail = (await client.get(f"{base}/gateways/{by_id['gw-old']['id']}", headers=h)).json()
    assert detail["gateway"]["status"] == "offline"

    # the receptions per day (D369): gw-old relayed one uplink three days ago, gw-now one today
    days = (
        await client.get(
            f"{base}/gateways/{by_id['gw-old']['id']}/days", params={"hours": 168}, headers=h
        )
    ).json()
    assert [(d["day"], d["receptions"], d["devices"], d["mean_rssi"]) for d in days] == [
        (three_days_ago.date().isoformat(), 1, 1, -100.0)
    ]
    assert (
        await client.get(
            f"{base}/gateways/{by_id['gw-now']['id']}/days", params={"hours": 12}, headers=h
        )
    ).status_code == 422

    # the messages a gateway relayed (D369): the traffic read and its count cut to the gateway
    week = {"from": (now - timedelta(days=7)).isoformat()}
    relayed = (
        await client.get(
            f"{base}/traffic", params={**week, "gateway_id": by_id["gw-old"]["id"]}, headers=h
        )
    ).json()
    assert len(relayed) == 1 and relayed[0]["receptions"][0]["gateway_id"] == "gw-old"
    count = (
        await client.get(
            f"{base}/traffic/count", params={**week, "gateway_id": by_id["gw-now"]["id"]}, headers=h
        )
    ).json()
    assert count["count"] == 1
    assert (
        await client.get(
            f"{base}/traffic", params={**week, "gateway_id": str(uuid.uuid4())}, headers=h
        )
    ).status_code == 404


async def test_all_scope_counts_devices_in_no_project(client, db, bus):  # noqa: F811
    """A device in no project is heard in the all scope, not in a project (decision D120)."""
    from datetime import UTC, datetime

    admin, project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    loose = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device["device_type_id"], "name": "loose", "status": "active"},
            headers=h,
        )
    ).json()
    external_id = uuid.uuid4().hex[:16].upper()
    await _uplink(db, bus, row, external_id, [("gw-c", -90, 5.0)], datetime.now(UTC).isoformat())
    identity = next(
        i
        for i in (await client.get("/api/v1/attention/identities?limit=500", headers=h)).json()[
            "items"
        ]
        if i["external_id"] == external_id
    )
    linked = await client.post(
        f"/api/v1/attention/identities/{identity['id']}/link",
        json={"device_id": loose["id"], "reprocess": False},
        headers=h,
    )
    assert linked.status_code == 200, linked.text
    await _uplink(db, bus, row, external_id, [("gw-c", -92, 4.0)], datetime.now(UTC).isoformat())

    # the gateway is on the project's source, so the project lists it (decision D175), but
    # the loose device's reception is not the project's; the all scope counts it
    # (another test's source has a gw-c too, so the source id is part of the key)
    key = (source["id"], "gw-c")
    in_project = {
        (g["data_source_id"], g["external_id"]): g
        for g in (await client.get(f"/api/v1/projects/{project.id}/gateways", headers=h)).json()
    }
    assert key in in_project and in_project[key]["receptions"] == 0
    in_all = {
        (g["data_source_id"], g["external_id"]): g
        for g in (await client.get("/api/v1/projects/all/gateways", headers=h)).json()
    }
    assert in_all[key]["receptions"] == 1
    connectivity = (await client.get("/api/v1/projects/all/connectivity", headers=h)).json()
    assert loose["id"] in [c["device_id"] for c in connectivity]


async def test_polling_cursor_reset(client, db):
    from tests.api.conftest import actor

    admin = await actor(client, db, superuser=True)
    h = admin.headers
    polling_key = next(k for k, a in ADAPTERS.items() if getattr(a, "polling", False))
    created = await client.post(
        "/api/v1/data-sources",
        json={
            "name": f"Poll-{uuid.uuid4().hex[:6]}",
            "adapter_key": polling_key,
            "config": {"url": "https://example.org"},
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    assert (await client.get(f"/api/v1/data-sources/{source_id}/cursor", headers=h)).json() == {}
    reset = await client.post(
        f"/api/v1/data-sources/{source_id}/cursor",
        json={"since": "2026-08-01T00:00:00+00:00"},
        headers=h,
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["since"] == "2026-08-01T00:00:00+00:00"
    state = (await client.get(f"/api/v1/data-sources/{source_id}/cursor", headers=h)).json()
    assert state["since"] == "2026-08-01T00:00:00+00:00" and state["reset_by"]
    pushed = await client.post(
        "/api/v1/data-sources",
        json={"name": f"HTTP-{uuid.uuid4().hex[:6]}", "adapter_key": "generic_http"},
        headers=h,
    )
    assert (
        await client.post(f"/api/v1/data-sources/{pushed.json()['id']}/cursor", json={}, headers=h)
    ).status_code == 422


async def test_a_source_assigned_to_the_project_shows_its_gateways_at_once(client, db, bus):  # noqa: F811
    """Decision D235: the assignment adds visibility and never removes it. A second source with
    a gateway and no device of the project: hidden until the source is assigned to the project,
    listed then; the first source's gateways stay."""
    from geoalchemy2 import WKTElement

    from shared.models import DataSourceProjectScope, Gateway

    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    other = DataSource(
        name=unique_name("Other network"), adapter_key="http", config={}, capabilities={}
    )
    db.add(other)
    await db.flush()
    db.add(
        Gateway(
            data_source_id=other.id,
            external_id="gw-other",
            name="Far gateway",
            geom=WKTElement("POINT(31.4 -24.8)", srid=4326),
        )
    )
    await db.commit()
    base = f"/api/v1/projects/{project.id}"
    listed = (await client.get(f"{base}/gateways", headers=h)).json()
    assert all(g["external_id"] != "gw-other" for g in listed)

    db.add(DataSourceProjectScope(data_source_id=other.id, project_id=project.id))
    await db.commit()
    listed = (await client.get(f"{base}/gateways", headers=h)).json()
    assert any(g["external_id"] == "gw-other" for g in listed)
    # the search sees it too, and the first source's gateways with it
    found = (await client.get("/api/v1/search", params={"q": "Far"}, headers=h)).json()
    assert any("Far gateway" in str(item) for item in found.get("gateways", found.get("items", [])))


async def test_a_project_admin_places_a_gateway_the_platform_gave_no_location(client, db, bus):  # noqa: F811
    """Decision D239: a Gateway Mesh relay or a gateway on a network without a gateway API has
    no location; a project admin sets one from the gateway's dialog, a viewer cannot, another
    project's admin does not see the gateway, and both coordinates empty clear it again."""
    from shared.enums import Role
    from shared.models import DataSourceProjectScope, Gateway
    from tests.api.conftest import actor, add_member, create_project

    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    other = DataSource(
        name=unique_name("Mesh network"), adapter_key="http", config={}, capabilities={}
    )
    db.add(other)
    await db.flush()
    relay = Gateway(
        data_source_id=other.id,
        external_id="f1366ff3",
        attributes={"kind": "relay"},
        status="online",
    )
    db.add(relay)
    db.add(DataSourceProjectScope(data_source_id=other.id, project_id=project.id))
    await db.commit()
    base = f"/api/v1/projects/{project.id}/gateways/{relay.id}/location"
    placed = await client.patch(
        base, json={"latitude": -24.81, "longitude": 31.42, "altitude_m": 410}, headers=h
    )
    assert placed.status_code == 200, placed.text
    body = placed.json()
    assert body["geometry"]["coordinates"] == [31.42, -24.81]
    assert body["location_source"] == "admin" and body["altitude_m"] == 410
    # one coordinate alone is refused
    assert (await client.patch(base, json={"latitude": -24.8}, headers=h)).status_code == 422
    # a viewer may not, another project's admin does not see it
    viewer = await actor(client, db)
    await add_member(db, viewer.user, project, Role.PROJECT_VIEWER)
    assert (
        await client.patch(
            base, json={"latitude": -24.8, "longitude": 31.4}, headers=viewer.headers
        )
    ).status_code == 403
    elsewhere = await create_project(db)
    stranger = await actor(client, db)
    await add_member(db, stranger.user, elsewhere, Role.PROJECT_ADMIN)
    refused = await client.patch(
        f"/api/v1/projects/{elsewhere.id}/gateways/{relay.id}/location",
        json={"latitude": -24.8, "longitude": 31.4},
        headers=stranger.headers,
    )
    assert refused.status_code == 404
    # both empty clears the location set by hand
    cleared = await client.patch(base, json={}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["geometry"] is None
    assert cleared.json()["location_source"] is None


async def test_a_project_admin_names_a_gateway(client, db, bus):  # noqa: F811
    """Decision D247: the platform's name is often the gateway id, so a project admin gives the
    gateway the name the field uses; a viewer cannot, another project's admin does not see it,
    and an empty name gives the platform's name back."""
    from shared.enums import Role
    from shared.models import DataSourceProjectScope, Gateway
    from tests.api.conftest import actor, add_member, create_project

    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    other = DataSource(
        name=unique_name("Mesh network"), adapter_key="http", config={}, capabilities={}
    )
    db.add(other)
    await db.flush()
    gateway = Gateway(
        data_source_id=other.id, external_id="f1366ff3", name="f1366ff3", status="online"
    )
    db.add(gateway)
    db.add(DataSourceProjectScope(data_source_id=other.id, project_id=project.id))
    await db.commit()
    base = f"/api/v1/projects/{project.id}/gateways/{gateway.id}"
    named = await client.patch(base, json={"name": "  North ridge  "}, headers=h)
    assert named.status_code == 200, named.text
    assert named.json()["name_override"] == "North ridge"
    assert named.json()["display_name"] == "North ridge"
    # the list shows it too
    listed = (await client.get(f"/api/v1/projects/{project.id}/gateways", headers=h)).json()
    assert [g["display_name"] for g in listed if g["id"] == str(gateway.id)] == ["North ridge"]
    # a viewer may not, another project's admin does not see the gateway
    viewer = await actor(client, db)
    await add_member(db, viewer.user, project, Role.PROJECT_VIEWER)
    assert (
        await client.patch(base, json={"name": "Theirs"}, headers=viewer.headers)
    ).status_code == 403
    elsewhere = await create_project(db)
    stranger = await actor(client, db)
    await add_member(db, stranger.user, elsewhere, Role.PROJECT_ADMIN)
    refused = await client.patch(
        f"/api/v1/projects/{elsewhere.id}/gateways/{gateway.id}",
        json={"name": "Theirs"},
        headers=stranger.headers,
    )
    assert refused.status_code == 404
    # an empty name gives the platform's name back
    cleared = await client.patch(base, json={"name": ""}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["name_override"] is None
    assert cleared.json()["display_name"] == "f1366ff3"


async def test_a_second_tenant_key_names_the_gateways_of_the_same_chirpstack(
    client,
    db,
    bus,  # noqa: F811
    monkeypatch,
):
    """Decision D375: two sources on one ChirpStack, a tenant key each. A gateway the first
    source knows from an uplink gets its name, state and place from the second source's list,
    and no second row; a gateway only the second tenant has becomes the second source's row."""
    from datetime import UTC, datetime

    admin, _project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers

    async def make(name: str) -> dict:
        response = await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name(name),
                "adapter_key": "chirpstack",
                "config": {"web_url": f"https://cs.example.org/#/tenants/{uuid.uuid4()}"},
                "credentials": {"api_token": "x"},
                "channels": {"api": True, "http": False, "mqtt": False},
            },
            headers=h,
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = await make("tenant-a")
    second = await make("tenant-b")
    row_a = await db.get(DataSource, uuid.UUID(first["id"]))
    # an uplink through the first tenant's source: a nameless row for gw-shared under it
    await _uplink(
        db,
        bus,
        row_a,
        "0000000000000001",
        [("gw-shared", -100, 5.0)],
        datetime.now(UTC).isoformat(),
    )

    class FakeManagement:
        async def list_gateway_updates(self):
            return [
                GatewayUpdate(
                    gateway_id="gw-shared",
                    name="Hill top",
                    status="online",
                    latitude=-24.7,
                    longitude=31.3,
                ),
                GatewayUpdate(gateway_id="gw-own", name="Valley", status="offline"),
            ]

    adapter = ADAPTERS["chirpstack"]
    monkeypatch.setattr(
        type(adapter), "management_connector", lambda self, ctx: FakeManagement(), raising=False
    )
    synced = await client.post(f"/api/v1/data-sources/{second['id']}/sync-gateways", headers=h)
    assert synced.status_code == 200, synced.text
    assert synced.json()["synced"] == 2

    async def registry(source_id: str) -> dict[str, dict]:
        items = (
            await client.get(
                "/api/v1/admin/gateways", params={"data_source_id": source_id}, headers=h
            )
        ).json()["items"]
        return {g["external_id"]: g for g in items}

    under_a = await registry(first["id"])
    under_b = await registry(second["id"])
    assert under_a["gw-shared"]["name"] == "Hill top"
    assert under_a["gw-shared"]["status"] == "online"
    assert under_a["gw-shared"]["geometry"]["coordinates"] == [31.3, -24.7]
    assert "gw-shared" not in under_b
    assert under_b["gw-own"]["name"] == "Valley" and under_b["gw-own"]["status"] == "offline"
