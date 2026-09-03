"""Data Explorer backend: bucketed aggregates, drill-down rows, metrics with data, bounds."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.models import Measurement
from tests.api.test_network_and_map import _setup

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)


async def _measurements(db, project, entity, device, source):
    """Battery voltage every 10 minutes for two hours (13 rows) and a boolean fix flag."""
    rows = []
    for i in range(13):
        rows.append(
            Measurement(
                time=T0 + timedelta(minutes=10 * i),
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                data_source_id=uuid.UUID(source["id"]),
                source_event_id=1000 + i,
                source_event_ingested_at=T0 + timedelta(minutes=10 * i, seconds=5),
                metric_key="battery_voltage",
                canonical_key=f"{device['id']}|battery_voltage|{i}",
                value_num=3.0 + i * 0.1,
                trace_id=uuid.uuid4(),
            )
        )
        rows.append(
            Measurement(
                time=T0 + timedelta(minutes=10 * i),
                device_id=uuid.UUID(device["id"]),
                project_id=project.id,
                entity_id=uuid.UUID(entity["id"]),
                metric_key="gnss_fix",
                canonical_key=f"{device['id']}|gnss_fix|{i}",
                value_bool=i % 2 == 0,
            )
        )
    db.add_all(rows)
    await db.commit()


def _ts(value: datetime) -> str:
    """Query-string safe timestamp (a `+00:00` offset would decode as a space)."""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _url(project, **params):
    query = "&".join(
        f"{k}={v}" for k, vs in params.items() for v in (vs if isinstance(vs, list) else [vs])
    )
    return f"/api/v1/projects/{project.id}/analytics/series?{query}"


async def test_hourly_buckets_with_all_aggregates(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _measurements(db, project, entity, device, source)
    response = await client.get(
        _url(
            project,
            metric=["battery_voltage", "gnss_fix"],
            bucket="1h",
            agg=["mean", "min", "max", "median", "sum", "count", "first", "last"],
        )
        + f"&from={_ts(T0)}&to={_ts(T0 + timedelta(hours=3))}",
        headers=admin.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bucket"] == "1h" and body["bucket_seconds"] == 3600
    assert body["automatic_bucket"] is False
    battery = next(s for s in body["series"] if s["metric_key"] == "battery_voltage")
    assert battery["unit"] == "V" and battery["entity_id"] == entity["id"]
    assert [p["time"][:16] for p in battery["points"]] == [
        "2026-04-01T00:00",
        "2026-04-01T01:00",
        "2026-04-01T02:00",
    ]
    first_hour = battery["points"][0]["values"]
    assert first_hour["count"] == 6  # minutes 0, 10, 20, 30, 40, 50
    assert first_hour["min"] == pytest.approx(3.0) and first_hour["max"] == pytest.approx(3.5)
    assert first_hour["mean"] == pytest.approx(3.25) and first_hour["median"] == pytest.approx(3.25)
    assert first_hour["first"] == pytest.approx(3.0) and first_hour["last"] == pytest.approx(3.5)
    assert first_hour["sum"] == pytest.approx(19.5)
    fix = next(s for s in body["series"] if s["metric_key"] == "gnss_fix")
    assert fix["points"][0]["values"]["mean"] == pytest.approx(0.5)  # booleans count as 0 and 1


async def test_automatic_bucket_and_layouts(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _measurements(db, project, entity, device, source)
    window = f"&from={_ts(T0)}&to={_ts(T0 + timedelta(days=1))}"
    auto = (
        await client.get(_url(project, metric="battery_voltage") + window, headers=admin.headers)
    ).json()
    assert auto["automatic_bucket"] is True
    assert auto["bucket"] == "1m"  # 24 h / 10 s would be 8,640 points, over the 5,000 bound
    assert len(auto["series"][0]["points"]) == 13  # empty buckets are not filled

    wide = (
        await client.get(
            _url(project, metric="battery_voltage", layout="wide", agg=["mean", "count"]) + window,
            headers=admin.headers,
        )
    ).json()
    assert wide["columns"] == [
        "time",
        f"battery_voltage|{entity['id']}|mean",
        f"battery_voltage|{entity['id']}|count",
    ]
    assert wide["rows"][0][1:] == [pytest.approx(3.0), 1]
    assert wide["series"] is None

    long = (
        await client.get(
            _url(project, metric="battery_voltage", layout="long", bucket="all") + window,
            headers=admin.headers,
        )
    ).json()
    assert long["bucket"] == "all" and len(long["rows"]) == 1
    assert long["rows"][0]["count"] == 13 and long["rows"][0]["metric_key"] == "battery_voltage"

    by_device = (
        await client.get(
            _url(project, metric="battery_voltage", group_by="device", device_id=device["id"])
            + window,
            headers=admin.headers,
        )
    ).json()
    assert by_device["series"][0]["device_id"] == device["id"]
    assert by_device["series"][0]["entity_id"] is None


async def test_bounds_and_validation(client, db):
    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    h = admin.headers
    window = f"&from={_ts(T0)}&to={_ts(T0 + timedelta(days=30))}"
    too_fine = await client.get(
        _url(project, metric="battery_voltage", bucket="1s") + window, headers=h
    )
    assert too_fine.status_code == 422 and "5000" in too_fine.text
    unknown = await client.get(_url(project, metric="no_such_metric") + window, headers=h)
    assert unknown.status_code == 404
    text_metric = await client.get(_url(project, metric="firmware_version") + window, headers=h)
    assert text_metric.status_code in (404, 422)
    too_many = await client.get(
        _url(project, metric=[f"m{i}" for i in range(21)]) + window, headers=h
    )
    assert too_many.status_code == 422
    device_without_filter = await client.get(
        _url(project, metric="battery_voltage", group_by="device") + window, headers=h
    )
    assert device_without_filter.status_code == 422
    reversed_window = await client.get(
        _url(project, metric="battery_voltage")
        + f"&from={_ts(T0 + timedelta(days=1))}&to={_ts(T0)}",
        headers=h,
    )
    assert reversed_window.status_code == 422
    # A member of another project cannot read this project's analytics.
    from tests.api.conftest import actor

    outsider = await actor(client, db)
    assert (
        await client.get(_url(project, metric="battery_voltage") + window, headers=outsider.headers)
    ).status_code == 403


async def test_drill_down_rows_and_metrics_with_data(client, db):
    admin, project, entity, source, device, _ = await _setup(client, db)
    await _measurements(db, project, entity, device, source)
    base = f"/api/v1/projects/{project.id}/analytics"
    window = f"from={_ts(T0)}&to={_ts(T0 + timedelta(hours=1))}"
    page1 = (
        await client.get(
            f"{base}/rows?metric=battery_voltage&entity_id={entity['id']}&{window}&limit=4",
            headers=admin.headers,
        )
    ).json()
    assert len(page1["items"]) == 4 and page1["next_cursor"]
    row = page1["items"][0]
    assert row["value"] == pytest.approx(3.0) and row["source_event_id"] == 1000
    assert row["trace_id"] and row["device_id"] == device["id"]
    page2 = (
        await client.get(
            f"{base}/rows?metric=battery_voltage&{window}&limit=4&cursor={page1['next_cursor']}",
            headers=admin.headers,
        )
    ).json()
    assert len(page2["items"]) == 2 and page2["next_cursor"] is None
    assert {r["id"] for r in page1["items"]}.isdisjoint({r["id"] for r in page2["items"]})

    metrics = (
        await client.get(
            f"{base}/metrics?from={_ts(T0)}&to={_ts(T0 + timedelta(days=1))}",
            headers=admin.headers,
        )
    ).json()
    assert [m["key"] for m in metrics] == ["battery_voltage", "gnss_fix"]
    battery = metrics[0]
    assert battery["count"] == 13 and battery["unit"] == "V" and battery["value_type"] == "numeric"
    assert battery["first_time"][:16] == "2026-04-01T00:00"
    assert battery["last_time"][:16] == "2026-04-01T02:00"


async def test_saved_views_are_shared_and_owned(client, db):
    from shared.enums import Role
    from tests.api.conftest import project_actor

    admin, project, _entity, _source, _device, _ = await _setup(client, db)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    base = f"/api/v1/projects/{project.id}/analytics/saved-views"
    created = await client.post(
        base,
        json={"name": "Battery last week", "view": {"metrics": ["battery_voltage"], "range": "7d"}},
        headers=viewer.headers,
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["created_by"] == str(viewer.user.id) and view["schema_version"] == 1
    duplicate = await client.post(
        base, json={"name": "Battery last week", "view": {}}, headers=admin.headers
    )
    assert duplicate.status_code == 409
    listed = (await client.get(base, headers=admin.headers)).json()
    assert [v["name"] for v in listed["items"]] == ["Battery last week"]

    # a second viewer cannot change it, the creator and a project admin can
    other = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    forbidden = await client.patch(
        f"{base}/{view['id']}", json={"name": "Mine now"}, headers=other.headers
    )
    assert forbidden.status_code == 403
    renamed = await client.patch(
        f"{base}/{view['id']}", json={"name": "Battery, 7 days"}, headers=viewer.headers
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Battery, 7 days"
    assert (await client.delete(f"{base}/{view['id']}", headers=admin.headers)).status_code == 204
    assert (await client.get(base, headers=viewer.headers)).json()["items"] == []
