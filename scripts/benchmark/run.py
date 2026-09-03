#!/usr/bin/env python3
"""Benchmark the running stack against the performance budgets (architecture 13.7, 13.8).

    uv run scripts/benchmark/run.py --email admin@example.org --password '...' \
        --manifest /path/to/manifest.json --output docs/operations/benchmarks.md

Runs against the API like a browser would: live map load, viewport tiles, tracks over 1 day,
30 days and a year, Data Explorer aggregates, a direct export, an export job (with the peak
memory of the export container) and an ingest burst through the HTTP webhook. Writes a
Markdown report with p50 and p95 per operation next to its budget.
"""

import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import httpx

BUDGETS_MS = {
    "live map load": 3_000,
    "viewport tile": 2_000,
    "track 1 day": 2_500,
    "track 30 days": 2_500,
    "track 1 year": 3_000,
    "explorer series, 1 metric, 30 days": 3_000,
    "explorer series, 1 metric, 1 year": 3_000,
    "explorer series, 4 metrics x 5 entities, 7 days": 3_000,
    "explorer metrics with data, 30 days": 3_000,
    "explorer drill-down page": 1_000,
    "direct export, positions, csv": 10_000,
}


class Bench:
    def __init__(self, api: str, token: str) -> None:
        self.client = httpx.Client(
            base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=600
        )
        self.results: list[dict[str, Any]] = []
        self.notes: list[str] = []

    def timed(
        self, name: str, method: str, url: str, repeats: int = 5, **kwargs: Any
    ) -> httpx.Response:
        samples = []
        response = None
        for _ in range(repeats):
            started = time.perf_counter()
            response = self.client.request(method, url, **kwargs)
            samples.append((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                raise SystemExit(f"{name}: {response.status_code} {response.text[:300]}")
        self.record(name, samples, size=len(response.content) if response else 0)
        assert response is not None
        return response

    def record(self, name: str, samples_ms: list[float], **extra: Any) -> None:
        samples = sorted(samples_ms)
        p95 = samples[min(len(samples) - 1, math.ceil(0.95 * len(samples)) - 1)]
        self.results.append(
            {
                "name": name,
                "samples": len(samples),
                "p50_ms": statistics.median(samples),
                "p95_ms": p95,
                "budget_ms": BUDGETS_MS.get(name),
                **extra,
            }
        )
        sys.stderr.write(
            f"  {name:<50} p50 {statistics.median(samples):8.0f} ms  p95 {p95:8.0f} ms\n"
        )


def login_token(api: str, email: str, password: str) -> str:
    with httpx.Client(base_url=api) as client:
        response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
        response.raise_for_status()
        return str(response.json()["access_token"])


def tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lon + 180) / 360 * n)
    y = int(
        (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
        / 2
        * n
    )
    return x, y


def container_peak_memory(name: str, stop: asyncio.Event) -> list[float]:
    """Resident memory of the worker process (PID 1 in the container) in MiB, sampled every
    second. `docker stats` would also count the page cache of the file being written."""
    samples: list[float] = []
    while not stop.is_set():
        out = subprocess.run(
            ["docker", "exec", name, "grep", "VmRSS", "/proc/1/status"],
            capture_output=True,
            text=True,
        )
        parts = out.stdout.split()
        if len(parts) >= 2:
            samples.append(int(parts[1]) / 1024)
        time.sleep(1)
    return samples


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--project", default="bench-kruger", help="slug of the benchmark project")
    parser.add_argument(
        "--manifest", type=Path, help="manifest written by generate.py (webhook tokens)"
    )
    parser.add_argument("--output", type=Path, default=Path("docs/operations/benchmarks.md"))
    parser.add_argument("--ingest-events", type=int, default=2_000)
    parser.add_argument("--export-container", default="protect-export")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=["map", "tracks", "explorer", "exports", "ingest"],
        help="run only these sections (default all); use another --output to keep the full report",
    )
    args = parser.parse_args()

    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://protect:protect-dev-password@localhost:5432/smartparks_protect",
    ).replace("postgresql+asyncpg://", "postgresql://")
    db = await asyncpg.connect(dsn)
    bench = Bench(args.api + "/api/v1", login_token(args.api, args.email, args.password))
    project = await db.fetchrow("SELECT id, name FROM projects WHERE slug = $1", args.project)
    if project is None:
        raise SystemExit(f"no project with slug {args.project}; run generate.py first")
    pid = project["id"]
    counts = await db.fetchrow(
        "SELECT (SELECT count(*) FROM positions WHERE project_id = $1) AS positions, (SELECT count(*) FROM measurements WHERE project_id = $1) AS measurements, (SELECT count(*) FROM entities WHERE project_id = $1) AS entities",
        pid,
    )
    totals = await db.fetchrow(
        "SELECT (SELECT count(*) FROM positions) AS positions, (SELECT count(*) FROM measurements) AS measurements, (SELECT count(*) FROM devices) AS devices, (SELECT count(*) FROM entities) AS entities"
    )
    sys.stderr.write(
        f"project {project['name']}: {counts['entities']} entities, {counts['positions']:,} positions, {counts['measurements']:,} measurements\n"
    )
    now = datetime.now(UTC)
    only = set(args.only or ())

    def wanted(section: str) -> bool:
        return not only or section in only

    # live map
    if wanted("map"):
        current = bench.timed("live map load", "GET", f"/projects/{pid}/map/current").json()
        features = current.get("features", [])
        bench.notes.append(
            f"Live map returned {len(features)} features (mode {current.get('mode', 'geojson')})."
        )
        center = await db.fetchrow(
            "SELECT ST_Y(ST_Centroid(ST_Collect(latest_position))) AS lat, ST_X(ST_Centroid(ST_Collect(latest_position))) AS lon FROM entity_current_state WHERE project_id = $1",
            pid,
        )
        for zoom in (6, 9, 12):
            x, y = tile(center["lat"], center["lon"], zoom)
            bench.timed(
                "viewport tile", "GET", f"/projects/{pid}/map/tiles/{zoom}/{x}/{y}.mvt", repeats=3
            )

        entity_ids = [
            r["entity_id"]
            for r in await db.fetch(
                "SELECT entity_id FROM entity_current_state WHERE project_id = $1 ORDER BY last_seen_at DESC LIMIT 5",
                pid,
            )
        ]
        entity = entity_ids[0]
    # tracks
    if wanted("tracks"):
        for label, days in (("track 1 day", 1), ("track 30 days", 30), ("track 1 year", 365)):
            body = bench.timed(
                label,
                "GET",
                f"/projects/{pid}/tracks",
                params={
                    "entity_id": str(entity),
                    "from": (now - timedelta(days=days)).isoformat(),
                    "to": now.isoformat(),
                },
            ).json()
            bench.results[-1]["rows"] = body["total_points"]

    # explorer
    if wanted("explorer"):
        for label, days in (
            ("explorer series, 1 metric, 30 days", 30),
            ("explorer series, 1 metric, 1 year", 365),
        ):
            body = bench.timed(
                label,
                "GET",
                f"/projects/{pid}/analytics/series",
                params={
                    "metric": "battery_voltage",
                    "entity_id": str(entity),
                    "from": (now - timedelta(days=days)).isoformat(),
                    "to": now.isoformat(),
                },
            ).json()
            bench.results[-1]["rows"] = sum(len(s["points"]) for s in body["series"])
        params: list[tuple[str, str]] = [
            ("metric", m)
            for m in ("battery_voltage", "device_temperature", "activity", "gnss_satellites")
        ]
        params += [("entity_id", str(e)) for e in entity_ids]
        params += [("from", (now - timedelta(days=7)).isoformat()), ("to", now.isoformat())]
        body = bench.timed(
            "explorer series, 4 metrics x 5 entities, 7 days",
            "GET",
            f"/projects/{pid}/analytics/series",
            params=params,
        ).json()
        bench.results[-1]["rows"] = sum(len(s["points"]) for s in body["series"])
        bench.timed(
            "explorer metrics with data, 30 days",
            "GET",
            f"/projects/{pid}/analytics/metrics",
            repeats=3,
        )
        bench.timed(
            "explorer drill-down page",
            "GET",
            f"/projects/{pid}/analytics/rows",
            params={
                "metric": "battery_voltage",
                "entity_id": str(entity),
                "from": (now - timedelta(days=30)).isoformat(),
                "to": now.isoformat(),
                "limit": 500,
            },
        )

    # direct export: a window with roughly 50,000 positions
    if wanted("exports"):
        per_day = counts["positions"] / 365
        days = max(1, min(365, int(50_000 / max(per_day, 1))))
        response = bench.timed(
            "direct export, positions, csv",
            "GET",
            f"/projects/{pid}/exports/direct",
            repeats=2,
            params={
                "dataset": "positions",
                "format": "csv",
                "time_from": (now - timedelta(days=days)).isoformat(),
                "time_to": now.isoformat(),
            },
        )
        bench.results[-1]["rows"] = response.text.count("\n") - 1

    # export job over the whole year of measurements, with the container's memory watched
    if wanted("exports"):
        stop = asyncio.Event()
        memory_task = asyncio.get_running_loop().run_in_executor(
            None, container_peak_memory, args.export_container, stop
        )
        started = time.perf_counter()
        job = bench.client.post(
            f"/projects/{pid}/exports",
            json={
                "dataset": "measurements",
                "format": "csv",
                "time_from": (now - timedelta(days=365)).isoformat(),
                "time_to": now.isoformat(),
            },
        ).json()
        while job["status"] in ("queued", "running"):
            await asyncio.sleep(2)
            job = bench.client.get(f"/projects/{pid}/exports/{job['id']}").json()
        elapsed = (time.perf_counter() - started) * 1000
        stop.set()
        peaks = await memory_task
        bench.record(
            "export job, measurements, csv, 1 year",
            [elapsed],
            rows=job.get("row_count"),
            size_bytes=job.get("size_bytes"),
            status=job["status"],
            peak_memory_mib=max(peaks) if peaks else None,
            baseline_memory_mib=min(peaks) if peaks else None,
        )
        if job["status"] != "done":
            bench.notes.append(f"Export job failed: {job.get('error_message')}")

    # ingest burst through the webhook
    if wanted("ingest"):
        tokens = json.loads(args.manifest.read_text())["webhook_tokens"] if args.manifest else {}
        if tokens:
            source_id, token = next(iter(tokens.items()))
            external_ids = [
                r["external_id"]
                for r in await db.fetch(
                    "SELECT external_id FROM external_identities WHERE data_source_id = $1 AND device_id IS NOT NULL ORDER BY external_id LIMIT 200",
                    source_id,
                )
            ]
            before = await db.fetchval(
                "SELECT count(*) FROM source_events WHERE data_source_id = $1", source_id
            )
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(base_url=args.api, timeout=60) as client:

                async def send(i: int) -> float:
                    t = now - timedelta(seconds=args.ingest_events - i)
                    payload = {
                        "device_id": external_ids[i % len(external_ids)],
                        "time": t.isoformat(),
                        "lat": -24.0 + i * 1e-5,
                        "lon": 31.5,
                        "measurements": {"battery_voltage": 3.8, "activity": i % 100},
                    }
                    s = time.perf_counter()
                    r = await client.post(
                        f"/api/v1/ingest/http/{source_id}", json=payload, headers=headers
                    )
                    if r.status_code >= 400:
                        raise SystemExit(f"ingest: {r.status_code} {r.text[:200]}")
                    return (time.perf_counter() - s) * 1000

                burst_started = time.perf_counter()
                burst_wall_start = datetime.now(UTC)
                semaphore = asyncio.Semaphore(32)

                async def bounded(i: int) -> float:
                    async with semaphore:
                        return await send(i)

                latencies = await asyncio.gather(*(bounded(i) for i in range(args.ingest_events)))
                accepted_seconds = time.perf_counter() - burst_started
            while True:
                processed = await db.fetchval(
                    "SELECT count(*) FROM source_events WHERE data_source_id = $1 AND processing_status IN ('processed', 'duplicate', 'failed')",
                    source_id,
                )
                if (
                    processed - before >= args.ingest_events
                    or time.perf_counter() - burst_started > 600
                ):
                    break
                await asyncio.sleep(1)
            processed_seconds = time.perf_counter() - burst_started
            bench.record("ingest webhook request", list(latencies), rows=args.ingest_events)
            bench.results.append(
                {
                    "name": "ingest burst accepted",
                    "samples": 1,
                    "p50_ms": accepted_seconds * 1000,
                    "p95_ms": accepted_seconds * 1000,
                    "budget_ms": None,
                    "rows": args.ingest_events,
                    "events_per_second": round(args.ingest_events / accepted_seconds),
                }
            )
            bench.results.append(
                {
                    "name": "ingest burst decoded (end to end)",
                    "samples": 1,
                    "p50_ms": processed_seconds * 1000,
                    "p95_ms": processed_seconds * 1000,
                    "budget_ms": None,
                    "rows": processed - before,
                    "events_per_second": round((processed - before) / processed_seconds),
                }
            )
            lag = await db.fetchval(
                "SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM (m.ingested_at - s.ingested_at))) "
                "FROM source_events s JOIN measurements m ON m.source_event_id = s.id "
                "WHERE s.data_source_id = $1 AND s.ingested_at >= $2",
                source_id,
                burst_wall_start,
            )
            if lag is not None:
                bench.record("commit to canonical row (p95 from timestamps)", [float(lag) * 1000])
                bench.results[-1]["budget_ms"] = 2_000
        else:
            bench.notes.append("No manifest given, the ingest burst was skipped.")

    await db.close()
    write_report(args.output, project["name"], dict(totals), dict(counts), bench)
    sys.stdout.write(f"report written to {args.output}\n")


