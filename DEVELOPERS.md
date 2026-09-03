# Developer documentation

This file describes how the Smart Parks Protect codebase works today. The plan for where it is going lives in `PROJECT_PLAN.md`. The product and architecture rationale lives in `Smart_Parks_Protect_Concept_Architecture.md`. Conventions live in `CONVENTIONS.md`.

Status: pre-alpha. The repository holds documentation and the project plan. No service runs yet. Sections marked "planned" describe agreed design that is not implemented; they are rewritten as the code lands.

## Project overview

**Smart Parks Protect** is a self-hosted operational data platform that:
- Ingests data from field devices and IoT platforms (OpenCollar over LoRaWAN first, then Traccar, Iridium via Cloudloop, generic MQTT and HTTP, and detections from AddaxAI Connect)
- Normalizes everything into one Smart Parks domain: Entities, Devices, Positions, Measurements, Events
- Provides a live map, a Data Explorer, exports, a stateful rules engine, device control and outbound integrations such as EarthRanger

**Architecture:** services in a monorepo, orchestrated with Docker Compose, Redis Streams as the event bus, PostgreSQL 17 with PostGIS and TimescaleDB, MinIO for files.
**Deployment:** local docker compose during early phases, then Ubuntu VM with Ansible.
**Design envelope:** 25,000 registered devices, 10,000 reporting, 5,000 entities on the map, 250 source events per second sustained, 250 million positions and 1 billion measurements online, 100 concurrent users. These are architecture targets, not current capacity.
**Relationship to AddaxAI Connect:** written from scratch; AddaxAI Connect is the reference for patterns (auth flow, RBAC, deployment, notifications, frontend conventions). A local clone is expected at `/home/tim/apps/AddaxAI-Connect` for comparison.

## Working with the plan

- Read `PROJECT_PLAN.md` at the start of every session and work the next unchecked item.
- Tick the checkbox in the same commit as the code and the docs.
- Add a session log entry at the end of every session.
- Update this file whenever a mechanism, convention or command changes.

## Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Database | PostgreSQL 17 + PostGIS + TimescaleDB (`timescale/timescaledb-ha`) | Hypertables for positions, measurements, source events, gateway receptions. Decision gate in phase 4 |
| Event bus and cache | Redis 7, Redis Streams with consumer groups | One broker; `EventBus` interface in `shared/bus.py` (planned) |
| Object storage | MinIO | Raw log files, uploads, exports. Not for telemetry |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, FastAPI-Users | `uv` workspace, one lockfile, exact pins |
| Frontend | React 19, Vite, TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, React Hook Form + Zod | MapLibre GL JS for maps, Apache ECharts for charts |
| Tests | pytest, Vitest, Playwright | API tests run against a real database container |
| Docs | MkDocs Material, ADRs in `docs/adr/` | `mkdocs build --strict` in CI |
| Deployment | Docker Compose, Ansible, Nginx, Let's Encrypt | From phase 7 |

## Repository structure (planned)

The target tree is in `PROJECT_PLAN.md` under "Target repository structure". The rules behind it:

- `services/<name>/` is one container each. Services import from `shared` and never from each other.
- `shared/shared/` is the only place for models, schemas, the bus, the trace helpers, device drivers and connectivity adapters.
- Provider-specific code lives only in `shared/connectivity/adapters/<provider>/`. Device-specific code lives only in `shared/device_drivers/<family>/`. A test enforces this from phase 7.
- `tests/<package>/` mirrors the packages; CI runs one job per directory. `tests/fixtures/payloads/` holds recorded real payloads with a note where each came from.

## Core concepts for developers

