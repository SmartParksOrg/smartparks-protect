"""The grazing module over real rows: two zones drawn through the API, a herd's fixes, the
estimate refusing a tiny area, the run through the runner, the areas table and the polygons."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.analysis.runner import run_analysis
from shared.models import AnalysisGeometry, AnalysisRun, Position
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
LAT, LON = -24.9, 31.5
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * 0.9069  # cos(24.9 degrees)


def _square(lat: float, lon: float, side_m: float) -> dict:
    dlat, dlon = side_m / M_PER_DEG_LAT, side_m / M_PER_DEG_LON
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]
        ],
    }


async def _zone(client, h, project, name: str, geometry: dict) -> str:
    created = await client.post(
        f"/api/v1/projects/{project.id}/features",
        json={"feature_type": "zone", "name": name, "geometry": geometry},
        headers=h,
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _fixes(db, project, entity, device, source, lat: float, lon: float, hours: int):
    rows = []
    for i in range(hours * 6):
        when = T0 + timedelta(minutes=10 * i)
        rows.append(
            Position(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=700 + i,
                source_event_ingested_at=when,
                canonical_key=f"{device['id']}|gnss|{i}",
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
            )
        )
    db.add_all(rows)
    await db.commit()


async def test_a_grazing_run_over_zones(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    camp = await _zone(client, h, project, "Camp 1", _square(LAT, LON, 316.2))  # ten hectares
    far = await _zone(client, h, project, "Camp 2", _square(LAT + 0.05, LON, 316.2))
    tiny = await _zone(client, h, project, "Pen", _square(LAT + 0.1, LON, 20))
    centre_lat, centre_lon = LAT + 158 / M_PER_DEG_LAT, LON + 158 / M_PER_DEG_LON
    await _fixes(db, project, entity, device, source, centre_lat, centre_lon, hours=12)
    base = f"/api/v1/projects/{project.id}/analyses"
    params = {
        "entity_ids": [entity["id"]],
        "time_from": T0.isoformat(),
        "time_to": (T0 + timedelta(days=2)).isoformat(),
        "feature_ids": [camp, far, tiny],
    }
    estimate = await client.get(
        f"{base}/estimate",
        params={"module": "grazing", "parameters": json.dumps(params)},
        headers=h,
    )
    assert estimate.status_code == 200, estimate.text
    assert not estimate.json()["ok"] and "under one hectare" in estimate.json()["reasons"][0]
    refused = await client.post(base, json={"module": "grazing", "parameters": params}, headers=h)
    assert refused.status_code == 422

    params["feature_ids"] = [camp, far]
    created = await client.post(base, json={"module": "grazing", "parameters": params}, headers=h)
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    await run_analysis(db, await db.get(AnalysisRun, run_id))
    body = (await client.get(f"{base}/{run_id}", headers=h)).json()
    assert body["status"] == "completed", (body["error_code"], body["error_message"])
    document = body["result"]
    camp_figures = document["summary"]["main"][camp]
    assert camp_figures["hectares"] == pytest.approx(10, rel=0.02)
    assert camp_figures["animal_hours"] == pytest.approx(11.83, rel=0.02)
    assert camp_figures["animal_days_per_ha"] == pytest.approx(0.0493, rel=0.03)
    assert camp_figures["use_days"] == 1 and camp_figures["rest_days"] == 1
    assert camp_figures["relative_pressure"] == 2 and camp_figures["pressure_rank"] == 1
    assert camp_figures["hotspot_count"] == 1
    assert document["summary"]["main"][far]["animal_hours"] == 0
    assert document["summary"]["herd"]["main"]["share_inside"] == 1
    assert document["summary"]["weighting"]["unit"] == "animals"
    assert [a["name"] for a in document["summary"]["areas"]] == ["Camp 1", "Camp 2"]
    intensity = document["summary"]["intensity"]
    assert intensity["cell_m"] == 100 and set(intensity["areas"]) == {camp, far}
    assert len(intensity["areas"][camp]) == 1 and intensity["areas"][far] == []
    assert intensity["areas"][camp][0][2] == pytest.approx(11.83, rel=0.02)
    areas = next(t for t in document["tables"] if t["key"] == "areas")
    assert areas["columns"][:3] == ["area", "period", "hectares"]
    assert [r[:2] for r in areas["rows"]] == [["Camp 1", "main"], ["Camp 2", "main"]]
    # the camps share no ground: no overlap table
    assert "overlaps" not in {t["key"] for t in document["tables"]}
    animals = next(t for t in document["tables"] if t["key"] == "animals")
    assert animals["rows"][0][:2] == ["Rhino 14", "Camp 1"]
    timeline = next(c for c in document["charts"] if c["key"] == "timeline")
    assert len(timeline["series"]) == 2 and len(timeline["series"][0]["data"]) == 2
    assert document["geometries"] == {"hotspot": 1, "area": 2}

    stored = (
        await db.execute(
            select(AnalysisGeometry.kind, AnalysisGeometry.level, AnalysisGeometry.area_m2)
            .where(AnalysisGeometry.run_id == run_id)
            .order_by(AnalysisGeometry.id)
        )
    ).all()
    kinds = sorted(r.kind for r in stored)
    assert kinds == ["area", "area", "hotspot"]
    camp_row = next(r for r in stored if r.kind == "area" and r.level == 2)
    assert camp_row.area_m2 == pytest.approx(100_000, rel=0.02)

    modules = await client.get("/api/v1/analysis-modules", headers=h)
    assert {m["key"] for m in modules.json()} >= {"movement", "grazing"}


class FakeNdviProvider:
    """A provider that answers per week from a table, as a real one does (the value of a week
    never depends on who asked for it), and counts how often it was asked: the cache must
    spare it on a rerun (decision D245)."""

    key = "fake_ndvi"
    layers: tuple[str, ...] = ("ndvi",)

    def __init__(self, before: list[float], after: list[float], split: datetime) -> None:
        self.before = before
        self.after = after
        self.split = split
        self.calls = 0

    async def sample(self, layer, geometries, time_from, time_to, project_id):
        from shared.analysis.environment import LayerSample, weeks_between

        self.calls += 1
        weeks = weeks_between(time_from, time_to)
        return LayerSample(
            layer=layer,
            source="a test",
            sampled_at=datetime.now(UTC),
            series=[
                [(week, (self.before if week < self.split else self.after)[i]) for week in weeks]
                for i in range(len(geometries))
            ],
        )


async def test_a_grazing_run_carries_the_vegetation_of_each_area(client, db, monkeypatch):
    """Decision D246: the vegetation index per area over the period, its change against the
    period before, the use-against-vegetation table and the weekly chart; the cache spares the
    provider on a rerun, and without a provider the run says so and is complete."""
    from shared.analysis import environment

    admin, project, entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    camp = await _zone(client, h, project, "Camp 1", _square(LAT, LON, 316.2))
    far = await _zone(client, h, project, "Camp 2", _square(LAT + 0.05, LON, 316.2))
    centre_lat, centre_lon = LAT + 158 / M_PER_DEG_LAT, LON + 158 / M_PER_DEG_LON
    await _fixes(db, project, entity, device, source, centre_lat, centre_lon, hours=12)
    base = f"/api/v1/projects/{project.id}/analyses"
    params = {
        "entity_ids": [entity["id"]],
        "time_from": T0.isoformat(),
        "time_to": (T0 + timedelta(days=14)).isoformat(),
        "feature_ids": [camp, far],
        "comparison": {
            "time_from": (T0 - timedelta(days=14)).isoformat(),
            "time_to": T0.isoformat(),
        },
    }

    # without a provider the run is complete and says why there is no layer
    monkeypatch.setattr(environment, "PROVIDERS", [])
    created = await client.post(base, json={"module": "grazing", "parameters": params}, headers=h)
    run_id = uuid.UUID(created.json()["id"])
    await run_analysis(db, await db.get(AnalysisRun, run_id))
    document = (await client.get(f"{base}/{run_id}", headers=h)).json()["result"]
    assert "vegetation" not in {t["key"] for t in document["tables"]}
    assert any(w["code"] == "landscape_unavailable" for w in document["warnings"])

    # Camp 1 greens down over the period, Camp 2 holds; the week the two periods share takes
    # the value of its own week, not of the period that asked
    provider = FakeNdviProvider(before=[0.55, 0.52], after=[0.30, 0.50], split=T0)
    monkeypatch.setattr(environment, "PROVIDERS", [provider])
    created = await client.post(base, json={"module": "grazing", "parameters": params}, headers=h)
    run_id = uuid.UUID(created.json()["id"])
    await run_analysis(db, await db.get(AnalysisRun, run_id))
    document = (await client.get(f"{base}/{run_id}", headers=h)).json()["result"]
    figures = document["summary"]["main"][camp]
    # the main period holds three weeks, the first of them still at the old value
    assert figures["ndvi_mean"] == pytest.approx((0.55 + 0.30 + 0.30) / 3, abs=0.001)
    assert figures["ndvi_change"] == pytest.approx(figures["ndvi_mean"] - 0.55, abs=0.001)
    assert figures["ndvi_level"] == "warn"  # more than a tenth of an index point down
    assert figures["ndvi_valid_share"] == 1.0
    assert document["summary"]["main"][far]["ndvi_level"] == "ok"
    vegetation = next(t for t in document["tables"] if t["key"] == "vegetation")
    assert vegetation["columns"] == [
        "area",
        "animal_days_per_ha",
        "ndvi_mean",
        "ndvi_change",
        "ndvi_valid_share",
        "ndvi_level",
    ]
    assert vegetation["rows"][0][0] == "Camp 1"  # the most used area first
    weekly = next(c for c in document["charts"] if c["key"] == "ndvi_weekly")
    assert {s["period"] for s in weekly["series"]} == {"main", "comparison"}
    assert len(weekly["series"][0]["data"]) >= 2

    # a rerun reads the cache: the provider is not asked again
    asked = provider.calls
    created = await client.post(base, json={"module": "grazing", "parameters": params}, headers=h)
    rerun_id = uuid.UUID(created.json()["id"])
    await run_analysis(db, await db.get(AnalysisRun, rerun_id))
    again = (await client.get(f"{base}/{rerun_id}", headers=h)).json()["result"]
    assert again["summary"]["main"][camp]["ndvi_mean"] == pytest.approx(figures["ndvi_mean"])
    assert provider.calls == asked
