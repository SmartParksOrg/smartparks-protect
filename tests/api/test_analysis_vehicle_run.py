"""The vehicle use module over real rows (phase 39): the check refuses an animal, the API
queues a run over a car's fixes with their reported speeds, the runner computes it as the
worker would, and the trips land as lines with the speeding point."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.analysis.runner import run_analysis
from shared.models import AnalysisGeometry, AnalysisRun, Position
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 25, 13, 0, tzinfo=UTC)
LAT, LON = -24.9, 31.5
M_PER_DEG_LON = 111_320.0 * 0.9067  # cos(24.9 degrees)


async def _car(client, headers, project):
    """An entity of the catalogue's Car sub-type, which the module admits."""
    types = (
        await client.get("/api/v1/entity-types", params={"limit": 500}, headers=headers)
    ).json()
    car = next(t for t in types["items"] if t["key"] == "car")
    created = await client.post(
        f"/api/v1/projects/{project.id}/entities",
        json={"entity_type_id": car["id"], "name": unique_name("Bakkie")},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _drive(db, project, entity, device, source):
    """Ten minutes parked, thirty minutes east at 60 km/h with the speed reported, two of them
    at 75, then twenty minutes parked with the receiver drifting a few metres."""
    rows = []
    x = 0.0
    for i in range(60):
        when = T0 + timedelta(minutes=i)
        if 10 <= i < 40:
            x += 1000
            speed = 75 / 3.6 if i in (20, 21) else 60 / 3.6
        else:
            speed = 0.0
        drift = 3.0 if i % 2 else -3.0
        rows.append(
            Position(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=5000 + i,
                source_event_ingested_at=when,
                canonical_key=f"{device['id']}|gnss|v{i}",
                geom=WKTElement(f"POINT({LON + (x + drift) / M_PER_DEG_LON} {LAT})", srid=4326),
                speed_mps=speed,
                heading_deg=90.0,
                satellites=9,
                accuracy_m=4.0,
            )
        )
    db.add_all(rows)
    await db.commit()


async def test_a_vehicle_run_over_a_drive(client, db):
    admin, project, rhino, source, device, _ = await _setup(client, db)
    h = admin.headers
    car = await _car(client, h, project)
    await _drive(db, project, car, device, source)
    base = f"/api/v1/projects/{project.id}/analyses"
    window = {"time_from": T0.isoformat(), "time_to": (T0 + timedelta(hours=2)).isoformat()}

    # an animal is refused before anything is queued
    refused = await client.get(
        f"{base}/estimate",
        params={
            "module": "vehicle_use",
            "parameters": json.dumps({"entity_ids": [rhino["id"]], **window}),
        },
        headers=h,
    )
    assert refused.status_code == 200, refused.text
    assert not refused.json()["ok"]
    assert "No vehicle among the subjects" in refused.json()["reasons"][0]
    mixed = await client.get(
        f"{base}/estimate",
        params={
            "module": "vehicle_use",
            "parameters": json.dumps({"entity_ids": [rhino["id"], car["id"]], **window}),
        },
        headers=h,
    )
    assert "Rhino 14 is not a vehicle" in mixed.json()["reasons"][0]

    # a rule of the project that judges a speed inside an area, and one that is switched
    # off: the first gives the speed chart a line beside the run's own limit
    zone_rule = {
        "trigger": {"kind": "position"},
        "conditions": {
            "all": [
                {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 40},
                {"type": "spatial", "relation": "inside", "feature_type": "zone"},
            ]
        },
        "event": {"event_type": "SPEED_LIMIT_VIOLATION", "title": "{entity} at {value} km/h"},
    }
    off_rule = dict(
        zone_rule,
        conditions={"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 25},
    )
    for name, document, enabled in (
        ("Camp road", zone_rule, True),
        ("Switched off", off_rule, False),
    ):
        made = await client.post(
            f"/api/v1/projects/{project.id}/rules",
            json={"name": unique_name(name), "document": document, "enabled": enabled},
            headers=h,
        )
        assert made.status_code == 201, made.text

    params = {"entity_ids": [car["id"]], **window, "limit_kmh": 60}
    estimate = await client.get(
        f"{base}/estimate",
        params={"module": "vehicle_use", "parameters": json.dumps(params)},
        headers=h,
    )
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["ok"] and estimate.json()["fixes"] == 60

    created = await client.post(
        base, json={"module": "vehicle_use", "parameters": params}, headers=h
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    assert created.json()["method_version"] == "vehicle_use/2"

    await run_analysis(db, await db.get(AnalysisRun, run_id))
    body = (await client.get(f"{base}/{run_id}", headers=h)).json()
    assert body["status"] == "completed", (body["error_code"], body["error_message"])
    document = body["result"]
    summary = document["summary"]["main"][car["id"]]
    assert summary["fixes"] == 60 and summary["trips"] == 1
    assert summary["distance_km"] == pytest.approx(30, rel=0.02)
    assert summary["top_speed_kmh"] == 75 and summary["speeding_episodes"] == 1
    assert summary["fixes_with_speed_share"] == 1
    # the parked minutes drift a few metres each and fold into their stop
    assert summary["folded_fixes"] >= 25 and summary["days_active"] == 1
    assert document["subjects"][0]["type"] == "Car"
    tables = {t["key"]: t for t in document["tables"]}
    assert len(tables["trips"]["rows"]) == 1 and tables["trips"]["rows"][0][8] == 75
    assert len(tables["speeding"]["rows"]) == 1
    charts = {c["key"]: c for c in document["charts"]}
    assert list(charts) == [
        "speed_over_time",
        "daily_distance",
        "daily_driving",
        "hour_driving",
        "hour_speed",
        "speed_bands",
        "daily_speeding",
    ]
    lines = charts["speed_over_time"]["limits"]
    assert [(x["value"], x["source"], x["zone"]) for x in lines] == [
        (60, "run", False),
        (40, "rule", True),
    ]
    assert lines[1]["label"].startswith("Camp road")
    speeds = [v for _, v in charts["speed_over_time"]["series"][0]["data"]]
    assert len(speeds) == 120 and max(v for v in speeds if v is not None) == 75
    assert speeds[-1] is None  # the second hour has no fix: a silence, not a standstill
    assert charts["daily_distance"]["series"][0]["data"][0][1] == pytest.approx(30, rel=0.02)
    # the trip in runs of one band on one side of the limit (60 then 75 then 60 km/h, all in
    # the band from 40, the middle one over the limit of 60), a numbered start and end, and
    # the speeding marker
    assert document["geometries"]["trip_segment"] == 3
    assert document["geometries"]["trip_marker"] == 2
    assert document["geometries"]["speeding"] == 1

    stored = (
        await db.execute(
            select(AnalysisGeometry.kind, AnalysisGeometry.level).where(
                AnalysisGeometry.run_id == run_id
            )
        )
    ).all()
    assert {row.kind for row in stored} == {"speeding", "trip_segment", "trip_marker"}
    trip = await client.get(
        f"{base}/{run_id}/geometries", params={"kind": "trip_segment"}, headers=h
    )
    features = trip.json()["features"]
    assert all(f["geometry"]["type"] == "LineString" for f in features)
    assert {f["properties"]["speed_class"] for f in features} == {3}
    assert sorted(f["properties"]["over_limit"] for f in features) == [False, False, True]
    assert features[0]["properties"]["top_kmh"] == 75 and features[0]["properties"]["trip"] == 1
    count = await db.scalar(
        select(Position.id).where(Position.entity_id == uuid.UUID(car["id"])).limit(1)
    )
    assert count is not None
