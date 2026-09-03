# 0007. Canonical domain model

Date: 2026-09-03

Status: accepted

## Context

Architecture sections 5, 6, 10 and 28 describe a domain that must outlive any single device family or network provider: entities separate from devices, assignments with validity, raw data retained, normalized rows with stable schemas, a metric registry. Decisions D6 (one entities table with typed JSONB attributes), D7 (one measurements table with typed value columns) and D31 (UUID for domain objects, bigint for time series) shape the tables.

## Decision

The schema in migration 0001 and `docs/architecture/data-model.md`. In particular:

- Devices are server-level; project membership and entity monitoring are time-bounded assignments with an exclusion constraint against overlaps.
- Canonical rows carry the resolved `project_id` and `entity_id` next to `device_id` (see 0010).
- Enumerated columns are text with a check constraint from a `StrEnum`, not PostgreSQL enums.
- Metrics use the key as primary key; measurements reference it directly.
- Source events are partitioned on `ingested_at` because the device time is only known after decoding.

## Alternatives considered

- Subtype tables per entity kind: rejected until a kind needs heavy relational queries (D6).
- One value column with a type tag: loses numeric indexing and aggregation (D7).
- PostgreSQL enum types: adding a value cannot run inside a transaction and complicates migrations.

## Consequences

Administrators add entity types, device types and metrics as rows. The schema allows every later phase without a domain redesign; phases add tables (commands, integrations, curation) rather than reshaping these.
