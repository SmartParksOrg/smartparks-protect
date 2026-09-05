# Benchmarks

Results of `scripts/benchmark/run.py` against `scripts/benchmark/generate.py` data on the dev server (DigitalOcean, 4 vCPU, 8 GB, ams3). Budgets come from architecture 13.7 and 13.8; they are development budgets, not service levels. Rerun both scripts to refresh this page.

Last run: 2026-09-05 09:26 UTC.

## Dataset

| | Whole database | Benchmark project |
| --- | --- | --- |
| Project | all | Benchmark Kruger |
| Devices | 2,001 | |
| Entities | 1,001 | 125 |
| Positions | 44,231,968 | 5,660,840 |
| Measurements | 176,927,824 | 22,643,360 |

## Results

| Operation | Samples | p50 | p95 | Budget | Verdict | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| live map load | 5 | 39 ms | 101 ms | 3.0 s | within budget |  |
| viewport tile | 3 | 24 ms | 29 ms | 2.0 s | within budget |  |
| viewport tile | 3 | 21 ms | 25 ms | 2.0 s | within budget |  |
| viewport tile | 3 | 20 ms | 20 ms | 2.0 s | within budget |  |
| track 1 day | 5 | 33 ms | 125 ms | 2.5 s | within budget | 74 rows |
| track 30 days | 5 | 150 ms | 185 ms | 2.5 s | within budget | 4,048 rows |
| track 1 year | 5 | 566 ms | 862 ms | 3.0 s | within budget | 49,938 rows |
| explorer series, 1 metric, 30 days | 5 | 223 ms | 459 ms | 3.0 s | within budget | 2,221 rows |
| explorer series, 1 metric, 1 year | 5 | 904 ms | 1.7 s | 3.0 s | within budget | 1,459 rows |
| explorer series, 4 metrics x 5 entities, 7 days | 5 | 1.0 s | 1.1 s | 3.0 s | within budget | 11,616 rows |
| explorer metrics with data, 30 days | 3 | 1.5 s | 2.4 s | 3.0 s | within budget |  |
| explorer drill-down page | 5 | 124 ms | 126 ms | 1.0 s | within budget |  |
| direct export, positions, csv | 2 | 10.0 s | 10.3 s | 10.0 s | over budget | 39,453 rows |
| export job, measurements, csv, 1 year | 1 | 4359.1 s | 4359.1 s |  |  | 22,615,236 rows, 4868.2 MB, export container 107 to 129 MiB |
| ingest webhook request | 2000 | 713 ms | 1.4 s |  |  | 2,000 rows |
| ingest burst accepted | 1 | 49.7 s | 49.7 s |  |  | 2,000 rows, 40 events/s |
| ingest burst decoded (end to end) | 1 | 129.2 s | 129.2 s |  |  | 2,000 rows, 15 events/s |
| commit to canonical row (p95 from timestamps) | 1 | 76.6 s | 76.6 s | 2.0 s | over budget |  |

## Notes

- Live map returned 125 features (mode geojson).

## Reading the run

Measured on a 4 vCPU, 8 GB DigitalOcean droplet against a dataset at 0.2 of the reference
envelope (decision D91): 2,000 devices, 44 million positions, 177 million measurements,
compressed to 2.6 GB and 7.3 GB on disk. Every interactive read path is within its budget at
twice the previous dataset on a machine slower than the development laptop. Three things
stand out:

- **Direct export at the edge.** 39,453 positions to CSV took 10.3 s at p95 against a 10 s
  budget, five times the laptop's time for the same rows: the API serialises the rows on one
  vCPU. Above about 40,000 rows a job is the right path anyway (the 100,000 row cut-off of
  architecture 13.8); lowering the cut-off on small servers is the candidate change.
- **Export jobs stream within a bounded memory.** 22.6 million measurements, 4.9 GB of CSV,
  with the export worker between 107 and 129 MiB: the streaming writer holds (13.8). The
  throughput, 5,200 rows per second here against 30,000 on the laptop, sets the expectation
  that a year of one project's measurements is an hour's job on a small server.
- **The decoder path is the bottleneck under a burst.** 2,000 uplinks were accepted at 40
  per second and decoded end to end at 15 per second, with a p95 of 77 s from webhook to
  canonical row against the 2 s budget (14 s on the laptop). At this scale the normal load is
  about 7 uplinks per second, so the pipeline keeps up in steady state and drains a burst in
  minutes; at the full envelope (about 33 per second) one decoder on this server would fall
  behind. The decoder consumes a Redis Streams consumer group, so the remedy is more decoder
  replicas or a larger server; profiling the per-event cost is the follow-up before 2.0
  claims the full envelope.

The full-envelope figures remain extrapolated (D91): read paths scale with the bounded query
shapes and were flat between 0.1 and 0.2; ingest scales with decoder replicas.

## Earlier run on the development machine

2026-09-03 18:42 UTC, 0.1 of the envelope (22.4 million positions, 89.7 million measurements) on a
laptop:

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
