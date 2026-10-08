"""The habitat selection module through the API and the runner (phase 41): the check refuses
a layer the project lacks; in the lean environment a run fails with `MODULE_UNAVAILABLE` and
says which image to build; in the analysis image a run over animals whose fixes favour the
east of a gradient layer, with a distance layer from the project's site, answers
coefficients, a validation per animal, the domains and the selection cells."""

import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.analysis.runner import run_analysis
from shared.models import AnalysisGeometry, AnalysisRun, Position
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, tzinfo=UTC)
LAT, LON = -20.85, 15.02
EPSG = 32733


def _has_engine() -> bool:
    try:
        import hsa.rsf  # noqa: F401
        import rasterio  # noqa: F401
    except ImportError:
        return False
    return True


async def _animal(client, headers, project, name):
    types = (
        await client.get("/api/v1/entity-types", params={"limit": 500}, headers=headers)
    ).json()
    kind = next(t for t in types["items"] if t["key"] == "wildlife")
    created = await client.post(
        f"/api/v1/projects/{project.id}/entities",
        json={"entity_type_id": kind["id"], "name": unique_name(name)},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _fixes(db, project, entity, device, source, *, n: int, east_bias: float, seed: int):
    """Hourly fixes in a box of about 3 km, their east-west place drawn with probability
    exp(east_bias * x); the canonical key carries the entity, so one device serves all."""
    rng = np.random.default_rng(seed)
    x = np.linspace(-1, 1, 200)
    weights = np.exp(east_bias * x)
    weights /= weights.sum()
    cols = rng.choice(200, size=n, p=weights)
    rows = []
    m_per_deg_lon = 111_320.0 * np.cos(np.radians(LAT))
    for i in range(n):
        when = T0 + timedelta(hours=i)
        lon = LON + (cols[i] - 100) * 15 / m_per_deg_lon + rng.uniform(-5, 5) / m_per_deg_lon
        lat = LAT + rng.uniform(-1500, 1500) / 111_320.0
        rows.append(
            Position(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=7000 + seed * 1000 + i,
                source_event_ingested_at=when,
                canonical_key=f"{entity['id']}|gnss|h{i}",
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
                satellites=9,
                accuracy_m=5.0,
            )
        )
    db.add_all(rows)
    await db.commit()


def _gradient_geotiff() -> bytes:
    """A gradient rising eastward over the fixes' box, 30 m pixels in UTM 33S."""
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG}", always_xy=True)
    cx, cy = to_utm.transform(LON, LAT)
    west, north = cx - 3000, cy + 3000
    width = height = 200
    grad = np.tile(np.linspace(-1, 1, width), (height, 1)).astype("float32")
    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs=f"EPSG:{EPSG}",
        transform=from_origin(west, north, 30, 30),
        nodata=-9999,
    ) as dst:
        dst.write(grad, 1)
    return buffer.getvalue()


async def _site(client, headers, project):
    """A site 3 km north of the fixes' box: its distance varies with northing, which the
    fixes are uniform in, so it explains nothing of the eastward selection (a site in the
    middle of the box would, since east is far from the middle)."""
    site = await client.post(
        f"/api/v1/projects/{project.id}/features",
        json={
            "feature_type": "site",
            "name": unique_name("Pan"),
            "geometry": {"type": "Point", "coordinates": [LON, LAT + 0.03]},
        },
        headers=headers,
    )
    assert site.status_code == 201, site.text


def _window(days: int = 10) -> dict[str, str]:
    return {"time_from": T0.isoformat(), "time_to": (T0 + timedelta(days=days)).isoformat()}


async def test_the_check_refuses_what_the_project_lacks(client, db):
    admin, project, rhino, _source, _device, _ = await _setup(client, db)
    base = f"/api/v1/projects/{project.id}/analyses"
    parameters = {"entity_ids": [rhino["id"]], "layers": ["ndvi"], **_window()}
    refused = await client.get(
        f"{base}/estimate",
        params={"module": "habitat_selection", "parameters": json.dumps(parameters)},
        headers=admin.headers,
    )
    assert refused.status_code == 200, refused.text
    assert not refused.json()["ok"]
    assert "No layer named ndvi" in refused.json()["reasons"][0]
    # a period in which the animal has fewer fixes than the fit needs is refused up front
    empty = {
        "entity_ids": [rhino["id"]],
        "layers": ["ndvi"],
        "time_from": (T0 - timedelta(days=30)).isoformat(),
        "time_to": (T0 - timedelta(days=20)).isoformat(),
    }
    refused = await client.get(
        f"{base}/estimate",
        params={"module": "habitat_selection", "parameters": json.dumps(empty)},
        headers=admin.headers,
    )
    assert refused.status_code == 200, refused.text
    assert any("needs 20 per animal" in r for r in refused.json()["reasons"])
    modules = (await client.get("/api/v1/analysis-modules", headers=admin.headers)).json()
    habitat = next(m for m in modules if m["key"] == "habitat_selection")
    assert habitat["limits"]["subjects"] == 40


