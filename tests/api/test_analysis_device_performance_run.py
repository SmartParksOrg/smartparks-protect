"""The device performance module over real rows (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
section 11): a healthy device and a failing one through the API and the runner; the fleet table
puts the failing one first with its reasons readable, the geometries land, a scoped member sees
one device, and the subjects resolve by id, by type and as every device."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import select

from shared.analysis.runner import run_analysis
from shared.enums import AcquisitionChannel, IngestionMethod, ProcessingStatus, Role
from shared.models import (
    AnalysisGeometry,
    AnalysisRun,
    DeviceStateHistory,
    Event,
    Gateway,
    GatewayReception,
    Measurement,
    Position,
    ProjectMembership,
    SourceEvent,
)
from tests.api.conftest import create_user, login
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 5, 1, tzinfo=UTC)
DAYS = 30
LAT, LON = -24.9, 31.5
HOUR = timedelta(hours=1)


async def _second_device(client, h, project, source, device_type_id):
    """A device of the same type on the same source, in the project, tracking no animal."""
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type_id, "name": unique_name("bad"), "status": "active"},
            headers=h,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": uuid.uuid4().hex[:16].upper()},
        headers=h,
    )
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=h,
    )
    assert assigned.status_code in (200, 201), assigned.text
    return device


async def _uplinks(db, source, device_id, hours: list[int], counters: list[int], gateways):
    """One source event per hour given, with its frame counter, and a reception per gateway."""
    events = []
    for hour, counter in zip(hours, counters, strict=True):
        when = T0 + hour * HOUR
        event = SourceEvent(
            ingested_at=when,
            data_source_id=uuid.UUID(source["id"]),
            external_id="x",
            device_id=device_id,
            event_type="uplink",
            acquisition_channel=AcquisitionChannel.LORAWAN,
            ingestion_method=IngestionMethod.MQTT,
            processing_status=ProcessingStatus.PROCESSED,
            payload={},
            payload_size=2,
            payload_sha256="0" * 64,
            provider_metadata={"f_cnt": counter},
        )
        db.add(event)
        events.append((event, when))
    await db.flush()
    for event, when in events:
        for gateway_id, rssi in gateways:
            db.add(
                GatewayReception(
                    time=when,
                    data_source_id=uuid.UUID(source["id"]),
                    device_id=device_id,
                    source_event_id=event.id,
                    source_event_ingested_at=event.ingested_at,
                    gateway_id=gateway_id,
                    rssi=rssi,
                    snr=7.0,
                )
            )


async def _records(db, project, entity_id, device_id, source, *, failing: bool):
    """Thirty days of a device: hourly statuses with battery and temperature, GNSS attempts
    and fixes; the failing one fixes every third hour, loses fixes, reboots and reports an
    error flag in a third of its statuses."""
    device = uuid.UUID(device_id)
    rows = []
    n = 0
    for hour in range(DAYS * 24):
        when = T0 + hour * HOUR
        day = hour / 24
        battery = (3.7 - 0.0067 * day) if failing else (3.95 - 0.0005 * day)
        fix_ok = (hour % 5 != 0) if failing else True  # 80 percent or every attempt
        metrics = {
            "battery_voltage": battery,
            "device_temperature": 28.0 + (hour % 24) / 4,
            "uptime": (hour % (10 * 24)) * 3600 if failing else hour * 3600,
            "gnss_fix": 1.0 if fix_ok else 0.0,
            "gnss_time_to_fix": 150.0 if failing else 20.0,
        }
        for key, value in metrics.items():
            n += 1
            rows.append(
                Measurement(
                    time=when,
                    device_id=device,
                    project_id=project.id,
                    entity_id=entity_id,
                    data_source_id=uuid.UUID(source["id"]),
                    source_event_id=10_000 + n,
                    source_event_ingested_at=when,
                    canonical_key=f"{device_id}|{key}|{hour}",
                    metric_key=key,
                    value_num=value,
                )
            )
        rows.append(
            DeviceStateHistory(
                time=when,
                device_id=device,
                project_id=project.id,
                state={
                    "errors": {"ublox_fix": failing and hour % 3 == 0, "flash": False},
                    "reset_reason": {"watchdog": False},
                    "firmware_version": "6.2",
                },
            )
        )
        if fix_ok and (hour % 3 == 0 or not failing):
            rows.append(
                Position(
                    time=when,
                    device_id=device,
                    project_id=project.id,
                    entity_id=entity_id,
                    data_source_id=uuid.UUID(source["id"]),
                    source_event_id=20_000 + hour,
                    source_event_ingested_at=when,
                    canonical_key=f"{device_id}|gnss|{hour}",
                    geom=WKTElement(
                        f"POINT({LON + (hour % 7) * 0.001} {LAT + (hour % 5) * 0.001})", srid=4326
                    ),
                    satellites=5 if failing else 9,
                    accuracy_m=45.0 if failing else 6.0,
                )
            )
    if failing:
        rows.append(
            Event(
                time=T0 + timedelta(days=10),
                project_id=project.id,
                device_id=device,
                event_type="device_reset",
                severity="warning",
                title="Device rebooted (watchdog)",
                context={"reset_reason": "watchdog"},
            )
        )
        # settings frame: a GPS interval of 3600 s (id 1, uint32 little endian)
        rows.append(
            DeviceStateHistory(
                time=T0 + HOUR / 2,
                device_id=device,
                project_id=project.id,
                state={"port_3_tlv": {"0x01": "100e0000", "0x03": "100e0000"}},
            )
        )
    db.add_all(rows)
    await db.flush()
    hours = list(range(0, DAYS * 24, 3 if failing else 1))
    if failing:
        # a quarter of the frames never reached the network
        counters = [i * 4 // 3 for i in range(len(hours))]  # 0 1 2 4 5 6 8: one in four lost
        gateways = [("gw-only", -118.0)]
    else:
        counters = list(range(len(hours)))
        gateways = [("gw-a", -90.0), ("gw-b", -105.0)]
    await _uplinks(db, source, device, hours, counters, gateways)


async def test_a_fleet_run_puts_the_failing_collar_first(client, db):
    admin, project, entity, source, good, _ = await _setup(client, db)
    h = admin.headers
    device_type_id = good["device_type_id"]
    typed = await client.patch(
        f"/api/v1/device-types/{device_type_id}",
        json={"default_settings": {"lr_gps_interval": 3600, "status_send_interval": 3600}},
        headers=h,
    )
    assert typed.status_code == 200, typed.text
    bad = await _second_device(client, h, project, source, device_type_id)
    await _records(db, project, uuid.UUID(entity["id"]), good["id"], source, failing=False)
    await _records(db, project, None, bad["id"], source, failing=True)
    db.add(
        Gateway(
            data_source_id=uuid.UUID(source["id"]),
            external_id="gw-a",
            name="Hill gateway",
            geom=WKTElement(f"POINT({LON + 0.01} {LAT + 0.01})", srid=4326),
        )
    )
    await db.commit()

    base = f"/api/v1/projects/{project.id}/analyses"
    window = {
        "time_from": T0.isoformat(),
        "time_to": (T0 + timedelta(days=DAYS)).isoformat(),
    }
    # the subjects resolve by ids, by type and as every device of the project
    for selection in (
        {"device_ids": [good["id"], bad["id"]]},
        {"device_type_id": device_type_id},
        {"all_devices": True},
    ):
        estimate = await client.get(
            f"{base}/estimate",
            params={
                "module": "device_performance",
                "parameters": json.dumps({**window, **selection}),
            },
            headers=h,
        )
        assert estimate.status_code == 200, estimate.text
        assert estimate.json()["subjects"] == 2 and estimate.json()["ok"], estimate.json()
    # hourly fixes of the good one; every third hour of the bad one, minus the failed attempts
    assert estimate.json()["fixes"] == DAYS * 24 + (DAYS * 8 - DAYS * 8 // 5)
    nothing = await client.get(
        f"{base}/estimate",
        params={"module": "device_performance", "parameters": json.dumps(window)},
        headers=h,
    )
    assert nothing.status_code == 422 and "Choose devices" in nothing.text

    params = {
        **window,
        "device_ids": [good["id"], bad["id"]],
        "comparison": {
            "time_from": (T0 - timedelta(days=DAYS)).isoformat(),
            "time_to": T0.isoformat(),
        },
    }
    created = await client.post(
        base, json={"module": "device_performance", "parameters": params}, headers=h
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()["id"])
    assert created.json()["parameters"]["device_ids"] == [good["id"], bad["id"]]
    assert "entity_ids" not in created.json()["parameters"]

    await run_analysis(db, await db.get(AnalysisRun, run_id))
    body = (await client.get(f"{base}/{run_id}", headers=h)).json()
    assert body["status"] == "completed", (body["error_code"], body["error_message"])
    document = body["result"]
    subjects = {s["id"]: s for s in document["subjects"]}
    assert subjects[good["id"]]["kind"] == "device"
    assert subjects[good["id"]]["tracked"] == "Rhino 14"
    assert subjects[bad["id"]]["tracked"] is None

    main = document["summary"]["main"]
    levels = document["summary"]["levels"]
    g, b = main[good["id"]], main[bad["id"]]
    # health: the failing battery falls about 6.7 mV a day, the good one hardly
    assert b["battery_slope_mv_day"] == pytest.approx(-6.7, abs=0.4)
    assert levels[bad["id"]]["battery_slope_mv_day"] == "warn"
    assert levels[good["id"]]["battery_slope_mv_day"] == "ok"
    # 3.5 V at the end, 6.7 mV a day: about a week to 3.45 V; the good one has years
    assert 5 < b["days_to_critical"] < 10 and g["days_to_critical"] > 365
    assert levels[bad["id"]]["days_to_critical"] == "critical"
    assert b["reboots"] == 1 and g["reboots"] == 0
    assert b["error_share"] == pytest.approx(1 / 3, abs=0.01)
    assert levels[bad["id"]]["error_share"] == "warn"
    assert b["firmware"] == "6.2"
    # reporting: the interval comes from the type's defaults (and the frame for the bad one)
    # the type's defaults say an hour; the good device keeps it, the bad one plainly fixes every
    # three hours, so its setting is stale and gives way to the data (decisions D225 to D227)
    assert g["expected_fix_s"] == 3600 and g["expected_fix_source"] == "type_default"
    assert b["expected_fix_s"] == 3 * 3600 and b["expected_fix_source"] == "learned"
    # a failed attempt every fifth fix leaves six-hour gaps: three quarters of the intervals
    # sit on the three-hour schedule, enough to trust it
    assert b["declared_fix_s"] == 3600 and 0.7 < b["fix_regular_share"] < 0.8
    assert g["missed_fix_share"] == 0 and levels[good["id"]]["missed_fix_share"] == "ok"
    # against its own schedule the bad device misses the attempts that failed: one in five
    assert b["missed_fix_share"] == pytest.approx(0.2, abs=0.01)
    assert levels[bad["id"]]["missed_fix_share"] == "warn"
    assert g["silences"] == 0
    # gnss
    assert g["fix_success"] == 1.0 and b["fix_success"] == pytest.approx(0.8)
    assert levels[bad["id"]]["fix_success"] == "ok"  # 80 percent is the bound, not below it
    assert b["ttf_p90_s"] == 150 and levels[bad["id"]]["ttf_p90_s"] == "warn"
    assert b["accuracy_median_m"] == 45 and levels[bad["id"]]["accuracy_median_m"] == "warn"
    assert g["accuracy_median_m"] == 6
    # network: one source, the lost share from the counter, the single gateway
    assert g["lost_uplinks_share"] == 0 and b["lost_uplinks_share"] == pytest.approx(0.25, abs=0.01)
    assert levels[bad["id"]]["lost_uplinks_share"] == "critical"
    assert g["rssi_p10_dbm"] == -90 and b["rssi_p10_dbm"] == -118
    assert b["level"] == "critical" and g["level"] in ("ok", "warn")

    tables = {t["key"]: t for t in document["tables"]}
    fleet = tables["fleet"]
    assert fleet["rows"][0][0] == bad["name"] and fleet["rows"][0][1] == "critical"
    assert fleet["rows"][1][0] == good["name"]
    assert fleet["columns"][:3] == ["device", "level", "battery_v"]
    network = tables["network"]
    by_device = {row[0]: row for row in network["rows"] if row[1] == "main"}
    gateways_column = network["columns"].index("gateways")
    best_column = network["columns"].index("best_gateway")
    assert by_device[good["name"]][gateways_column] == 2
    assert by_device[good["name"]][best_column] == "Hill gateway"
    assert by_device[bad["name"]][gateways_column] == 1
    assert tables["reboots"]["rows"] == [
        [bad["name"], (T0 + timedelta(days=10)).isoformat(), "watchdog"]
    ]
    assert [r[:2] for r in tables["errors"]["rows"] if r[1] == "ublox_fix"] == [
        [bad["name"], "ublox_fix"]
    ]
    # ranks: the failing device is first on the indicators that matter
    ranks = document["summary"]["ranks"]
    assert ranks[bad["id"]]["missed_fix_share"] == 1 and ranks[good["id"]]["missed_fix_share"] == 2
    assert ranks[bad["id"]]["battery_v"] == 1
    assert "warn below 3.6 V" in document["summary"]["defaults"]["battery_v"]
    assert {c["key"] for c in document["charts"]} >= {
        "battery",
        "temperature",
        "fixes_per_day",
        "time_to_fix",
        "uplinks_per_day",
        "rssi_per_day",
    }
    # the comparison period is empty: it counts, with no figures
    assert document["summary"]["comparison"][good["id"]]["fixes"] == 0
    assert [p["key"] for p in document["periods"]] == ["main", "comparison"]
    codes = {(w["code"], w["subject_id"]) for w in document["warnings"]}
    assert ("no_data", good["id"]) not in codes
    assert ("interval_disagrees", bad["id"]) in codes and (
        "interval_disagrees",
        good["id"],
    ) not in codes
    assert ("no_comparison_data", good["id"]) in codes  # nothing before the period, a notice

    stored = (
        await db.execute(
            select(
                AnalysisGeometry.kind, AnalysisGeometry.subject_id, AnalysisGeometry.level
            ).where(AnalysisGeometry.run_id == run_id)
        )
    ).all()
    kinds = {}
    for row in stored:
        kinds.setdefault(row.kind, []).append(row)
    assert len(kinds["coverage"]) == 2
    assert len(kinds["gateway"]) == 1 and kinds["gateway"][0].level == 1.0
    assert document["geometries"] == {"coverage": 2, "gateway": 1}

    # a member scoped to one device: the other is refused by id, skipped by "all", and the run
    # over both is hidden
    scoped_user = await create_user(db)
    db.add(
        ProjectMembership(
            user_id=scoped_user.id,
            project_id=project.id,
            role=Role.PROJECT_ANALYST,
            scope={"groups": [], "entities": [], "devices": [good["id"]]},
        )
    )
    await db.commit()
    scoped = {"Authorization": f"Bearer {await login(client, scoped_user.email)}"}
    refused = await client.get(
        f"{base}/estimate",
        params={
            "module": "device_performance",
            "parameters": json.dumps({**window, "device_ids": [bad["id"]]}),
        },
        headers=scoped,
    )
    assert refused.status_code == 422 and "outside" in refused.text
    narrowed = await client.get(
        f"{base}/estimate",
        params={
            "module": "device_performance",
            "parameters": json.dumps({**window, "all_devices": True}),
        },
        headers=scoped,
    )
    assert narrowed.status_code == 200 and narrowed.json()["subjects"] == 1
    await client.patch(f"{base}/{run_id}", json={"shared": True}, headers=h)
    assert (await client.get(f"{base}/{run_id}", headers=scoped)).status_code == 404
    listed = await client.get(base, params={"module": "device_performance"}, headers=scoped)
    assert listed.status_code == 200 and listed.json()["items"] == []

    # the device page's Reporting card reads the same expectation (decision D226)
    read = await client.get(f"/api/v1/devices/{bad['id']}/reporting", headers=h)
    assert read.status_code == 200, read.text
    reporting = read.json()
    assert reporting["expected_source"] == "learned" and reporting["disagrees"] is True
    assert reporting["declared_fix_s"] == 3600 and reporting["declared_source"] == "type_default"
    assert reporting["learned"]["confident"] and reporting["override"] is None
    # a person's word comes first, and can be taken back
    put = await client.put(
        f"/api/v1/devices/{bad['id']}/reporting",
        json={"expected_fix_interval_s": 7200},
        headers=h,
    )
    assert put.status_code == 200, put.text
    assert put.json()["expected_source"] == "override" and put.json()["expected_fix_s"] == 7200
    cleared = await client.put(
        f"/api/v1/devices/{bad['id']}/reporting", json={"expected_fix_interval_s": None}, headers=h
    )
    assert cleared.json()["override"] is None and cleared.json()["expected_source"] == "learned"

    # the settings tab (decisions D228 to D231): the generic type has no catalogue
    empty = await client.get(f"/api/v1/devices/{bad['id']}/settings", headers=h)
    assert empty.status_code == 200 and empty.json()["items"] == [] and empty.json()["known"] == 0