def write_report(
    path: Path, project_name: str, totals: dict[str, Any], counts: dict[str, Any], bench: Bench
) -> None:
    lines = [
        "# Benchmarks",
        "",
        "Results of `scripts/benchmark/run.py` against `scripts/benchmark/generate.py` data on the development machine. "
        "Budgets come from architecture 13.7 and 13.8; they are development budgets, not service levels. "
        "Rerun both scripts to refresh this page.",
        "",
        f"Last run: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "## Dataset",
        "",
        "| | Whole database | Benchmark project |",
        "| --- | --- | --- |",
        f"| Project | all | {project_name} |",
        f"| Devices | {totals['devices']:,} | |",
        f"| Entities | {totals['entities']:,} | {counts['entities']:,} |",
        f"| Positions | {totals['positions']:,} | {counts['positions']:,} |",
        f"| Measurements | {totals['measurements']:,} | {counts['measurements']:,} |",
        "",
        "## Results",
        "",
        "| Operation | Samples | p50 | p95 | Budget | Verdict | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in bench.results:
        budget = r.get("budget_ms")
        verdict = (
            "" if budget is None else ("within budget" if r["p95_ms"] <= budget else "over budget")
        )
        notes = []
        if r.get("rows") is not None:
            notes.append(f"{r['rows']:,} rows")
        if r.get("size_bytes"):
            notes.append(f"{r['size_bytes'] / 1e6:.1f} MB")
        if r.get("events_per_second"):
            notes.append(f"{r['events_per_second']:,} events/s")
        if r.get("peak_memory_mib") is not None:
            notes.append(
                f"export container {r['baseline_memory_mib']:.0f} to {r['peak_memory_mib']:.0f} MiB"
            )
        if r.get("status") and r["status"] != "done":
            notes.append(r["status"])
        lines.append(
            f"| {r['name']} | {r['samples']} | {_ms(r['p50_ms'])} | {_ms(r['p95_ms'])} | {_ms(budget) if budget else ''} | {verdict} | {', '.join(notes)} |"
        )
    if bench.notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in bench.notes]
    lines.append("")
    path.write_text("\n".join(lines))


def _ms(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 1000:.1f} s" if value >= 1000 else f"{value:.0f} ms"


if __name__ == "__main__":
    asyncio.run(main())
