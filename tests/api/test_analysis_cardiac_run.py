"""The cardiac module over real rows (phase 34): the API refuses a period with no readings,
creates the run over a day of them, and the runner computes what the document promises.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.analysis.runner import run_analysis
from shared.models import AnalysisRun, Measurement
from shared.models.settings import DeviceSetting
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
NIGHT_BPM = 42.0
DAY_BPM = 78.0
REPORTING_INTERVAL_S = 900  # the collar composes a message every fifteen minutes


def _measurement(project, entity, device, source, at, key, index, *, num=None, flag=None):
    return Measurement(
        time=at,
        device_id=uuid.UUID(device["id"]),
        project_id=project.id,
        entity_id=uuid.UUID(entity["id"]),
        data_source_id=uuid.UUID(source["id"]),
        source_event_id=7000 + index,
        source_event_ingested_at=at,
        metric_key=key,
        canonical_key=f"{device['id']}|cmdq|{key}|{index}",
        value_num=num,
        value_bool=flag,
    )


async def _a_day_of_readings(db, project, entity, device, source):
    """Every fifteen minutes for a day: a slow heart at night and a faster one by day, one
    sighting that carried no reading, and one impossible value that must not reach a figure."""
    rows = []
    index = 0
    for step in range(96):
        at = T0 + timedelta(minutes=15 * step)
        heard = True
        bpm = NIGHT_BPM if at.hour < 6 else DAY_BPM
        if step == 40:  # the tag was heard and had nothing to say
            heard = False
            bpm = None
        rows.append(
            _measurement(project, entity, device, source, at, "cmdq_success", index, flag=heard)
        )
        index += 1
        if bpm is not None:
            rows.append(
                _measurement(project, entity, device, source, at, "heart_rate", index, num=bpm)
            )
            index += 1
            rows.append(
                _measurement(
                    project, entity, device, source, at, "heart_rate_variability", index, num=48.0
                )
            )
            index += 1
            rows.append(
                _measurement(
                    project, entity, device, source, at, "cmdq_temperature", index, num=38.4
                )
            )
            index += 1
    # 6000 / 1, the arithmetic of a single byte and not a heartbeat
    rows.append(
        _measurement(
            project,
            entity,
            device,
            source,
            T0 + timedelta(hours=12),
            "heart_rate",
            index,
            num=6000.0,
        )
    )
    rows.append(
        DeviceSetting(
            device_id=uuid.UUID(device["id"]),
            key="cmdq_reporting_interval",
            value=REPORTING_INTERVAL_S,  # JSONB: the number the device reported
            source="frame",
            observed_at=T0,
        )
    )
    db.add_all(rows)
    await db.commit()


def _params(**extra):
    return {
        "time_from": T0.isoformat(),
        "time_to": (T0 + timedelta(days=1)).isoformat(),
        **extra,
    }


async def test_an_estimate_refuses_a_period_without_a_single_reading(client, db):
    admin, project, entity, _source, _device, _ = await _setup(client, db)
    estimate = await client.get(
        f"/api/v1/projects/{project.id}/analyses/estimate",
        params={
            "module": "cardiac",
            "parameters": json.dumps(_params(entity_ids=[entity["id"]])),
        },
        headers=admin.headers,
    )
    assert estimate.status_code == 200, estimate.text
    body = estimate.json()
    assert body["ok"] is False
    assert any("No cardiac readings" in reason for reason in body["reasons"])


async def test_a_cardiac_run_over_a_day_of_readings(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _a_day_of_readings(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/analyses"
    params = _params(entity_ids=[entity["id"]])

    estimate = await client.get(
        f"{base}/estimate",
        params={"module": "cardiac", "parameters": json.dumps(params)},
        headers=admin.headers,
    )
    assert estimate.status_code == 200 and estimate.json()["ok"], estimate.text

    created = await client.post(
        base, json={"module": "cardiac", "parameters": params}, headers=admin.headers
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])

    await run_analysis(db, await db.get(AnalysisRun, run_id))
    read = await client.get(f"{base}/{run_id}", headers=admin.headers)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "completed", (body["error_code"], body["error_message"])
    document = body["result"]
    figures = document["summary"]["subjects"][entity["id"]]

    # what was heard, before what the heart did
    seen = figures["coverage"]
    assert seen["heard"] == 96
    assert seen["with_reading"] == 95
    assert seen["expected"] == 96  # a day at a message every fifteen minutes
    assert seen["reading_share"] == pytest.approx(95 / 96, abs=0.001)

    # the impossible reading is out of every figure and counted
    assert figures["dropped_implausible"] == 1
    assert figures["heart_rate"]["n"] == 95
    assert figures["heart_rate"]["highest"] == DAY_BPM

    # the rhythm is read per hour of the local day, and the resting rate off the quiet hours
    by_hour = {point["hour"]: point["median"] for point in figures["by_hour"]}
    assert by_hour[3] == NIGHT_BPM and by_hour[12] == DAY_BPM
    assert figures["resting_heart_rate"] == NIGHT_BPM
    assert figures["hrv"]["median"] == 48.0
    assert figures["tag_temperature"]["median"] == 38.4

    # the settings that produced the resting figure travel with it
    assert document["summary"]["settings"]["quiet_hours"] == [0, 5]
    assert document["summary"]["settings"]["resting_quantile"] == 0.1

    assert [t["key"] for t in document["tables"]] == ["cardiac", "coverage"]
    assert [c["key"] for c in document["charts"]] == ["rhythm"]
    assert document["subjects"][0]["name"] == "Rhino 14"
    codes = {w["code"] for w in document["warnings"]}
    assert "implausible_dropped" in codes
    assert "nothing_heard" not in codes


async def test_a_subject_heard_without_a_single_reading_says_so(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    rows = [
        _measurement(
            project,
            entity,
            device,
            source,
            T0 + timedelta(minutes=15 * step),
            "cmdq_success",
            step,
            flag=False,
        )
        for step in range(20)
    ]
    db.add_all(rows)
    await db.commit()
    base = f"/api/v1/projects/{project.id}/analyses"
    created = await client.post(
        base,
        json={"module": "cardiac", "parameters": _params(entity_ids=[entity["id"]])},
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    await run_analysis(db, await db.get(AnalysisRun, run_id))
    document = (await client.get(f"{base}/{run_id}", headers=admin.headers)).json()["result"]
    codes = {w["code"] for w in document["warnings"]}
    assert "heard_without_readings" in codes
    figures = document["summary"]["subjects"][entity["id"]]
    assert figures["coverage"]["heard"] == 20 and figures["coverage"]["with_reading"] == 0
    assert "heart_rate" not in figures
