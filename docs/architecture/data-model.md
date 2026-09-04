# Data model

Schema as of migration 0001. Every time column is `TIMESTAMPTZ` in UTC. Domain objects have UUID primary keys; time-series rows have `bigint` identities with a composite primary key that includes the time column (decision D31).

## Access control

| Table | Purpose |
| --- | --- |
| `users` | Accounts, FastAPI-Users compatible. `is_superuser` is the server admin flag. `password_changed_at` invalidates older tokens. |
| `organizations` | Reserved tenant boundary, not enforced (D21) |
| `projects` | Access control and operational grouping |
| `project_memberships` | One role per user per project |
| `invitations` | Registration is by invitation; the token proves the email |
| `audit_log` | Who did what to which object, with request and trace ids |

## Domain

| Table | Purpose |
| --- | --- |
| `entity_types` | Kinds of entities with icon key and JSON schema for attributes |
| `entities` | The monitored objects, per project, optional geometry |
| `features` | Sites, zones, geofences, routes with PostGIS geometry |
| `device_types` | Families with driver key and capabilities |
| `devices` | Hardware, server level |
| `device_project_assignments` | `tstzrange` validity, GiST exclusion per device |
| `device_entity_assignments` | Same, per device |
| `data_sources` | External platform accounts, encrypted credentials, capabilities, link templates |
| `data_source_project_scopes` | Optional project scoping and auto-assign flag |
| `external_identities` | `(data source, external id)` to device, null device while unknown |
| `metrics` | Registry of metric keys with unit, value type and category |
| `device_log_files` | Raw log files and browser syncs as managed assets: file in the log files bucket, SHA-256 unique per device, status, frame and record counts, period, firmware, the file's trace (architecture 25.6) |

## Time series (hypertables)

| Table | Partition column | Compression segment | Retention |
| --- | --- | --- | --- |
| `source_events` | `ingested_at` | `data_source_id` | 730 days by default |
| `positions` | `time` | `device_id` | none |
| `measurements` | `time` | `device_id` | none |
| `gateway_receptions` | `time` | `gateway_id` | none |
| `device_state_history` | `time` | `device_id` | none |

Chunks are 7 days (30 for state history). Compression starts after 7 days. TimescaleDB does not allow foreign keys to a hypertable, so references from canonical rows to their source event carry `source_event_id` and `source_event_ingested_at` as plain columns.

Current state lives in regular tables that are updated in the same transaction as the canonical rows: `device_current_state`, `entity_current_state` and `connectivity_state` (per device and data source).

## Events and rules

`events` are domain facts with type, severity, optional geometry and context. `alerts` are events that need a person, with an open, acknowledged, resolved lifecycle. `rules` and `rule_versions` hold versioned rule documents; every event references the version that produced it. Rules are filled in during phase 5.

## Traces

`processing_traces` (one per flow, with class and compact flag), `processing_steps` (ordered steps with timing, references and an error id) and `application_errors` (stable error code, severity, retryable and user-actionable flags, technical context).

## Indexes

From measured needs only, as the architecture asks. Migration 0001 creates: time plus device, entity and project on positions and measurements (with metric key), GiST on every geometry, unique canonical key plus time on positions and measurements, and the lookups that the admin API and the pipeline use (external id per source, processing status, trace id). BRIN indexes on time are added in phase 4 once the benchmark shows where they pay off.

## Enumerations

Enumerated columns are text with a check constraint generated from a `StrEnum` in `shared/enums.py`, not PostgreSQL enum types, so a new value is a normal migration.
