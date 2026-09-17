"""The environmental layer boundary and the Copernicus provider (decision D245): the weeks and
the geometry key the cache is built on, the process graph the provider sends, and a whole job
over a fake transport, including the answers that must become a clear failure."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from shared.analysis.environment import (
    geometry_hash,
    week_start,
    weeks_between,
)
from shared.analysis.providers.copernicus import (
    CopernicusProvider,
    ProviderError,
    bbox,
    ndvi_process,
    parse_timeseries,
)

AREA_A = {
    "type": "Polygon",
    "coordinates": [
        [[16.70, -20.85], [16.72, -20.85], [16.72, -20.83], [16.70, -20.83], [16.70, -20.85]]
    ],
}
AREA_B = {
    "type": "Polygon",
    "coordinates": [
        [[16.74, -20.86], [16.76, -20.86], [16.76, -20.84], [16.74, -20.84], [16.74, -20.86]]
    ],
}
FROM = datetime(2026, 7, 1, tzinfo=UTC)
TO = datetime(2026, 7, 29, tzinfo=UTC)


def test_the_week_is_the_monday_and_the_range_covers_the_period():
    # a Wednesday and the Sunday after it fall in the same week
    assert week_start(datetime(2026, 7, 15, 13, 5, tzinfo=UTC)) == datetime(2026, 7, 13, tzinfo=UTC)
    assert week_start(datetime(2026, 7, 19, 23, 59, tzinfo=UTC)) == datetime(
        2026, 7, 13, tzinfo=UTC
    )
    weeks = weeks_between(FROM, TO)
    assert weeks[0] == datetime(2026, 6, 29, tzinfo=UTC) and len(weeks) == 5
    assert weeks_between(FROM, FROM) == []


def test_the_geometry_key_ignores_noise_and_separates_areas():
    moved = {
        "type": "Polygon",
        "coordinates": [
            [
                [16.700000004, -20.85],
                [16.72, -20.85],
                [16.72, -20.83],
                [16.70, -20.83],
                [16.70, -20.85],
            ]
        ],
    }
    assert geometry_hash(AREA_A) == geometry_hash(moved)  # under a metre is the same area
    assert geometry_hash(AREA_A) != geometry_hash(AREA_B)


def test_the_process_graph_asks_for_a_weekly_masked_ndvi_per_geometry():
    graph = ndvi_process([AREA_A, AREA_B], FROM, TO)["process_graph"]
    assert graph["load"]["arguments"]["id"] == "SENTINEL2_L2A"
    assert graph["load"]["arguments"]["bands"] == ["B04", "B08", "SCL"]
    assert graph["load"]["arguments"]["temporal_extent"] == ["2026-07-01", "2026-07-29"]
    assert graph["mask"]["process_id"] == "mask_scl_dilation"  # clouds out before the index
    assert graph["weekly"]["arguments"]["period"] == "week"
    assert len(graph["areas"]["arguments"]["geometries"]["features"]) == 2
    assert graph["save"]["arguments"]["format"] == "JSON" and graph["save"]["result"] is True
    box = bbox([AREA_A, AREA_B])
    assert box["west"] < 16.70 and box["east"] > 16.76 and box["south"] < -20.86


def test_the_recorded_answer_of_the_live_backend_parses_into_ten_weeks():
    """The answer Copernicus wrote for two areas near Okonjima over two months, recorded on
    2026-09-17 (`tests/fixtures/openeo/README.md`). The backend labels a week by its Sunday, a
    day before the Monday Protect counts from, so the labels must land on the weeks asked
    for."""
    import json
    from pathlib import Path as _Path

    from shared.analysis.environment import nearest_week

    body = json.loads(
        (
            _Path(__file__).resolve().parents[1] / "fixtures" / "openeo" / "ndvi_timeseries.json"
        ).read_text()
    )
    series = parse_timeseries(body, 2)
    assert len(series[0]) == 10 and len(series[1]) == 10
    # the dry season: the index falls from late June to the end of August, bush above grass
    assert series[0][0][1] == pytest.approx(0.26, abs=0.01)
    assert series[0][-1][1] == pytest.approx(0.175, abs=0.01)
    assert all(a[1] > b[1] for a, b in zip(series[0], series[1], strict=True))
    weeks = weeks_between(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC))
    matched = {nearest_week(when, weeks) for when, _ in series[0]}
    assert None not in matched and len(matched) == len(series[0])


def test_the_answer_becomes_a_series_per_geometry_with_gaps_kept():
    body = {
        "2026-07-06T00:00:00Z": [[0.42], [0.51]],
        "2026-07-13T00:00:00Z": [[None], [0.49]],
        "2026-07-20T00:00:00Z": [["nan"], [0.47]],
    }
    series = parse_timeseries(body, 2)
    assert [v for _, v in series[0]] == [0.42, None, None]  # a cloudy week is no observation
    assert [v for _, v in series[1]] == [0.51, 0.49, 0.47]
    assert series[0][0][0] == datetime(2026, 7, 6, tzinfo=UTC)
    with pytest.raises(ProviderError):
        parse_timeseries(["not", "a", "mapping"], 2)


def _transport(*, status: str = "finished", asset_status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t0ken", "expires_in": 3600})
        if url.endswith("/jobs") and request.method == "POST":
            assert b"SENTINEL2_L2A" in request.content
            return httpx.Response(201, headers={"OpenEO-Identifier": "j-1"}, json={"id": "j-1"})
        if url.endswith("/jobs/j-1/results") and request.method == "POST":
            return httpx.Response(202)
        if url.endswith("/jobs/j-1"):
            return httpx.Response(200, json={"status": status, "progress": 100})
        if url.endswith("/jobs/j-1/results"):
            return httpx.Response(
                200,
                json={
                    "assets": {
                        "timeseries.json": {
                            "href": "https://store.example/j-1/timeseries.json",
                            "type": "application/json",
                        }
                    }
                },
            )
        if url.startswith("https://store.example/"):
            # the object store refuses our own authorization header, so it must not be sent
            assert "authorization" not in {k.lower() for k in request.headers}
            return httpx.Response(
                asset_status,
                json={
                    "2026-07-06T00:00:00Z": [[0.42], [0.51]],
                    "2026-07-13T00:00:00Z": [[0.40], [None]],
                },
            )
        raise AssertionError(f"unexpected request {url}")

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_a_whole_job_gives_a_series_per_area(monkeypatch):
    monkeypatch.setattr("shared.analysis.providers.copernicus.POLL_S", 0)
    provider = CopernicusProvider("id", "secret", transport=_transport())
    sample = await provider.sample("ndvi", [AREA_A, AREA_B], FROM, TO, uuid.uuid4())
    assert sample.layer == "ndvi" and "Sentinel-2" in sample.source
    assert [v for _, v in sample.series[0]] == [0.42, 0.40]
    assert [v for _, v in sample.series[1]] == [0.51, None]


@pytest.mark.asyncio
async def test_a_failing_job_a_refused_asset_and_a_wrong_ask_are_clear(monkeypatch):
    monkeypatch.setattr("shared.analysis.providers.copernicus.POLL_S", 0)
    failing = CopernicusProvider("id", "secret", transport=_transport(status="error"))
    with pytest.raises(ProviderError, match="ended as error"):
        await failing.sample("ndvi", [AREA_A], FROM, TO, uuid.uuid4())
    refused = CopernicusProvider("id", "secret", transport=_transport(asset_status=403))
    with pytest.raises(ProviderError, match="without a result"):
        await refused.sample("ndvi", [AREA_A], FROM, TO, uuid.uuid4())
    provider = CopernicusProvider("id", "secret", transport=_transport())
    with pytest.raises(ProviderError, match="not one this provider answers"):
        await provider.sample("rainfall", [AREA_A], FROM, TO, uuid.uuid4())
    with pytest.raises(ProviderError, match="between 1 and"):
        await provider.sample("ndvi", [], FROM, TO, uuid.uuid4())


def test_the_registry_answers_by_layer_only_for_what_a_provider_has():
    # the module is taken as a whole: another test in this directory re-imports the analysis
    # package to prove the core lives without it, which would leave a stale registry behind
    import shared.analysis.environment as env

    before = list(env.PROVIDERS)
    try:
        env.PROVIDERS.clear()
        assert env.provider_for("ndvi") is None
        env.register(CopernicusProvider("id", "secret"))
        env.register(CopernicusProvider("id", "secret"))  # the same key twice registers once
        assert len(env.PROVIDERS) == 1
        assert env.provider_for("ndvi") is not None
        assert env.provider_for("rainfall") is None
    finally:
        env.PROVIDERS.clear()
        env.PROVIDERS.extend(before)
