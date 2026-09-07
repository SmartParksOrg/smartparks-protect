"""Coverage (decision D107): heard positions as points or hexagons, the share per gateway."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.connectivity.base import GatewayReceptionData, InboundMessage
from shared.enums import AcquisitionChannel, IngestionMethod
from shared.ingest import commit_and_publish, store_inbound
from shared.models import DataSource
from tests.api.test_network_and_map import _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _heard(db, bus, source_id, external_id, when, lat, lon, receptions):  # noqa: F811
    from protect_decoder.pipeline import process_source_event

    source = await db.get(DataSource, uuid.UUID(source_id))
    message = InboundMessage(
        external_id=external_id,
        event_type="uplink",
        payload={"time": when.isoformat(), "lat": lat, "lon": lon},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        network_received_at=when + timedelta(seconds=2),
        gateway_receptions=[
            GatewayReceptionData(gateway_id=g, rssi=r, snr=s) for g, r, s in receptions
        ],
    )
    stored = await store_inbound(db, source, message)
    await commit_and_publish(db, bus, [stored])
    await process_source_event(db, stored.source_event.id, stored.source_event.ingested_at)
    await db.commit()


async def test_coverage_points_hexagons_and_shares(client, db, bus):  # noqa: F811
    admin, project, _entity, source, _device, external_id = await _setup(client, db)
    h = admin.headers
    now = datetime.now(UTC).replace(microsecond=0)
    fixes = [
        (-24.90, 31.50, [("gw-a", -95.0, 8.0), ("gw-b", -110.0, 2.0)]),
        (-24.91, 31.51, [("gw-a", -100.0, 7.0)]),
        (-24.92, 31.52, [("gw-b", -105.0, 3.0)]),
    ]
    for i, (lat, lon, receptions) in enumerate(fixes):
        await _heard(
            db, bus, source["id"], external_id, now - timedelta(minutes=i + 1), lat, lon, receptions
        )
    base = f"/api/v1/projects/{project.id}"

    points = await client.get(f"{base}/coverage", params={"zoom": 14, "hours": 24}, headers=h)
    assert points.status_code == 200, points.text
    body = points.json()
    assert body["mode"] == "points" and body["total"] == 3
    assert sorted(f["properties"]["best_rssi"] for f in body["features"]) == [-105.0, -100.0, -95.0]
    assert [(g["external_id"], g["heard"], g["share"]) for g in body["gateways"]] == [
        ("gw-a", 2, 0.667),
        ("gw-b", 2, 0.667),
    ]
    gw_a = next(g for g in body["gateways"] if g["external_id"] == "gw-a")
    assert gw_a["gateway_id"] is not None and gw_a["best_rssi"] == -95.0

    # points at any zoom (decision D123); hexagons on request only
    assert (
        await client.get(
            f"{base}/coverage",
            params={"zoom": 6, "hours": 24, "bbox": "31.4,-25.0,31.6,-24.8"},
            headers=h,
        )
    ).json()["mode"] == "points"
    hexes = await client.get(
        f"{base}/coverage",
        params={"zoom": 9, "hours": 24, "bbox": "31.4,-25.0,31.6,-24.8", "mode": "hexagons"},
        headers=h,
    )
    assert hexes.status_code == 200, hexes.text
    body = hexes.json()
    assert body["mode"] == "hexagons" and body["hexagon_m"] > 0 and body["total"] == 3
    assert sum(f["properties"]["count"] for f in body["features"]) == 3
    assert all(f["geometry"]["type"] == "Polygon" for f in body["features"])
    assert max(f["properties"]["best_rssi"] for f in body["features"]) == -95.0

    # one gateway only
    only_b = (
        await client.get(
            f"{base}/coverage",
            params={"zoom": 14, "hours": 24, "gateway_id": gw_a["gateway_id"]},
            headers=h,
        )
    ).json()
    assert only_b["total"] == 2 and [g["external_id"] for g in only_b["gateways"]] == ["gw-a"]

    # outside the window or the view: nothing
    empty = (
        await client.get(f"{base}/coverage", params={"zoom": 14, "bbox": "0,0,1,1"}, headers=h)
    ).json()
    assert empty["total"] == 0 and empty["features"] == [] and empty["gateways"] == []
    assert (await client.get(f"{base}/coverage", params={"hours": 0}, headers=h)).status_code == 422
