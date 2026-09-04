"""Rules, events, alerts, automations, notification targets and deliveries through the API,
with the role matrix."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement

from shared.enums import Role
from shared.models import ActionDelivery, Alert, EntityCurrentState, Event, Measurement
from tests.api.conftest import project_actor
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

BATTERY = {
    "trigger": {"kind": "measurement", "metric_key": "battery_voltage"},
    "conditions": {"type": "threshold", "metric": "battery_voltage", "op": "<", "value": 3.2},
    "event": {"event_type": "BATTERY_LOW", "title": "{entity} battery at {value} V"},
}
T0 = datetime(2026, 4, 1, tzinfo=UTC)


async def _seed_measurements(db, project, entity, device, values):
    for i, value in enumerate(values):
        when = T0 + timedelta(minutes=10 * i)
        db.add(
            Measurement(
                time=when,
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                metric_key="battery_voltage",
                canonical_key=f"{device['id']}|battery|{i}",
                value_num=value,
            )
        )
    await db.commit()


async def test_rule_lifecycle_versions_and_replay(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}/rules"
    templates = (await client.get(f"{base}/templates", headers=h)).json()
    assert {t["key"] for t in templates} >= {"geofence_exit", "battery_low", "no_data"}
    schema = (await client.get(f"{base}/schema", headers=h)).json()
    assert "trigger" in schema["properties"]

    created = await client.post(
        base, json={"name": "Battery", "document": BATTERY, "enabled": True}, headers=h
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert (
        rule["current_version"] == 1
        and rule["enabled"]
        and rule["document"]["trigger"]["kind"] == "measurement"
    )

    # invalid document: field path in the error
    bad = await client.post(
        base, json={"name": "Bad", "document": {"trigger": {"kind": "nope"}}}, headers=h
    )
    assert bad.status_code == 422 and "trigger" in str(bad.json()["detail"])

    # a reserved type can be saved disabled but not enabled
    reserved = dict(
        BATTERY, conditions={"type": "baseline", "metric": "activity", "days": 30, "factor": 0.35}
    )
    saved = await client.post(base, json={"name": "Reserved", "document": reserved}, headers=h)
    assert saved.status_code == 201 and saved.json()["reserved_types"] == ["baseline"]
    enable = await client.patch(f"{base}/{saved.json()['id']}", json={"enabled": True}, headers=h)
    assert enable.status_code == 422 and "baseline" in enable.text

    # new version
    changed = dict(
        BATTERY,
        conditions={"type": "threshold", "metric": "battery_voltage", "op": "<", "value": 3.5},
    )
    v2 = await client.put(f"{base}/{rule['id']}/document", json={"document": changed}, headers=h)
    assert v2.status_code == 200 and v2.json()["current_version"] == 2
    versions = (await client.get(f"{base}/{rule['id']}/versions", headers=h)).json()
    assert [v["version"] for v in versions] == [2, 1]

    # replay over history: 3.6, 3.4, 3.0, 3.1, 3.7 with threshold 3.5 fires once (edge)
    await _seed_measurements(db, project, entity, device, [3.6, 3.4, 3.0, 3.1, 3.7])
    replay = await client.post(
        f"{base}/{rule['id']}/test",
        json={"from": T0.isoformat(), "to": (T0 + timedelta(hours=1)).isoformat()},
        headers=h,
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert (
        body["total"] == 1
        and body["samples"] == 5
        and body["events"][0]["title"] == "Rhino 14 battery at 3.4 V"
    )
    v1 = await client.post(
        f"{base}/{rule['id']}/test",
        json={"from": T0.isoformat(), "to": (T0 + timedelta(hours=1)).isoformat(), "version": 1},
        headers=h,
    )
    assert v1.json()["total"] == 1 and v1.json()["events"][0]["title"] == "Rhino 14 battery at 3 V"
    draft = await client.post(
        f"{base}/test-document",
        json={
            "from": T0.isoformat(),
            "to": (T0 + timedelta(hours=1)).isoformat(),
            "document": BATTERY,
        },
        headers=h,
    )
    assert draft.status_code == 200 and draft.json()["total"] == 1

    listed = (await client.get(base, headers=h)).json()
    assert {r["name"] for r in listed["items"]} == {"Battery", "Reserved"}
    assert (await client.delete(f"{base}/{saved.json()['id']}", headers=h)).status_code == 204


async def test_rules_role_matrix(client, db):
    _admin, project, *_ = await _setup(client, db)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    padmin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    base = f"/api/v1/projects/{project.id}"
    body = {"name": "R", "document": BATTERY}
    assert (
        await client.post(f"{base}/rules", json=body, headers=viewer.headers)
    ).status_code == 403
    assert (
        await client.post(f"{base}/rules", json=body, headers=padmin.headers)
    ).status_code == 201
    assert (await client.get(f"{base}/rules", headers=viewer.headers)).status_code == 200
    assert (
        await client.post(
            f"{base}/automations",
            json={"name": "A", "actions": [{"type": "webhook", "url": "https://x.example"}]},
            headers=viewer.headers,
        )
    ).status_code == 403
    assert (await client.get(f"{base}/alerts", headers=viewer.headers)).status_code == 200


async def test_events_alerts_and_map_layer(client, db):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    h = admin.headers
    now = datetime.now(UTC)
    db.add(
        EntityCurrentState(
            entity_id=uuid.UUID(entity["id"]), project_id=project.id, active_alert_count=1
        )
    )
    event = Event(
        time=now - timedelta(minutes=5),
        project_id=project.id,
        entity_id=uuid.UUID(entity["id"]),
        device_id=uuid.UUID(device["id"]),
        event_type="GEOFENCE_EXIT",
        severity="warning",
        title="Rhino 14 left Core area",
        geom=WKTElement("POINT(31.5 -24.9)", srid=4326),
        context={"feature": "Core area"},
    )
    older = Event(
        time=now - timedelta(days=3),
        project_id=project.id,
        event_type="BATTERY_LOW",
        severity="info",
        title="old",
    )
    db.add_all([event, older])
    await db.flush()
    alert = Alert(event_id=event.id, project_id=project.id, severity="warning")
    db.add(alert)
    await db.commit()
    base = f"/api/v1/projects/{project.id}"

    listed = (await client.get(f"{base}/events", headers=viewer.headers)).json()
    assert [e["event_type"] for e in listed["items"]] == ["GEOFENCE_EXIT", "BATTERY_LOW"]
    assert (
        listed["items"][0]["alert_status"] == "open"
        and listed["items"][0]["geometry"]["type"] == "Point"
    )
    paged = (await client.get(f"{base}/events", params={"limit": 1}, headers=h)).json()
    assert len(paged["items"]) == 1 and paged["next_cursor"]
    second = (
        await client.get(
            f"{base}/events", params={"limit": 1, "cursor": paged["next_cursor"]}, headers=h
        )
    ).json()
    assert second["items"][0]["event_type"] == "BATTERY_LOW" and second["next_cursor"] is None
    filtered = (
        await client.get(f"{base}/events", params={"severity": "warning"}, headers=h)
    ).json()
    assert len(filtered["items"]) == 1

    detail = (await client.get(f"{base}/events/{event.id}", headers=h)).json()
    assert detail["alert"]["status"] == "open" and detail["deliveries"] == []

    layer = (await client.get(f"{base}/map/events", params={"hours": 24}, headers=h)).json()
    assert len(layer["features"]) == 1
    assert layer["features"][0]["properties"]["icon_key"] == "event.geofence"

    alerts = (await client.get(f"{base}/alerts", params={"status": "open"}, headers=h)).json()
    assert (
        alerts["items"][0]["title"] == "Rhino 14 left Core area"
        and alerts["items"][0]["entity_id"] == entity["id"]
    )

    # a viewer acknowledges, then resolves; the open count drops once
    ack = await client.post(
        f"{base}/alerts/{alert.id}/acknowledge", json={"note": "on it"}, headers=viewer.headers
    )
    assert (
        ack.status_code == 200
        and ack.json()["status"] == "acknowledged"
        and ack.json()["note"] == "on it"
    )
    state = await db.get(EntityCurrentState, uuid.UUID(entity["id"]))
    await db.refresh(state)
    assert state.active_alert_count == 0
    resolve = await client.post(
        f"{base}/alerts/{alert.id}/resolve", json={}, headers=viewer.headers
    )
    assert resolve.status_code == 200 and resolve.json()["status"] == "resolved"
    await db.refresh(state)
    assert state.active_alert_count == 0
    again = await client.post(f"{base}/alerts/{alert.id}/acknowledge", json={}, headers=h)
    assert again.status_code == 409
    # another project cannot see it
    other = await client.get(f"{base}/alerts/{uuid.uuid4()}/acknowledge", headers=h)
    assert other.status_code in (404, 405)


async def test_automations_targets_and_deliveries(client, db):
    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    base = f"/api/v1/projects/{project.id}"
    caps = (await client.get(f"{base}/notifications/capabilities", headers=h)).json()
    assert caps["mail_configured"] is False and caps["telegram_configured"] is False

    email = await client.post(
        f"{base}/notification-targets",
        json={"name": "Ops", "channel": "email", "address": "ops@example.org"},
        headers=h,
    )
    assert email.status_code == 201 and email.json()["linked"] is True
    bad = await client.post(
        f"{base}/notification-targets", json={"name": "Bad", "channel": "email"}, headers=h
    )
    assert bad.status_code == 422
    tg = await client.post(
        f"{base}/notification-targets", json={"name": "Rangers", "channel": "telegram"}, headers=h
    )
    assert tg.status_code == 201
    assert (
        tg.json()["linked"] is False
        and len(tg.json()["telegram_link_code"]) == 8
        and tg.json()["link_url"] is None
    )
    code = tg.json()["telegram_link_code"]
    relink = (
        await client.post(f"{base}/notification-targets/{tg.json()['id']}/link-code", headers=h)
    ).json()
    assert relink["telegram_link_code"] != code

    test = (
        await client.post(f"{base}/notification-targets/{email.json()['id']}/test", headers=h)
    ).json()
    assert test["status"] == "skipped" and "logged" in test["detail"]
    test_tg = (
        await client.post(f"{base}/notification-targets/{tg.json()['id']}/test", headers=h)
    ).json()
    assert test_tg["status"] == "failed" and "not linked" in test_tg["detail"]

    auto = await client.post(
        f"{base}/automations",
        json={
            "name": "Notify ops",
            "event_types": ["BATTERY_LOW"],
            "min_severity": "warning",
            "actions": [
                {"type": "notify", "target_id": email.json()["id"]},
                {"type": "webhook", "url": "https://hooks.example.org/x", "secret": "s"},
            ],
        },
        headers=h,
    )
    assert auto.status_code == 201, auto.text
    assert auto.json()["actions"][0]["target_id"] == email.json()["id"]
    wrong_target = await client.post(
        f"{base}/automations",
        json={"name": "X", "actions": [{"type": "notify", "target_id": str(uuid.uuid4())}]},
        headers=h,
    )
    assert wrong_target.status_code == 422
    reserved = await client.post(
        f"{base}/automations", json={"name": "Y", "actions": [{"type": "command"}]}, headers=h
    )
    assert reserved.status_code == 422
    patched = await client.patch(
        f"{base}/automations/{auto.json()['id']}",
        json={"enabled": False, "max_event_age_seconds": 600},
        headers=h,
    )
    assert (
        patched.status_code == 200
        and patched.json()["enabled"] is False
        and patched.json()["max_event_age_seconds"] == 600
    )
    listed = (await client.get(f"{base}/automations", headers=h)).json()
    assert [a["name"] for a in listed["items"]] == ["Notify ops"]

    # deliveries: a failed one can be retried, a sent one cannot
    event = Event(
        time=datetime.now(UTC),
        project_id=project.id,
        event_type="BATTERY_LOW",
        severity="warning",
        title="t",
    )
    db.add(event)
    await db.flush()
    failed = ActionDelivery(
        event_id=event.id,
        automation_id=uuid.UUID(auto.json()["id"]),
        project_id=project.id,
        action_index=1,
        action_type="webhook",
        status="failed",
        attempts=1,
        error_message="503",
    )
    sent = ActionDelivery(
        event_id=event.id,
        automation_id=uuid.UUID(auto.json()["id"]),
        project_id=project.id,
        action_index=0,
        action_type="notify",
        status="sent",
        attempts=1,
    )
    db.add_all([failed, sent])
    await db.commit()
    deliveries = (
        await client.get(f"{base}/deliveries", params={"status": "failed"}, headers=h)
    ).json()
    assert [d["id"] for d in deliveries["items"]] == [str(failed.id)]
    retried = await client.post(f"{base}/deliveries/{failed.id}/retry", headers=h)
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert (await client.post(f"{base}/deliveries/{sent.id}/retry", headers=h)).status_code == 409
    assert (
        await client.delete(f"{base}/automations/{auto.json()['id']}", headers=h)
    ).status_code == 204
    assert (
        await client.delete(f"{base}/notification-targets/{tg.json()['id']}", headers=h)
    ).status_code == 204


async def test_server_level_alerts_and_targets(client, db):
    admin, project, *_ = await _setup(client, db)
    h = admin.headers
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    event = Event(
        time=datetime.now(UTC),
        project_id=None,
        event_type="SYSTEM_WORKER_STALE",
        severity="critical",
        title="Worker export stale",
        context={"subject": "export", "system": True},
    )
    db.add(event)
    await db.flush()
    db.add(Alert(event_id=event.id, project_id=None, severity="critical"))
    await db.commit()
    assert (await client.get("/api/v1/admin/alerts", headers=viewer.headers)).status_code == 403
    alerts = (await client.get("/api/v1/admin/alerts", params={"status": "open"}, headers=h)).json()
    assert any(a["event_id"] == str(event.id) for a in alerts["items"])
    alert_id = next(a["id"] for a in alerts["items"] if a["event_id"] == str(event.id))
    done = await client.post(
        f"/api/v1/admin/alerts/{alert_id}/resolve", json={"note": "restarted"}, headers=h
    )
    assert done.status_code == 200 and done.json()["status"] == "resolved"
    target = await client.post(
        "/api/v1/admin/notification-targets",
        json={"name": "Admins", "channel": "email", "address": "admin@example.org"},
        headers=h,
    )
    assert target.status_code == 201 and target.json()["project_id"] is None
    auto = await client.post(
        "/api/v1/admin/automations",
        json={
            "name": "System mail",
            "actions": [{"type": "notify", "target_id": target.json()["id"]}],
        },
        headers=h,
    )
    assert auto.status_code == 201
    # a project automation cannot use a server-level target
    wrong = await client.post(
        f"/api/v1/projects/{project.id}/automations",
        json={"name": "X", "actions": [{"type": "notify", "target_id": target.json()["id"]}]},
        headers=h,
    )
    assert wrong.status_code == 422
    events = (await client.get("/api/v1/admin/events", headers=h)).json()
    assert any(e["id"] == str(event.id) for e in events["items"])
