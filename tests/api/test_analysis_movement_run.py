"""The movement module over real rows: the API creates the run over an animal's fixes, the
runner computes it as the worker would, the document and the hotspot polygons land."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import func, select

from shared.analysis.runner import run_analysis
from shared.models import AnalysisGeometry, AnalysisRun, Position
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
LAT, LON = -24.9, 31.5
M_PER_DEG_LAT = 111_320.0


async def _walk(db, project, entity, device, source):
    """Six hours east at 100 m every ten minutes, then six hours still, then a network
    location and an invalid fix that must not count."""
    dlon = 100 / (M_PER_DEG_LAT * 0.9)  # cos(24.9 degrees)
    rows = []
    for i in range(72):
        when = T0 + timedelta(minutes=10 * i)
        step = min(i, 36)
        rows.append(
            Position(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=900 + i,
                source_event_ingested_at=when,
                canonical_key=f"{device['id']}|gnss|{i}",
                geom=WKTElement(f"POINT({LON + step * dlon} {LAT})", srid=4326),
                satellites=8,
                accuracy_m=5.0,
            )
        )
    when = T0 + timedelta(hours=13)
    rows.append(
        Position(
            time=when,
            device_id=uuid.UUID(device["id"]),
            project_id=project.id,
            entity_id=uuid.UUID(entity["id"]),
            data_source_id=uuid.UUID(source["id"]),
            source_event_id=999,
            source_event_ingested_at=when,
            record_type="network",
            canonical_key=f"{device['id']}|network|1",
            geom=WKTElement(f"POINT({LON + 1} {LAT + 1})", srid=4326),
        )
    )
    rows.append(
        Position(
            time=when + timedelta(minutes=1),
            device_id=uuid.UUID(device["id"]),
            project_id=project.id,
            entity_id=uuid.UUID(entity["id"]),
            data_source_id=uuid.UUID(source["id"]),
            source_event_id=1000,
            source_event_ingested_at=when,
            canonical_key=f"{device['id']}|gnss|bad",
            geom=WKTElement(f"POINT({LON - 1} {LAT - 1})", srid=4326),
            valid=False,
        )
    )
    db.add_all(rows)
    await db.commit()


async def test_a_movement_run_over_fixes(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    await _walk(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/analyses"
    params = {
        "entity_ids": [entity["id"]],
        "time_from": T0.isoformat(),
        "time_to": (T0 + timedelta(days=1)).isoformat(),
        "gap_hours": 4,
        "cell_m": 100,
    }
    estimate = await client.get(
        f"{base}/estimate",
        params={"module": "movement", "parameters": json.dumps(params)},
        headers=h,
    )
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["fixes"] == 72 and estimate.json()["ok"]

    created = await client.post(base, json={"module": "movement", "parameters": params}, headers=h)
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    assert created.json()["method_version"] == "movement/1"

    await run_analysis(db, await db.get(AnalysisRun, run_id))
    read = await client.get(f"{base}/{run_id}", headers=h)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "completed", body
    assert body["input_count"] == 72 and body["excluded_count"] == 0
    document = body["result"]
    summary = document["summary"]["main"][entity["id"]]
    assert summary["fixes"] == 72
    assert summary["distance_km"] == pytest.approx(3.6, rel=0.01)
    assert summary["displacement_km"] == pytest.approx(3.6, rel=0.01)
    # half the covered time is a stationary period of six hours
    assert summary["stationary_periods"] == 1
    assert summary["stationary_share"] == pytest.approx(0.5, abs=0.02)
    assert summary["hotspot_count"] == 1  # the cell it rested in holds half the time
    assert document["subjects"][0]["name"] == "Rhino 14"
    assert document["subjects"][0]["type"] == "Animal"
    assert {c["key"] for c in document["charts"]} >= {"daily_distance", "turning", "nsd"}
    assert [w["code"] for w in document["warnings"] if w["level"] == "warning"] == ["gaps"]

    stored = (
        await db.execute(
            select(AnalysisGeometry.kind, AnalysisGeometry.level, AnalysisGeometry.area_m2).where(
                AnalysisGeometry.run_id == run_id
            )
        )
    ).all()
    assert len(stored) == 1 and stored[0].kind == "hotspot"
    assert stored[0].area_m2 == pytest.approx(100 * 100, rel=0.02)
    assert stored[0].level == pytest.approx(0.5, abs=0.05)

    features = await client.get(f"{base}/{run_id}/geometries", headers=h)
    assert features.status_code == 200
    assert features.json()["features"][0]["properties"]["visits"] == 1

    csv_export = await client.get(
        f"{base}/{run_id}/export", params={"what": "summary", "format": "csv"}, headers=h
    )
    assert csv_export.status_code == 200
    assert csv_export.text.splitlines()[0].startswith("subject,period,fixes,")
    count = await db.scalar(select(func.count()).select_from(Position))
    assert count >= 74
