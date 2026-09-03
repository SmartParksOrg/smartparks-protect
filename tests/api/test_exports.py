"""Export jobs and direct exports through the API, the job run by the export runner."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement

from shared.exports import runner
from shared.exports.runner import run_export
from shared.models import ExportJob, Measurement, Position
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
FROM, TO = "2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z"


async def _rows(db, project, entity, device, source, count: int = 5):
    for i in range(count):
        when = T0 + timedelta(minutes=10 * i)
        db.add(
            Position(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=500 + i,
                source_event_ingested_at=when,
                canonical_key=f"{device['id']}|gnss|{i}",
                geom=WKTElement(f"POINT({31.5 + i * 0.001} {-24.9 - i * 0.001})", srid=4326),
                altitude_m=300.0 + i,
                attributes={"fix_type": 3},
            )
        )
        db.add(
            Measurement(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                metric_key="battery_voltage",
                canonical_key=f"{device['id']}|battery_voltage|{i}",
                value_num=3.5 + i * 0.01,
            )
        )
    await db.commit()


async def test_job_runs_to_minio_and_downloads(client, db, monkeypatch):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _rows(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/exports"
    created = await client.post(
        base,
        json={
            "dataset": "positions",
            "format": "csv",
            "time_from": FROM,
            "time_to": TO,
            "timezone": "Africa/Johannesburg",
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["status"] == "queued" and job["parameters"]["timezone"] == "Africa/Johannesburg"
    not_ready = await client.get(f"{base}/{job['id']}/download", headers=admin.headers)
    assert not_ready.status_code == 409

    # the export service does this on `export.requested`; progress every two rows exercises the
    # progress path while the server-side cursor is open
    monkeypatch.setattr(runner, "PROGRESS_EVERY", 2)
    await run_export(db, await db.get(ExportJob, uuid.UUID(job["id"])))

    done = (await client.get(f"{base}/{job['id']}", headers=admin.headers)).json()
    assert done["status"] == "done", done
    assert done["row_count"] == 5 and done["size_bytes"] > 0 and len(done["sha256"]) == 64
    assert (
        done["metadata"]["row_count"] == 5 and done["metadata"]["timezone"] == "Africa/Johannesburg"
    )
    download = await client.get(f"{base}/{job['id']}/download", headers=admin.headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.headers["x-content-sha256"] == done["sha256"]
    rows = list(csv.DictReader(io.StringIO(download.text)))
    assert len(rows) == 5
    assert rows[0]["time"] == "2026-04-01T02:00:00+02:00"  # requested zone
    assert rows[0]["entity_name"] == "Rhino 14" and rows[0]["latitude"] == "-24.9"
    assert json.loads(rows[0]["attributes"]) == {"fix_type": 3}

    listed = (await client.get(base, headers=admin.headers)).json()
    assert [j["id"] for j in listed["items"]] == [job["id"]]

    reproduced = await client.post(f"{base}/{job['id']}/reproduce", headers=admin.headers)
    assert reproduced.status_code == 201
    assert reproduced.json()["source_job_id"] == job["id"]
    assert reproduced.json()["parameters"] == job["parameters"]


async def test_direct_exports_every_dataset(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _rows(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/exports/direct"
    window = f"time_from={FROM}&time_to={TO}"

    gpx = await client.get(f"{base}?dataset=positions&format=gpx&{window}", headers=admin.headers)
    assert gpx.status_code == 200, gpx.text
    assert gpx.headers["content-type"].startswith("application/gpx+xml")
    assert gpx.text.count("<trkpt") == 5 and "<name>Rhino 14</name>" in gpx.text
    assert 'filename="positions-20260401-20260402.gpx"' in gpx.headers["content-disposition"]

    geojson = (
        await client.get(f"{base}?dataset=positions&format=geojson&{window}", headers=admin.headers)
    ).json()
    assert len(geojson["features"]) == 5 and geojson["metadata"]["timezone"] == "UTC"

    measurements = await client.get(
        f"{base}?dataset=measurements&format=json&{window}&metric_keys=battery_voltage",
        headers=admin.headers,
    )
    body = measurements.json()
    assert len(body["rows"]) == 5 and body["rows"][0]["unit"] == "V"
    assert body["metadata"]["metrics"]["battery_voltage"]["label"] == "Battery voltage"

    xlsx = await client.get(
        f"{base}?dataset=measurements&format=xlsx&{window}", headers=admin.headers
    )
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

    aggregates = await client.get(
        f"{base}?dataset=aggregates&format=csv&{window}&metric_keys=battery_voltage&bucket=1h",
        headers=admin.headers,
    )
    assert aggregates.status_code == 200, aggregates.text
    rows = list(csv.DictReader(io.StringIO(aggregates.text)))
    assert len(rows) == 1 and rows[0]["count"] == "5" and rows[0]["entity_name"] == "Rhino 14"

    wide = await client.get(
        f"{base}?dataset=aggregates&format=csv&{window}&metric_keys=battery_voltage"
        f"&bucket=1h&layout=wide&entity_ids={entity['id']}&aggregates=mean&aggregates=count",
        headers=admin.headers,
    )
    rows = list(csv.DictReader(io.StringIO(wide.text)))
    assert list(rows[0]) == [
        "time",
        f"battery_voltage|{entity['id']}|mean",
        f"battery_voltage|{entity['id']}|count",
    ]

    raw = await client.get(
        f"{base}?dataset=source_events&format=csv&{window}", headers=admin.headers
    )
    assert raw.status_code == 200 and raw.text.startswith("ingested_at,")


async def test_direct_export_bounds_and_validation(client, db, monkeypatch):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _rows(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/exports"
    window = f"time_from={FROM}&time_to={TO}"

    monkeypatch.setattr(runner, "DIRECT_MAX_ROWS", 2)
    too_big = await client.get(
        f"{base}/direct?dataset=positions&format=csv&{window}", headers=admin.headers
    )
    assert too_big.status_code == 413 and "export job" in too_big.text

    wrong_format = await client.post(
        base,
        json={"dataset": "measurements", "format": "gpx", "time_from": FROM, "time_to": TO},
        headers=admin.headers,
    )
    assert wrong_format.status_code == 422 and "measurements exports support" in wrong_format.text
    bad_zone = await client.post(
        base,
        json={
            "dataset": "positions",
            "format": "csv",
            "time_from": FROM,
            "time_to": TO,
            "timezone": "Mars/Olympus",
        },
        headers=admin.headers,
    )
    assert bad_zone.status_code == 422
    naive = await client.post(
        base,
        json={
            "dataset": "positions",
            "format": "csv",
            "time_from": "2026-04-01T00:00:00",
            "time_to": TO,
        },
        headers=admin.headers,
    )
    assert naive.status_code == 422

    from tests.api.conftest import actor

    outsider = await actor(client, db)
    assert (
        await client.get(
            f"{base}/direct?dataset=positions&format=csv&{window}", headers=outsider.headers
        )
    ).status_code == 403
