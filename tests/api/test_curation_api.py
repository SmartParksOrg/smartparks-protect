"""Data curation through the API (architecture 28, decisions D80 to D83): a single correction
and its effect on every reader, the approval switch, a bulk timestamp job with preview, apply
and revert, stale outbound deliveries with resend, and the export views."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.curation.jobs import apply_job, revert_job
from shared.enums import DeliveryOrigin, DeliveryStatus, Role
from shared.models import (
    DeviceProjectAssignment,
    Integration,
    IntegrationDelivery,
    Measurement,
    Metric,
    Position,
    Project,
)
from tests.api.conftest import project_actor
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 7, 1, 3, 14, tzinfo=UTC)


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _rows(db, project_id: str, device_id: str, entity_id: str, count: int = 3):
    """Positions and one measurement per hour from T0, attributed to the project and entity."""
    device, entity, project = uuid.UUID(device_id), uuid.UUID(entity_id), uuid.UUID(project_id)
    if await db.get(Metric, "battery_voltage") is None:
        db.add(
            Metric(
                key="battery_voltage",
                label="Battery",
                unit="V",
                value_type="number",
                category="device",
            )
        )
    positions, measurements = [], []
    for i in range(count):
        t = T0 + timedelta(hours=i)
        positions.append(
            Position(
                time=t,
                device_id=device,
                project_id=project,
                entity_id=entity,
                record_type="gnss",
                canonical_key=f"{device}:{t.isoformat()}:gnss",
                geom=WKTElement(f"POINT({31.5 + i * 0.001} -24.9)", srid=4326),
                accuracy_m=10.0,
            )
        )
        measurements.append(
            Measurement(
                time=t,
                device_id=device,
                project_id=project,
                entity_id=entity,
                metric_key="battery_voltage",
                canonical_key=f"{device}:{t.isoformat()}:battery_voltage",
                value_num=3.6 + i * 0.1,
            )
        )
    db.add_all(positions + measurements)
    await db.commit()
    return positions, measurements


async def test_single_corrections_flow_through_every_reader(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    positions, measurements = await _rows(db, str(project.id), device["id"], entity["id"])
    base = f"/api/v1/projects/{project.id}"
    curation = f"{base}/curation"
    summary = (await client.get(f"{curation}/summary", headers=h)).json()
    assert summary["requires_approval"] is False
    assert summary["curatable"] == {
        "measurement": ["time", "valid", "value"],
        "position": ["coordinates", "time", "valid"],
    }

    # time + 12 h on the first position: applied at once, visible on the positions list
    first = positions[0]
    corrected = (T0 + timedelta(hours=12)).isoformat()
    created = await client.post(
        f"{curation}/corrections",
        json={
            "target_type": "position",
            "target_id": first.id,
            "target_time": first.time.isoformat(),
            "field": "time",
            "corrected_value": corrected,
            "reason_code": "DEVICE_FIRMWARE_BUG",
            "comment": "firmware 6.12 clock bug",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    correction = created.json()
    assert correction["status"] == "active" and _t(correction["original_value"]) == T0
    assert correction["impact"]["attribution"]["after"]["project_id"] == str(project.id)
    window = {
        "from": (T0 - timedelta(hours=1)).isoformat(),
        "to": (T0 + timedelta(days=1)).isoformat(),
    }
    listed = (
        await client.get(
            f"{base}/positions", params={"device_id": device["id"], **window}, headers=h
        )
    ).json()
    by_id = {p["id"]: p for p in listed}
    assert (
        _t(by_id[first.id]["time"]) == _t(corrected) and _t(by_id[first.id]["original_time"]) == T0
    )
    assert (
        by_id[first.id]["curated_fields"] == ["time"] and by_id[first.id]["curation_version"] == 2
    )
    assert listed[0]["id"] == first.id  # newest by effective time
    # a window that only covers the original time no longer finds it
    early = (
        await client.get(
            f"{base}/positions",
            params={
                "device_id": device["id"],
                "from": (T0 - timedelta(hours=1)).isoformat(),
                "to": (T0 + timedelta(hours=1)).isoformat(),
            },
            headers=h,
        )
    ).json()
    assert first.id not in {p["id"] for p in early}
    track = (
        await client.get(f"{base}/tracks", params={"device_id": device["id"], **window}, headers=h)
    ).json()
    assert track["last_position_id"] == first.id and track["total_points"] == 3
    history = (
        await client.get(
            f"{curation}/history",
            params={
                "target_type": "position",
                "target_id": first.id,
                "target_time": first.time.isoformat(),
            },
            headers=h,
        )
    ).json()
    assert (
        _t(history["effective"]["time"]) == _t(corrected) and _t(history["original"]["time"]) == T0
    )
    assert [c["status"] for c in history["corrections"]] == ["active"]

    # the same value again is refused; a second correction on the field supersedes the first
    same = await client.post(
        f"{curation}/corrections",
        json={
            "target_type": "position",
            "target_id": first.id,
            "target_time": first.time.isoformat(),
            "field": "time",
            "corrected_value": corrected,
            "reason_code": "OTHER",
        },
        headers=h,
    )
    assert same.status_code == 422
    later = (T0 + timedelta(hours=13)).isoformat()
    second = (
        await client.post(
            f"{curation}/corrections",
            json={
                "target_type": "position",
                "target_id": first.id,
                "target_time": first.time.isoformat(),
                "field": "time",
                "corrected_value": later,
                "reason_code": "DEVICE_CLOCK_ERROR",
            },
            headers=h,
        )
    ).json()
    assert second["supersedes_id"] == correction["id"] and _t(second["original_value"]) == _t(
        corrected
    )
    assert (await client.get(f"{curation}/corrections/{correction['id']}", headers=h)).json()[
        "status"
    ] == "superseded"
    # the older one cannot be reverted while the newer is active
    assert (
        await client.post(f"{curation}/corrections/{correction['id']}/revert", json={}, headers=h)
    ).status_code == 409
    reverted = await client.post(
        f"{curation}/corrections/{second['id']}/revert", json={"comment": "wrong offset"}, headers=h
    )
    assert reverted.status_code == 200 and reverted.json()["status"] == "reverted"
    assert (await client.get(f"{curation}/corrections/{correction['id']}", headers=h)).json()[
        "status"
    ] == "active"
    listed = (
        await client.get(
            f"{base}/positions", params={"device_id": device["id"], **window}, headers=h
        )
    ).json()
    assert _t({p["id"]: p["time"] for p in listed}[first.id]) == _t(corrected)

    # validity hides a record from the readers, and the original view of an export keeps it
    last = positions[-1]
    hidden = await client.post(
        f"{curation}/corrections",
        json={
            "target_type": "position",
            "target_id": last.id,
            "target_time": last.time.isoformat(),
            "field": "valid",
            "corrected_value": False,
            "reason_code": "GPS_OUTLIER",
        },
        headers=h,
    )
    assert hidden.status_code == 201
    listed = (
        await client.get(
            f"{base}/positions", params={"device_id": device["id"], **window}, headers=h
        )
    ).json()
    assert last.id not in {p["id"] for p in listed}
    with_invalid = (
        await client.get(
            f"{base}/positions",
            params={"device_id": device["id"], "include_invalid": "true", **window},
            headers=h,
        )
    ).json()
    assert {p["id"]: p["valid"] for p in with_invalid}[last.id] is False
    effective = await client.get(
        f"{base}/exports/direct",
        params={
            "dataset": "positions",
            "format": "csv",
            "time_from": window["from"],
            "time_to": window["to"],
            "curation_metadata": "true",
        },
        headers=h,
    )
    assert effective.status_code == 200, effective.text
    lines = effective.text.strip().splitlines()
    assert "is_curated" in lines[0] and "original_time" in lines[0]
    assert len(lines) == 3  # header plus two valid positions
    original = await client.get(
        f"{base}/exports/direct",
        params={
            "dataset": "positions",
            "format": "csv",
            "time_from": window["from"],
            "time_to": (T0 + timedelta(hours=4)).isoformat(),
            "view": "original",
        },
        headers=h,
    )
    assert len(original.text.strip().splitlines()) == 4  # every row by original time, valid column

    # a measurement value correction shows in the analytics rows and in the series
    m = measurements[1]
    fixed = await client.post(
        f"{curation}/corrections",
        json={
            "target_type": "measurement",
            "target_id": m.id,
            "target_time": m.time.isoformat(),
            "field": "value",
            "corrected_value": 4.2,
            "reason_code": "CALIBRATION_ERROR",
        },
        headers=h,
    )
    assert fixed.status_code == 201, fixed.text
    rows = (
        await client.get(
            f"{base}/analytics/rows",
            params={"metric": "battery_voltage", "device_id": device["id"], **window},
            headers=h,
        )
    ).json()["items"]
    row = next(r for r in rows if r["id"] == m.id)
    assert (
        row["value"] == 4.2
        and row["original_value"] == pytest.approx(3.7)
        and row["curated_fields"] == ["value"]
    )
    series = (
        await client.get(
            f"{base}/analytics/series",
            params={"metric": "battery_voltage", "aggregate": "max", "bucket": "all", **window},
            headers=h,
        )
    ).json()
    assert series["series"][0]["points"][0]["values"]["max"] == pytest.approx(4.2)

    # viewers read but cannot curate
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    assert (await client.get(f"{curation}/corrections", headers=viewer.headers)).status_code == 200
    forbidden = await client.post(
        f"{curation}/corrections",
        json={
            "target_type": "position",
            "target_id": last.id,
            "target_time": last.time.isoformat(),
            "field": "valid",
            "corrected_value": True,
            "reason_code": "OTHER",
        },
        headers=viewer.headers,
    )
    assert forbidden.status_code == 403


async def test_approval_switch_and_four_eyes(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    positions, _ = await _rows(db, str(project.id), device["id"], entity["id"], count=1)
    curation = f"/api/v1/projects/{project.id}/curation"
    assert (
        await client.patch(
            f"/api/v1/projects/{project.id}",
            json={"settings": {"curation_requires_approval": True}},
            headers=h,
        )
    ).status_code == 200
    body = {
        "target_type": "position",
        "target_id": positions[0].id,
        "target_time": T0.isoformat(),
        "field": "valid",
        "corrected_value": False,
        "reason_code": "MANUAL_QC",
    }
    proposed = (await client.post(f"{curation}/corrections", json=body, headers=h)).json()
    assert proposed["status"] == "pending"
    row = await db.get(Position, (positions[0].id, T0))
    await db.refresh(row)
    assert row.valid is True  # nothing applied yet
    assert (
        await client.post(f"{curation}/corrections/{proposed['id']}/approve", headers=h)
    ).status_code == 409
    other = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    approved = await client.post(
        f"{curation}/corrections/{proposed['id']}/approve", headers=other.headers
    )
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    await db.refresh(row)
    assert row.valid is False
    summary = (await client.get(f"{curation}/summary", headers=h)).json()
    assert summary["requires_approval"] is True and summary["active_corrections"] == 1


async def test_bulk_time_shift_preview_apply_flag_and_revert(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    positions, _ = await _rows(db, str(project.id), device["id"], entity["id"], count=3)
    project_id = project.id
    # the device moves to another project at T0 + 13 h: a +12 h shift moves the records at
    # T0 + 1 h and T0 + 2 h there and leaves the first one
    other_project = Project(
        name=f"Other {uuid.uuid4().hex[:6]}", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db.add(other_project)
    await db.flush()
    assignment = await db.scalar(
        select(DeviceProjectAssignment).where(
            DeviceProjectAssignment.device_id == uuid.UUID(device["id"])
        )
    )
    from sqlalchemy.dialects.postgresql import Range

    handover = T0 + timedelta(hours=13)
    assignment.validity = Range(assignment.validity.lower, handover, bounds="[)")
    db.add(
        DeviceProjectAssignment(
            device_id=uuid.UUID(device["id"]),
            project_id=other_project.id,
            validity=Range(handover, None, bounds="[)"),
        )
    )
    # an integration that already delivered the first position (which stays in the project)
    integration = Integration(
        project_id=project_id,
        name="fake",
        connector_key="webhook",
        enabled=True,
        object_types=["position"],
        config={"url": "https://example.org/hook"},
    )
    db.add(integration)
    await db.flush()
    sent = IntegrationDelivery(
        integration_id=integration.id,
        project_id=project_id,
        object_type="position",
        object_id=str(positions[0].id),
        object_version=1,
        object_time=positions[0].time,
        entity_id=uuid.UUID(entity["id"]),
        device_id=uuid.UUID(device["id"]),
        origin=DeliveryOrigin.LIVE,
        status=DeliveryStatus.SENT,
        attempts=1,
        delivered_at=T0,
    )
    db.add(sent)
    await db.commit()

    curation = f"/api/v1/projects/{project_id}/curation"
    created = await client.post(
        f"{curation}/jobs",
        json={
            "target_type": "position",
            "device_ids": [device["id"]],
            "time_from": (T0 - timedelta(hours=1)).isoformat(),
            "time_to": (T0 + timedelta(hours=6)).isoformat(),
            "transformation": {"kind": "time_offset", "seconds": 12 * 3600},
            "reason_code": "DEVICE_FIRMWARE_BUG",
            "comment": "firmware v6.12 timestamp bug",
            "replay_rules": True,
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    job = created.json()
    assert job["status"] == "previewed" and job["affected_count"] == 3
    preview = job["preview"]
    assert preview["transformation"] == "time + 43200 s" and len(preview["samples"]) == 3
    assert _t(preview["samples"][0]["after"]) == T0 + timedelta(hours=12)
    assert preview["impact"] == {
        "scanned": 3,
        "estimated": False,
        "attribution_changes": 2,
        "deliveries_sent": 1,
        "enabled_rules": 0,
    }

    applied = await client.post(f"{curation}/jobs/{job['id']}/apply", headers=h)
    assert applied.status_code == 200 and applied.json()["status"] == "applying"
    await apply_job(uuid.UUID(job["id"]), user_id=admin.user.id)  # what the batch worker does
    done = (await client.get(f"{curation}/jobs/{job['id']}", headers=h)).json()
    assert done["status"] == "applied", done
    assert done["applied_count"] == 3 and done["impact"]["deliveries_flagged"] == 1
    assert done["replay_rules"] is True and done["impact"]["replay"]["rules"] == []
    # attribution moved for the last record, the others stayed
    for row in positions:
        await db.refresh(row)
    assert positions[2].project_id == other_project.id and positions[
        2
    ].curated_time == T0 + timedelta(hours=14)
    assert positions[1].project_id == other_project.id
    assert positions[0].project_id == project_id and positions[0].curated_fields == ["time"]
    # the delivery is stale and can be resent as version 2
    stale = (
        await client.get(
            f"/api/v1/projects/{project_id}/integrations/deliveries",
            params={"stale": "true"},
            headers=h,
        )
    ).json()["items"]
    assert [d["id"] for d in stale] == [str(sent.id)] and "time corrected" in stale[0][
        "stale_reason"
    ]
    resent = await client.post(
        f"/api/v1/projects/{project_id}/integrations/deliveries/{sent.id}/resend", headers=h
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["object_version"] == 2 and resent.json()["status"] == "queued"
    assert (
        await client.get(
            f"/api/v1/projects/{project_id}/integrations/deliveries",
            params={"stale": "true"},
            headers=h,
        )
    ).json()["items"] == []
    corrections = (
        await client.get(f"{curation}/corrections", params={"job_id": job["id"]}, headers=h)
    ).json()["items"]
    assert len(corrections) == 3 and all(c["status"] == "active" for c in corrections)

    # revert brings every record back, attribution included
    reverting = await client.post(
        f"{curation}/jobs/{job['id']}/revert", json={"comment": "offset was wrong"}, headers=h
    )
    assert reverting.status_code == 200 and reverting.json()["status"] == "reverting"
    await revert_job(uuid.UUID(job["id"]), user_id=admin.user.id, comment="offset was wrong")
    done = (await client.get(f"{curation}/jobs/{job['id']}", headers=h)).json()
    assert done["status"] == "reverted" and done["reverted_count"] == 3
    for row in positions:
        await db.refresh(row)
    assert all(
        r.curated_time is None and r.curated_fields == [] and r.project_id == project_id
        for r in positions
    )
    summary = (await client.get(f"{curation}/summary", headers=h)).json()
    assert summary["reverted_corrections"] == 3 and summary["jobs"] == {"reverted": 1}
