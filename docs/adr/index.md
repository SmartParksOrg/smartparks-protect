# Architecture decision records

Significant technical decisions are recorded as short ADRs: what was chosen, why, which alternatives were considered and what follows from it. Records are never edited after acceptance; a later ADR supersedes an earlier one.

Copy `template.md` for a new record. Number sequentially. Link the ADR from `PROJECT_PLAN.md` when the related decision in the decisions table is made.

| Number | Title | Status |
| --- | --- | --- |
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-start-from-scratch.md) | Start from scratch, reuse AddaxAI Connect patterns | accepted |
| [0003](0003-postgresql-timescaledb-postgis.md) | PostgreSQL 17 with TimescaleDB and PostGIS from migration 1 | accepted, gate in phase 4 |
| [0004](0004-redis-streams-event-bus.md) | Redis Streams as the event bus | accepted |
| [0005](0005-backend-and-frontend-stack.md) | Backend and frontend stack | accepted |
| [0006](0006-schema-versioning.md) | Schema versioning for bus messages, webhooks and API responses | accepted |
| [0007](0007-canonical-domain-model.md) | Canonical domain model | accepted |
| [0008](0008-device-timestamp-deduplication.md) | Device timestamp deduplication | accepted |
| [0009](0009-processing-trace-model.md) | Processing trace model | accepted |
| [0010](0010-assignment-attribution.md) | Assignment attribution stored on canonical rows | accepted |
| [0011](0011-connectivity-adapter-boundary.md) | Connectivity adapter boundary | accepted |
- [0012 rule representation](0012-rule-representation.md)
