# Scalability

What the phase 4 benchmark showed, what it means for the reference envelope (architecture 13.1: 25,000 devices, 250 million positions, one billion measurements, 250 source events per second sustained), and what was changed because of it. The numbers are from `docs/operations/benchmarks.md`; rerun the scripts to refresh them.

## Dataset

`scripts/benchmark/generate.py` loads the dataset with COPY from several connections. Two runs on the development machine (WSL2, Docker Desktop, one NVMe disk):

| Scale | Devices | Entities | Positions | Measurements | Size before compression | Time |
| --- | --- | --- | --- | --- | --- | --- |
| 1/100 | 103 | 51 | 2.3 million | 9.2 million | 1.5 GB + 6.2 GB | 2 min |
| 1/10 | 1,003 | 501 | 22.4 million | 89.7 million | 14 GB + 59 GB | 39 min |

About 670 bytes per measurement row before compression; most of that is the four indexes and the canonical key text.

Compressing the chunks older than 200 days by hand (the policy does it after seven days, on a twelve hour schedule) gave the measured ratios:

| Hypertable | Before | After | Ratio |
| --- | --- | --- | --- |
| measurements (24 chunks) | 2,741 MB | 168 MB | 16.3 |
| positions (24 chunks) | 674 MB | 65 MB | 10.4 |

At those ratios the full envelope is roughly 40 GB of compressed measurements and 10 GB of positions, plus the recent uncompressed week: five years online on ordinary hardware. Retention exists as a policy only for raw source events (730 days); canonical rows stay.

## Read paths

Every read path stayed inside its budget at both scales. At 1/10 (the benchmark project holds 2.8 million positions and 11.4 million measurements):

| Operation | p50 | p95 | Budget |
| --- | --- | --- | --- |
| Live map, 63 entities (current state table, GeoJSON) | 72 ms | 246 ms | 3 s |
| Viewport tile (`ST_AsMVT` over current state) | 5 to 18 ms | 52 ms | 2 s |
| Track over 30 days (4,100 points) | 34 ms | 2.3 s | 2.5 s |
| Track over a year (50,000 points, decimated) | 214 ms | 1.1 s | 3 s |
| Data Explorer, one series, a year (automatic 6 h buckets) | 51 ms | 946 ms | 3 s |
| Data Explorer, 20 series over 7 days (12,000 points) | 216 ms | 674 ms | 3 s |
| Metrics with data, 30 days | 51 ms | 290 ms | 3 s |
| Drill-down page of 500 rows | 14 ms | 87 ms | 1 s |
| Direct export of 46,500 positions as CSV | 2.0 s | 2.0 s | 10 s |

The p95 values are the first, cold read of each series (five samples each); the warm reads are the p50. At 1/100 everything was under 200 ms. Why they scale: the live map never touches history (`entity_current_state`, architecture 13.2); tracks and aggregates are bounded by the point ladder (decision D41) and read through the `(entity_id, time)` and `(project_id, metric_key, time)` indexes, so the work grows with the answer, not with the table. Continuous aggregates for hourly and daily buckets stay in reserve for the moment a project's raw scan gets expensive; the year-long `time_bucket` scan of one entity is still under a second cold.

## Exports

The export service streams plain column rows through a server-side cursor in batches of 2,000 into a temporary file and uploads it to MinIO. The one year measurement export of the benchmark project at 1/10 scale wrote 11.4 million rows, 2.4 GB of CSV, in 6 minutes 24 seconds (about 30,000 rows per second) while the worker's resident memory moved from 85 to 115 MiB. That is the target from architecture 13.8: the file grows, the process does not.

Three findings on the way there. A progress commit on the streaming session closed the server-side cursor, so progress now goes through its own session. Loading ORM objects grew the worker to 269 MiB for 1.3 million rows because every object stayed in the session; the row sources select plain columns now. And `docker stats` counts the page cache of the file being written (it showed 1.8 GiB for the 2.4 GB export), so the benchmark samples the process's resident memory from `/proc` instead.

## Ingest

The webhook accepted a burst of 2,000 events spread over 200 devices at about 210 per second, with a p95 request latency under 300 ms, so the API side meets the sustained target. The decoder did not: one consumer handled about 60 events per second, so the burst took 33 seconds to become canonical rows and the commit-to-row lag reached 21 seconds against a 2 second budget.

The first cause was a strictly sequential consumer. The bus now handles a batch in lanes: messages of one device in order in one lane, different lanes concurrently, `BUS_CONCURRENCY` lanes per worker (default 8). Handlers were already safe for this: canonical keys make repeated deliveries idempotent and current state only moves forward in time. That took one decoder from about 60 to about 90 events per second, and raising the lanes from 8 to 32 changed nothing, so the remaining limit is CPU in the decoder process, about 11 ms of Python per event (ORM, validation, trace steps). Two ways forward, both open:

- More decoder processes. Every service is stateless and the consumer group shares the work, so three decoders give the sustained 250 per second. The compose file pins one container per service; running replicas is a deployment topic for phase 7 (Ansible), where the decoder count becomes a host variable.
- Less work per event. Profile the decoder, count the statements per event and batch the trace steps into one insert. This is the cheaper win and is the first performance item of the next session.

Until one of them lands, the realtime budget (p95 under 2 seconds from commit) holds up to about 90 events per second per decoder, which covers today's deployments but not the envelope.

## What still needs proving

- The benchmark ran at one tenth of the envelope on a laptop and at one fifth on the dev server (decision D91, [benchmarks](../operations/benchmarks.md)): every read path within budget, the decoder path the bottleneck under a burst (15 uplinks per second end to end on 4 vCPU), a direct export at the edge of its budget. The full envelope is extrapolated until a production-sized server exists; the generator writes in time order and compresses behind the write frontier, so the disk holds compressed history plus one block (scale 0.2 took 4.1 hours and 10 GB on disk).
- Compression was measured by compressing old chunks by hand and, since the 0.2 run, by the generator's `--compress`; the policy job itself (every twelve hours, chunks older than seven days) has not been watched over a full cycle on a long-running stack.
- The per-event cost of the decoder path needs profiling before the full envelope is claimed; more decoder replicas are the known remedy.
- Rules with rolling windows and geofences (phase 5) add the first read path that scans recent history per event; the benchmark gets a case for it then.
