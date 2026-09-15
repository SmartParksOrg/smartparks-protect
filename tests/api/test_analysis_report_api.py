"""The PDF report of a run through the API (decision D211): asked for, made by the export
worker's handler, downloaded, and gone with the run."""

import json
import uuid
from datetime import timedelta

import pytest
from minio.error import S3Error

from shared.analysis.report import run_report_job
from shared.analysis.runner import run_analysis
from shared.config import get_settings
from shared.models import AnalysisRun
from shared.storage import get_object
from tests.api.test_analysis_movement_run import T0, _walk
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio


async def test_a_report_is_made_downloaded_and_removed_with_the_run(client, db):
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
    created = await client.post(base, json={"module": "movement", "parameters": params}, headers=h)
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])

    # no result yet: no report
    early = await client.post(f"{base}/{run_id}/report", headers=h)
    assert early.status_code == 409
    await run_analysis(db, await db.get(AnalysisRun, run_id))

    asked = await client.post(f"{base}/{run_id}/report", headers=h)
    assert asked.status_code == 200, asked.text
    assert asked.json()["report_status"] == "queued"
    again = await client.post(f"{base}/{run_id}/report", headers=h)
    assert again.status_code == 409  # being made
    not_yet = await client.get(f"{base}/{run_id}/report", headers=h)
    assert not_yet.status_code == 404

    await run_report_job({"run_id": str(run_id)})
    read = (await client.get(f"{base}/{run_id}", headers=h)).json()
    assert read["report_status"] == "ready", read.get("report_error")
    assert read["report_at"] is not None
    download = await client.get(f"{base}/{run_id}/report", headers=h)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content.startswith(b"%PDF")
    assert 'filename="movement-' in download.headers["content-disposition"]

    # the report can be made again, and a viewer of the project may read it once shared
    remade = await client.post(f"{base}/{run_id}/report", headers=h)
    assert remade.status_code == 200 and remade.json()["report_status"] == "queued"
    await run_report_job({"run_id": str(run_id)})

    key = (await db.get(AnalysisRun, run_id)).report_key
    assert key and await get_object(get_settings().minio_bucket_exports, key)
    deleted = await client.delete(f"{base}/{run_id}", headers=h)
    assert deleted.status_code == 204
    with pytest.raises(S3Error):
        await get_object(get_settings().minio_bucket_exports, key)
    assert json.loads((await client.get(f"{base}/{run_id}", headers=h)).text)["detail"]
