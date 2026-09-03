# Benchmarks

Results of `scripts/benchmark/run.py` against `scripts/benchmark/generate.py` data on the development machine. Budgets come from architecture 13.7 and 13.8; they are development budgets, not service levels. Rerun both scripts to refresh this page.

Last run: 2026-09-03 18:42 UTC.

## Dataset

| | Whole database | Benchmark project |
| --- | --- | --- |
| Project | all | Benchmark Kruger |
| Devices | 1,003 | |
| Entities | 501 | 63 |
| Positions | 22,424,972 | 2,844,200 |
| Measurements | 89,699,872 | 11,376,800 |

## Results

| Operation | Samples | p50 | p95 | Budget | Verdict | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| live map load | 5 | 72 ms | 246 ms | 3.0 s | within budget |  |
| viewport tile | 3 | 18 ms | 52 ms | 2.0 s | within budget |  |
| viewport tile | 3 | 14 ms | 14 ms | 2.0 s | within budget |  |
| viewport tile | 3 | 5 ms | 5 ms | 2.0 s | within budget |  |
| track 1 day | 5 | 11 ms | 61 ms | 2.5 s | within budget | 132 rows |
| track 30 days | 5 | 34 ms | 2.3 s | 2.5 s | within budget | 4,105 rows |
| track 1 year | 5 | 214 ms | 1.1 s | 3.0 s | within budget | 49,996 rows |
| explorer series, 1 metric, 30 days | 5 | 34 ms | 97 ms | 3.0 s | within budget | 2,235 rows |
| explorer series, 1 metric, 1 year | 5 | 51 ms | 946 ms | 3.0 s | within budget | 1,460 rows |
| explorer series, 4 metrics x 5 entities, 7 days | 5 | 216 ms | 674 ms | 3.0 s | within budget | 12,160 rows |
| explorer metrics with data, 30 days | 3 | 51 ms | 290 ms | 3.0 s | within budget |  |
| explorer drill-down page | 5 | 14 ms | 87 ms | 1.0 s | within budget |  |
| direct export, positions, csv | 2 | 2.0 s | 2.0 s | 10.0 s | within budget | 46,517 rows |
| export job, measurements, csv, 1 year | 1 | 381.8 s | 381.8 s |  |  | 11,375,836 rows, 2446.0 MB, worker resident memory 85 to 115 MiB (measured in a second run of the export section; the first run's docker stats figure counted the page cache of the 2.4 GB file) |
| ingest webhook request | 2000 | 144 ms | 262 ms |  |  | 2,000 rows |
| ingest burst accepted | 1 | 9.8 s | 9.8 s |  |  | 2,000 rows, 205 events/s |
| ingest burst decoded (end to end) | 1 | 24.8 s | 24.8 s |  |  | 2,000 rows, 81 events/s |
| commit to canonical row (p95 from timestamps) | 1 | 14.1 s | 14.1 s | 2.0 s | over budget |  |

## Notes

- Live map returned 63 features (mode geojson).
