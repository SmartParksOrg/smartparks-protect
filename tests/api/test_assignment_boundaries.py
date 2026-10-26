"""Assignment boundaries moved after the fact (decisions D355 to D358), on the case that
asked for it: SP051307 was moved from Smart Parks to Smart Parks - LP0 and from entity Tim
to entity SP051307 "from now" on 2026-10-26, while it changed hands a day earlier, one
second after its last KPN uplink. The fixture here is that timeline in the test database:
a device with three records, in a project on an entity since its first data, moved from now
to a second project and put on a new entity there, so one project row and one entity row
end at the transfer's instant and the next two start there. The intended boundary lies
between the second and the third record, so the third changes hands."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from shared.enums import Role
from shared.models import AuditLog, Position, SourceEvent
from tests.api.conftest import create_project, project_actor
from tests.api.test_attribution_repair import _finish_jobs
from tests.api.test_moves import _entity_type, _in_project_since_first_data

pytestmark = pytest.mark.asyncio

BOUNDARY = "2026-05-04T12:00:00+00:00"


@pytest_asyncio.fixture
async def bus():
    from shared.bus import RedisStreamsBus

    bus = RedisStreamsBus()
    yield bus
    await bus.close()


async def _transferred_from_now(client, db, bus):
    """The SP051307 shape: `old` row [first data, transfer) and `new` row [transfer, open) for
    the project; `tim` row and `sp` row the same for the entity."""
    admin, old, device, tim_id, _first = await _in_project_since_first_data(client, db, bus)
    h = admin.headers
    new = await create_project(db)
    moved = await client.post(
        "/api/v1/devices/move",
        json={"device_ids": [device["id"]], "project_id": str(new.id), "start": "now"},
        headers=h,
    )
    assert moved.status_code == 200, moved.text
    timeline = (await client.get(f"/api/v1/devices/{device['id']}/assignments", headers=h)).json()
    [old_row, new_row] = timeline["project_assignments"]
    transfer = new_row["valid_from"]
    assert old_row["valid_to"] == transfer
    entity_type = await _entity_type(client, h)
    tracked = await client.post(
        f"/api/v1/projects/{new.id}/entity-assignments",
        json={
            "device_id": device["id"],
            "valid_from": transfer,
            "new_entity": {"name": "SP051307", "entity_type_id": entity_type["id"]},
        },
        headers=h,
    )
    assert tracked.status_code == 201, tracked.text
    await _finish_jobs(client, device["id"], h)
    timeline = (await client.get(f"/api/v1/devices/{device['id']}/assignments", headers=h)).json()
    [tim_row, sp_row] = timeline["entity_assignments"]
    assert tim_row["entity_id"] == tim_id and tim_row["valid_to"] == transfer
    assert sp_row["valid_from"] == transfer and sp_row["valid_to"] is None
    return admin, old, new, device, timeline, transfer


async def _positions(db, device_id):
    rows = (
        await db.scalars(
            select(Position).where(Position.device_id == device_id).order_by(Position.time)
        )
    ).all()
    return [(p.time.day, p.project_id, p.entity_id) for p in rows]


async def _raw_count(db, device_id) -> int:
    return int(
        await db.scalar(
            select(func.count()).select_from(SourceEvent).where(SourceEvent.device_id == device_id)
        )
        or 0
    )


async def test_the_timeline_read_carries_jobs_changes_and_rights(client, db, bus):
    _admin, old, new, device, timeline, _transfer = await _transferred_from_now(client, db, bus)
    assert timeline["device_id"] == device["id"]
    assert timeline["can_edit_project"] and timeline["can_edit_entity"]
    assert timeline["active_job"] is None
    [old_row, new_row] = timeline["project_assignments"]
    assert old_row["project_id"] == str(old.id) and new_row["project_id"] == str(new.id)
    # the assignment's job over the May records touched the old row; nothing lay in the
    # move's window from now, so the new row has none
    assert old_row["attribution_job"]["status"] == "complete"
    assert new_row["attribution_job"] is None
    [_tim_row, sp_row] = timeline["entity_assignments"]
    assert sp_row["last_change"]["action"] == "entity_assignment.created"
    assert sp_row["last_change"]["user_name"]
    # a viewer of the new project reads the timeline and may edit nothing
    viewer = await project_actor(client, db, new, Role.PROJECT_VIEWER)
    seen = (
        await client.get(f"/api/v1/devices/{device['id']}/assignments", headers=viewer.headers)
    ).json()
    assert not seen["can_edit_project"] and not seen["can_edit_entity"]
    # the viewer of the new project sees that project's rows alone
    assert [r["project_id"] for r in seen["project_assignments"]] == [str(new.id)]


async def test_the_combined_correction_moves_four_rows_and_queues_one_job(client, db, bus):
    admin, old, new, device, timeline, transfer = await _transferred_from_now(client, db, bus)
    h = admin.headers
    device_id = uuid.UUID(device["id"])
    old_id, new_id = old.id, new.id  # read before a rollback expires the rows
    [old_row, new_row] = timeline["project_assignments"]
    [tim_row, sp_row] = timeline["entity_assignments"]
    raw_before = await _raw_count(db, device_id)
    await db.rollback()
    body = {
        "project_assignment_id": new_row["id"],
        "entity_assignment_id": sp_row["id"],
        "instant": BOUNDARY,
        "reason": "one second after the last KPN uplink",
    }
    # the preview says what moves and writes nothing
    preview = await client.post(
        f"/api/v1/devices/{device['id']}/assignments/correct",
        json={**body, "preview": True},
        headers=h,
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["preview"] and plan["attribution_job"] is None
    assert {(c["kind"], c["assignment_id"], c["edge"]) for c in plan["changes"]} == {
        ("project", new_row["id"], "start"),
        ("project", old_row["id"], "end"),
        ("entity", sp_row["id"], "start"),
        ("entity", tim_row["id"], "end"),
    }
    assert all(
        c["old"] == transfer and c["new"].startswith("2026-05-04T12:00:00") for c in plan["changes"]
    )
    assert plan["window_from"].startswith("2026-05-04T12:00:00") and plan["window_to"] == transfer
    assert plan["gap"] is None
    assert plan["timeline"]["project_assignments"][1]["valid_from"] == transfer

    done = await client.post(
        f"/api/v1/devices/{device['id']}/assignments/correct", json=body, headers=h
    )
    assert done.status_code == 200, done.text
    result = done.json()
    assert not result["preview"]
    job = result["attribution_job"]
    assert job is not None and job["status"] == "queued"
    assert job["time_from"].startswith("2026-05-04T12:00:00") and job["time_to"] == transfer
    assert job["reason"] == "assignment.boundary_moved" and job["records_total"] == 2
    # (a) all four rows carry the new boundary
    rows = result["timeline"]
    assert rows["project_assignments"][0]["valid_to"].startswith("2026-05-04T12:00:00")
    assert rows["project_assignments"][1]["valid_from"].startswith("2026-05-04T12:00:00")
    assert rows["entity_assignments"][0]["valid_to"].startswith("2026-05-04T12:00:00")
    assert rows["entity_assignments"][1]["valid_from"].startswith("2026-05-04T12:00:00")
    for row in rows["project_assignments"] + rows["entity_assignments"]:
        assert row["last_change"]["reason"] == "one second after the last KPN uplink"
        assert row["last_change"]["action"].endswith("assignment.boundary_moved")
        assert row["attribution_job"]["id"] == job["id"]
    assert rows["active_job"]["id"] == job["id"]
    # (b) the job rewrote the records of the window: the third record changed hands
    jobs = await _finish_jobs(client, device["id"], h)
    assert jobs[0]["status"] == "complete"
    await db.rollback()
    tim_id, sp_id = uuid.UUID(tim_row["entity_id"]), uuid.UUID(sp_row["entity_id"])
    assert await _positions(db, device_id) == [
        (3, old_id, tim_id),
        (4, old_id, tim_id),
        (5, new_id, sp_id),
    ]
    # (c) the raw messages are untouched
    assert await _raw_count(db, device_id) == raw_before
    audits = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.action.in_(
                    ["project_assignment.boundary_moved", "entity_assignment.boundary_moved"]
                ),
                AuditLog.details["device_id"].as_string() == device["id"],
            )
        )
    ).all()
    assert len(audits) == 4
    assert {a.details["to"][:19] for a in audits} == {"2026-05-04T12:00:00"}
    assert all(
        datetime.fromisoformat(a.details["from"]) == datetime.fromisoformat(transfer)
        for a in audits
    )


async def test_refusals_come_as_422_in_words(client, db, bus):
    admin, _old, _new, device, timeline, transfer = await _transferred_from_now(client, db, bus)
    h = admin.headers
    [_old_row, new_row] = timeline["project_assignments"]
    [_tim_row, sp_row] = timeline["entity_assignments"]
    url = f"/api/v1/devices/{device['id']}/project-assignments/{new_row['id']}/boundary"
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    refused = await client.patch(url, json={"valid_from": future, "reason": "x"}, headers=h)
    assert refused.status_code == 422 and "future" in refused.json()["detail"]
    # before the previous row's start: it would be left empty
    refused = await client.patch(
        url, json={"valid_from": "2026-04-01T00:00:00+00:00", "reason": "x"}, headers=h
    )
    assert refused.status_code == 422 and "previous assignment empty" in refused.json()["detail"]
    # in Dutch for a Dutch reader
    refused = await client.patch(
        url,
        json={"valid_from": "2026-04-01T00:00:00+00:00", "reason": "x"},
        headers={**h, "Accept-Language": "nl"},
    )
    assert refused.status_code == 422 and "vorige toewijzing" in refused.json()["detail"]
    # the entity boundary alone cannot leave the project rows: the new entity's row would
    # start while the device was still in the old project
    refused = await client.patch(
        f"/api/v1/devices/{device['id']}/entity-assignments/{sp_row['id']}/boundary",
        json={"valid_from": BOUNDARY, "reason": "x"},
        headers=h,
    )
    assert refused.status_code == 422 and "entity's project" in refused.json()["detail"]
    # a reason is required, and so is an edge
    assert (await client.patch(url, json={"valid_from": BOUNDARY}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"reason": "x"}, headers=h)).status_code == 422
    # the same instant changes nothing and says so
    same = await client.patch(url, json={"valid_from": transfer, "reason": "x"}, headers=h)
    assert same.status_code == 200 and same.json()["changes"] == []


async def test_a_single_boundary_moves_with_its_neighbour_and_rights_are_checked(client, db, bus):
    admin, _old, new, device, timeline, transfer = await _transferred_from_now(client, db, bus)
    h = admin.headers
    [old_row, new_row] = timeline["project_assignments"]
    [tim_row, sp_row] = timeline["entity_assignments"]
    earlier = (datetime.fromisoformat(transfer) - timedelta(minutes=5)).isoformat()
    # a project admin of the new project alone may not move a boundary the old project shares
    new_admin = await project_actor(client, db, new, Role.PROJECT_ADMIN)
    refused = await client.patch(
        f"/api/v1/devices/{device['id']}/project-assignments/{new_row['id']}/boundary",
        json={"valid_from": earlier, "reason": "x"},
        headers=new_admin.headers,
    )
    assert refused.status_code == 403
    # an operator of the new project has devices:write there, but the combined correction
    # names a project row too, which needs a project admin: refused before anything is planned
    operator = await project_actor(client, db, new, Role.PROJECT_OPERATOR)
    refused = await client.post(
        f"/api/v1/devices/{device['id']}/assignments/correct",
        json={
            "project_assignment_id": new_row["id"],
            "entity_assignment_id": sp_row["id"],
            "instant": earlier,
            "reason": "x",
        },
        headers=operator.headers,
    )
    assert refused.status_code == 403
    # the server admin moves the project boundary five minutes earlier: the old row shrinks,
    # the new one grows, no record changes hands (none lies in the window), no job
    moved = await client.patch(
        f"/api/v1/devices/{device['id']}/project-assignments/{old_row['id']}/boundary",
        json={"valid_to": earlier, "reason": "the handover was earlier"},
        headers=h,
    )
    assert moved.status_code == 200, moved.text
    result = moved.json()
    assert result["attribution_job"] is None and result["gap"] is None
    assert {(c["assignment_id"], c["edge"]) for c in result["changes"]} == {
        (old_row["id"], "end"),
        (new_row["id"], "start"),
    }
    rows = result["timeline"]["project_assignments"]
    assert rows[0]["valid_to"] == rows[1]["valid_from"]
    assert datetime.fromisoformat(rows[1]["valid_from"]) == datetime.fromisoformat(earlier)
    # the entity rows did not move and now straddle the project boundary: the correction of
    # both at once puts them back in step
    corrected = await client.post(
        f"/api/v1/devices/{device['id']}/assignments/correct",
        json={
            "project_assignment_id": new_row["id"],
            "entity_assignment_id": sp_row["id"],
            "instant": earlier,
            "reason": "in step",
        },
        headers=h,
    )
    assert corrected.status_code == 200, corrected.text
    assert {c["assignment_id"] for c in corrected.json()["changes"]} == {
        tim_row["id"],
        sp_row["id"],
    }


async def test_the_last_message_before_an_instant_is_offered_one_second_later(client, db, bus):
    admin, _old, _new, device, _timeline, transfer = await _transferred_from_now(client, db, bus)
    h = admin.headers
    found = await client.get(
        f"/api/v1/devices/{device['id']}/last-message", params={"before": transfer}, headers=h
    )
    assert found.status_code == 200, found.text
    last = found.json()
    assert last["time"] is not None and last["acquisition_channel"] == "api"
    assert datetime.fromisoformat(last["snap_to"]) == datetime.fromisoformat(
        last["time"]
    ) + timedelta(seconds=1)
    nothing = await client.get(
        f"/api/v1/devices/{device['id']}/last-message",
        params={"before": "2020-01-01T00:00:00+00:00"},
        headers=h,
    )
    assert nothing.json() == {
        "time": None,
        "snap_to": None,
        "acquisition_channel": None,
        "data_source_name": None,
    }