- **Device versus Entity.** A Device is hardware and exists at server level without a project column. An Entity is the real-world object (animal, vehicle, gate). They are linked by `device_entity_assignments` with a validity range. Project membership of a device is `device_project_assignments`, also time-bounded. Both use `tstzrange` with an exclusion constraint so ranges never overlap.
- **Attribution uses canonical time.** A record belongs to the project and entity that were assigned at the record's device-origin time, not at ingest time. `shared/domain/assignments.py` (planned) is the one place that resolves this.
- **DataSource and ExternalIdentity.** A DataSource is an external platform account (a ChirpStack instance, a KPN account). ExternalIdentity maps `(data_source, external_id)` such as a DevEUI to a Device. Incoming data is resolved through this pair. Unknown identities are retained and shown in Needs Attention, never guessed.
- **Four data levels.** Raw SourceEvent (immutable), decoded (driver output), normalized canonical rows (positions, measurements, states, events), aggregated (server-side buckets). Maps, charts, rules and exports use canonical rows.
- **Canonical key and deduplication.** For OpenCollar: device EUI + device-origin timestamp + record type, plus a payload fingerprint where needed. Several deliveries (LoRaWAN, WebBLE, log file, Iridium) link to one canonical row. Never use network, satellite, sync, upload or ingest time in the key.
- **ProcessingTrace.** Every flow (inbound message, command, import, delivery, export) has a trace id and ordered steps with status and a structured ApplicationError on failure. Successful routine telemetry writes compact traces.
- **Bounded queries.** Every user-facing list, map, chart and export endpoint has an explicit bound. An endpoint that could return the whole history is a defect.

## Conventions specific to this repo

### Timestamps

- Every time column is `TIMESTAMPTZ` and stored in UTC. No naive datetimes anywhere. A helper raises on a naive datetime.
- Canonical rows have `time` (device-origin, defined by the driver per record type) and `ingested_at`.
- SourceEvents keep provenance times separately: `network_received_at`, `satellite_delivered_at`, `ble_synced_at`, `file_uploaded_at`, `ingested_at`.
- Display timezone is a user or project setting applied in the frontend and in exports on request. UTC is the export default.

### Event bus (planned)

- Topics are `<object>.<verb>` in past tense: `source_event.received`, `position.created`, `device.state_changed`, `event.created`, `alert.created`, `command.updated`, `delivery.updated`.
- Each worker is one consumer group. Messages are acked after the database transaction commits. Failed messages retry with backoff and land in `<topic>.dead` after the configured attempts.
- Every worker stamps a heartbeat key; 15 minutes without a stamp is stale. The health endpoint and the liveness alert read the same rule.

### Errors

- Application errors use the stable codes from architecture section 26.5 (`PAYLOAD_DECODE_FAILED`, `DEVICE_NOT_FOUND`, `TIMESTAMP_INVALID`, ...). Each has severity, retryable and user-actionable flags.
- Crash early in development. Unexpected states raise; they are not logged and skipped.

### Naming

- Containers `protect-<service>`, network `protect-network`, database `smartparks_protect`.
- Python packages use snake_case, adapter keys and driver keys are lowercase identifiers (`chirpstack`, `kpn_thingpark`, `loriot`, `opencollar`).
- Metric keys are lowercase snake_case with the canonical unit in the registry (`battery_voltage` in V, `temperature` in °C).
- Icon keys are dotted (`wildlife.wolf`, `device.lora_gateway`).

## Local development (planned, filled in during phase 0)

```bash
cp .env.example .env
docker compose up -d                      # infrastructure, api, frontend
docker compose --profile chirpstack up -d # adds a local ChirpStack for LoRaWAN testing
```

Backend and frontend commands, the simulator and the benchmark scripts are documented here once they exist.

## Database migrations (planned)

Migrations live in `services/api/alembic/versions/`. Hypertable creation, compression and retention policies are explicit migration steps, not autogenerated. Migrations must apply and revert from an empty database in CI.

## Testing (planned)

```bash
uv run pytest tests/ -q          # all python tests
uv run pytest tests/shared -q    # one package
cd services/frontend && npm run test && npm run build
```

- Drivers, adapters and rules are tested with recorded fixtures under `tests/fixtures/payloads/`. Add the source of every fixture in a `README.md` next to it.
- API tests use a real Postgres/Timescale container. No mocked SQL.
- Playwright smoke opens every page at 390, 768 and 1440 px.
- Benchmarks (`scripts/benchmark/`) run on demand, not in CI. Results go to `docs/operations/benchmarks.md`.

## Releases

`VERSION` is written and committed before each tag. `CHANGELOG.md` has an Unreleased section that becomes the release notes. Servers run tags, never `main`, except a dev server.

## Logging

All services write structured JSON to stdout with `service`, `trace_id` and `request_id` fields where available. `docker compose logs -f <service>` follows a service.