@pytest.mark.skipif(_has_engine(), reason="the lean environment's refusal; the image runs it")
async def test_a_lean_worker_refuses_with_module_unavailable(client, db):
    admin, project, rhino, source, device, _ = await _setup(client, db)
    h = admin.headers
    await _fixes(db, project, rhino, device, source, n=60, east_bias=2.0, seed=1)
    await _site(client, h, project)
    parameters = {"entity_ids": [rhino["id"]], "layers": ["distance_to_site"], **_window()}
    created = await client.post(
        f"/api/v1/projects/{project.id}/analyses",
        json={"module": "habitat_selection", "parameters": parameters},
        headers=h,
    )
    assert created.status_code == 201, created.text
    run = await db.get(AnalysisRun, uuid.UUID(created.json()["id"]))
    await run_analysis(db, run)
    await db.refresh(run)
    assert run.status == "failed" and run.error_code == "MODULE_UNAVAILABLE"
    assert "analysis image" in (run.error_message or "")


@pytest.mark.skipif(not _has_engine(), reason="needs hrHSA, which the analysis image carries")
async def test_a_run_over_a_gradient_answers_coefficients_folds_and_cells(client, db):
    admin, project, rhino, source, device, _ = await _setup(client, db)
    h = admin.headers
    animals = [rhino] + [await _animal(client, h, project, f"Oryx {i}") for i in range(3)]
    for i, animal in enumerate(animals):
        await _fixes(db, project, animal, device, source, n=120, east_bias=2.0, seed=i + 1)
    await _site(client, h, project)
    uploaded = await client.post(
        f"/api/v1/projects/{project.id}/layers",
        params={"name": "greenness", "label": "Greenness"},
        files={"file": ("greenness.tif", _gradient_geotiff(), "image/tiff")},
        headers=h,
    )
    assert uploaded.status_code == 201, uploaded.text
    choices = (await client.get(f"/api/v1/projects/{project.id}/analysis-layers", headers=h)).json()
    assert {c["name"] for c in choices} >= {"greenness", "distance_to_site"}
    parameters = {
        "entity_ids": [a["id"] for a in animals],
        "layers": ["greenness", "distance_to_site"],
        "thin_hours": None,
        "area_buffer_m": 300,
        **_window(),
    }
    created = await client.post(
        f"/api/v1/projects/{project.id}/analyses",
        json={"module": "habitat_selection", "parameters": parameters},
        headers=h,
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    run = await db.get(AnalysisRun, run_id)
    await run_analysis(db, run)
    await db.refresh(run)
    assert run.status == "completed", (run.error_code, run.error_message)
    document = run.result
    tables = {t["key"]: t for t in document["tables"]}
    terms = {r[0]: r for r in tables["coefficients"]["rows"]}
    assert terms["greenness"][1] > 0 and terms["greenness"][4] > 0  # the lower bound above zero
    assert (
        terms["distance_to_site"][4] < 0 < terms["distance_to_site"][5]
    )  # the interval holds zero
    assert len(tables["validation"]["rows"]) == 4
    assert all(r[1] is not None and r[1] > 0.3 for r in tables["validation"]["rows"])
    layers = {r[0]: r for r in tables["layers"]["rows"]}
    assert layers["greenness"][2].startswith("uploaded GeoTIFF")
    assert layers["distance_to_site"][4] > 0
    assert document["summary"]["fleet"]["layers"] == 2
    assert document["summary"]["grid"]["epsg"] == EPSG
    assert {c["key"] for c in document["charts"]} == {"estimates", "boyce"}
    assert document["provenance"]["sources"][-1].startswith("hrHSA")
    kinds = (
        await db.execute(select(AnalysisGeometry.kind).where(AnalysisGeometry.run_id == run_id))
    ).scalars()
    counts: dict[str, int] = {}
    for kind in kinds:
        counts[kind] = counts.get(kind, 0) + 1
    assert counts["domain"] == 4 and counts["selection"] > 50
    assert document["geometries"] == counts
    geometries = await client.get(
        f"/api/v1/projects/{project.id}/analyses/{run_id}/geometries",
        params={"kind": "selection"},
        headers=h,
    )
    assert geometries.status_code == 200
    first = geometries.json()["features"][0]["properties"]
    assert {"value", "rank"} <= set(first)
