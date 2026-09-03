# 0003. PostgreSQL 17 with TimescaleDB and PostGIS from migration 1

Date: 2026-09-03

Status: accepted, confirmed at the phase 4 decision gate on 2026-09-03

## Context

The design envelope is 250 million positions, one billion measurements, five years online, 250 source events per second sustained. Positions, measurements, source events and gateway receptions are append-only time series that need time-based pruning, compression and fast time-range queries. PostGIS is required for geofences, viewport queries and vector tiles.

## Decision

PostgreSQL 17 with the PostGIS and TimescaleDB extensions, using the `timescale/timescaledb-ha` image which ships both. The time-series tables are hypertables from the first migration. Compression and retention policies are explicit migration steps. A benchmark in phase 4 at one tenth of the envelope confirms TimescaleDB or replaces it with native partitioning; hypertable creation is isolated in one migration so the swap touches one place.

## Alternatives considered

- Plain PostgreSQL with native partitioning: works, but partition management, compression and continuous aggregates must be built by hand. Kept as the fallback.
- Add TimescaleDB later: retrofitting hypertables on tables with hundreds of millions of rows is the expensive path.
- A separate time-series database: a second system to run, back up and join against.

## Consequences

One database for everything. The TimescaleDB community licence permits self-hosting; managed-service resale is out of scope. Migrations must run against the same image in CI.

## Decision gate, phase 4

The benchmark at one hundredth of the envelope (2.3 million positions, 9.2 million measurements, generated in about two minutes with COPY) ran every read path far inside its budget: live map and tiles in tens of milliseconds, a one year track in about 40 ms, Data Explorer aggregates with `time_bucket` in 30 to 200 ms. `first`, `last` and `time_bucket` are used by the aggregation API, compression and retention are policies instead of hand-written partition management, and continuous aggregates are available when a query gets expensive. TimescaleDB stays. Native partitioning remains the fallback; the hypertable setup is still isolated in migration 0001. The full results are in `docs/operations/benchmarks.md`; the scale reasoning in `docs/architecture/scalability.md`.
