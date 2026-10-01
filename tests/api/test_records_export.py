"""The records export (decision D144): one row per moment with a column per metric (wide), or a
row per value (long), streamed like the other datasets; the direct path counts the moments."""

import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pyarrow.parquet as pq
import pytest
from shapely import from_wkb

from tests.api.test_network_and_map import _feed, _setup, bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_records_export_wide_and_long(client, db, bus):  # noqa: F811
    admin, project, entity, source, _device, external_id = await _setup(client, db)
    start = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    for i in range(3):
        await _feed(
            db, bus, source["id"], external_id, start + timedelta(minutes=i), -24.9, 31.5 + i / 100
        )
    query = {
        "dataset": "records",
        "format": "csv",
        "time_from": (start - timedelta(hours=1)).isoformat(),
        "time_to": (start + timedelta(hours=1)).isoformat(),
        "entity_ids": entity["id"],
    }
    wide = await client.get(
        f"/api/v1/projects/{project.id}/exports/direct", params=query, headers=admin.headers
    )
    assert wide.status_code == 200, wide.text
    rows = list(csv.DictReader(io.StringIO(wide.text)))
    assert len(rows) == 3
    assert "m_battery_voltage" in rows[0] and rows[0]["m_battery_voltage"] == "3.8"
    assert rows[0]["entity_name"] == "Rhino 14" and rows[0]["latitude"].startswith("-24.9")
    assert [r["longitude"][:5] for r in rows] == ["31.5", "31.51", "31.52"]  # oldest first

    # the same moments as GeoParquet (decision D312): a point per moment, a typed metric column
    parquet = await client.get(
        f"/api/v1/projects/{project.id}/exports/direct",
        params={**query, "format": "parquet"},
        headers=admin.headers,
    )
    assert parquet.status_code == 200, parquet.text
    table = pq.read_table(io.BytesIO(parquet.content))
    assert table.num_rows == 3 and "latitude" not in table.column_names
    assert str(table.schema.field("m_battery_voltage").type) == "double"
    first = table.slice(0, 1).to_pylist()[0]
    assert first["m_battery_voltage"] == 3.8 and first["entity_name"] == "Rhino 14"
    assert from_wkb(first["geometry"]).coords[0] == (31.5, -24.9)
    footer = pq.read_metadata(io.BytesIO(parquet.content)).metadata
    assert json.loads(footer[b"geo"])["columns"]["geometry"]["bbox"][0] == 31.5

    long = await client.get(
        f"/api/v1/projects/{project.id}/exports/direct",
        params={**query, "records_layout": "long"},
        headers=admin.headers,
    )
    assert long.status_code == 200, long.text
    long_rows = list(csv.DictReader(io.StringIO(long.text)))
    assert {r["field"] for r in long_rows} >= {"latitude", "longitude", "battery_voltage"}
    assert next(r for r in long_rows if r["field"] == "battery_voltage")["unit"] == "V"

    job = await client.post(
        f"/api/v1/projects/{project.id}/exports",
        json={**query, "entity_ids": [entity["id"]]},
        headers=admin.headers,
    )
    assert job.status_code == 201, job.text
