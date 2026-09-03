# 0003. PostgreSQL 17 with TimescaleDB and PostGIS from migration 1

Date: 2026-09-03

Status: accepted, decision gate in phase 4

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
