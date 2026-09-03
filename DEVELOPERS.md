# Developer documentation

This file describes how the Smart Parks Protect codebase works today. The plan for where it is going lives in `PROJECT_PLAN.md`. The product and architecture rationale lives in `Smart_Parks_Protect_Concept_Architecture.md`. Conventions live in `CONVENTIONS.md`.

Status: pre-alpha. Phases 0 and 1 are done: workspace, compose stack, CI, docs, the canonical schema with migrations, authentication by invitation, RBAC, the trace contract, assignment resolution and the admin API. Nothing ingests data yet (phase 2). Sections marked "planned" describe agreed design that is not implemented; they are rewritten as the code lands.

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
| Database | PostgreSQL 17 + PostGIS + TimescaleDB (`timescale/timescaledb-ha:pg17.10-ts2.29.2`) | Hypertables for positions, measurements, source events, gateway receptions. Decision gate in phase 4 |
| Event bus and cache | Redis 7.4, Redis Streams with consumer groups | One broker; `EventBus` interface in `shared/bus.py` (planned, phase 2) |
| Object storage | MinIO | Raw log files, uploads, exports. Not for telemetry |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, FastAPI-Users | `uv` workspace, one `uv.lock`, exact `==` pins in every `pyproject.toml` |
| Frontend | React 19, Vite, TypeScript strict, Tailwind 4, shadcn/ui (Radix), TanStack Query, Zustand, React Hook Form + Zod, React Router 7 | MapLibre GL JS for maps, Apache ECharts for charts. Rules in `services/frontend/FRONTEND_CONVENTIONS.md` |
| Tests | pytest, Vitest, Playwright (phase 3) | API tests run against real Postgres, Redis and MinIO |
| Docs | MkDocs 1.x with Material, ADRs in `docs/adr/` | `mkdocs build --strict` in CI. MkDocs 2 removes plugins and is pinned out |
| Deployment | Docker Compose, Ansible, Nginx, Let's Encrypt | From phase 7 |

## Repository structure

What exists today. The full target tree is in `PROJECT_PLAN.md` under "Target repository structure".

```
smartparks-protect/
├── services/
│   ├── api/                 # FastAPI service `protect_api`: auth/, routers/, schemas/, deps.py, alembic/
│   └── frontend/            # React + Vite + TypeScript, nginx Dockerfile, FRONTEND_CONVENTIONS.md
├── shared/shared/           # package `shared`: config, database, logger, version, enums, permissions,
│                            # models/ (by area), domain/assignments.py, trace.py, timeutil.py, secrets.py
├── tests/                   # tests/shared, tests/api, tests/fixtures/payloads
├── docs/                    # MkDocs site, docs/adr/ holds the ADRs
├── docker/chirpstack/       # ChirpStack, gateway bridge and Mosquitto config for the compose profile
├── scripts/dev.sh           # daily commands
├── .githooks/commit-msg     # strips assistant trailers (D28), installed with scripts/dev.sh hooks
├── .github/workflows/ci.yml
├── docker-compose.yml
├── pyproject.toml           # uv workspace root, ruff, mypy, pytest config
└── uv.lock
```

The rules behind it:

- `services/<name>/` is one container each. Services import from `shared` and never from each other.
- `shared/shared/` is the only place for models, schemas, the bus, the trace helpers, device drivers and connectivity adapters.
- Provider-specific code lives only in `shared/connectivity/adapters/<provider>/`. Device-specific code lives only in `shared/device_drivers/<family>/`. A test enforces this from phase 7.
- `tests/<package>/` mirrors the packages; CI runs one job per directory. `tests/fixtures/payloads/` holds recorded real payloads with a note where each came from.

## Core concepts for developers

- **Device versus Entity.** A Device is hardware and exists at server level without a project column. An Entity is the real-world object (animal, vehicle, gate). They are linked by `device_entity_assignments` with a validity range. Project membership of a device is `device_project_assignments`, also time-bounded. Both use `tstzrange` with an exclusion constraint so ranges never overlap.
- **Attribution uses canonical time.** A record belongs to the project and entity that were assigned at the record's device-origin time, not at ingest time. `shared/domain/assignments.py` is the one place that resolves this (`resolve_attribution(session, device_id, at)`).
- **DataSource and ExternalIdentity.** A DataSource is an external platform account (a ChirpStack instance, a KPN account). ExternalIdentity maps `(data_source, external_id)` such as a DevEUI to a Device. Incoming data is resolved through this pair. Unknown identities are retained and shown in Needs Attention, never guessed.
- **Four data levels.** Raw SourceEvent (immutable), decoded (driver output), normalized canonical rows (positions, measurements, states, events), aggregated (server-side buckets). Maps, charts, rules and exports use canonical rows.
- **Canonical key and deduplication.** For OpenCollar: device EUI + device-origin timestamp + record type, plus a payload fingerprint where needed. Several deliveries (LoRaWAN, WebBLE, log file, Iridium) link to one canonical row. Never use network, satellite, sync, upload or ingest time in the key.
- **ProcessingTrace.** Every flow (inbound message, command, import, delivery, export) has a trace id and ordered steps with status and a structured ApplicationError on failure. Successful routine telemetry writes compact traces. `shared/trace.py` has the `Tracer`; a step is `async with tracer.step(component, operation)`; raise `ApplicationError(code, message, component, ...)` for expected failures, anything else is recorded as `INTERNAL_ERROR` and re-raised.
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

## Local development

Requirements: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), Node 24. On WSL2, enable the Docker Desktop WSL integration for the distro.

```bash
cp .env.example .env
scripts/dev.sh hooks                      # git config core.hooksPath .githooks
scripts/dev.sh up                         # docker compose up -d --build: postgres, redis, minio, api, frontend
docker compose --profile chirpstack up -d # adds a local ChirpStack (web UI on :8080, MQTT on :1883, REST on :8090)
uv sync --all-groups                      # python environment for tests, linters and docs
cd services/frontend && npm ci            # frontend dependencies
```

Daily commands through `scripts/dev.sh`: `up`, `down`, `logs [service]`, `test`, `lint`, `format`, `docs`, `hooks`. `migrate` and `sweep` arrive in phases 1 and 3.

Ports (all bound to localhost except the frontend): API 8000, frontend 3000, Postgres 5432, Redis 6379, MinIO 9000 and console 9001. `/api/docs` is the OpenAPI UI, `/api/health` reports database, Redis and MinIO, `/api/version` reports the version and commit.

The frontend dev server (`npm run dev` in `services/frontend`) runs on :5173 and proxies `/api` and `/ws` to `VITE_PROXY_TARGET` from the root `.env`. The frontend reads the root `.env`, there is no second env file.

### Python workspace

One `uv` workspace: `shared/` and `services/*` (the frontend is excluded). Every `pyproject.toml` pins exact versions; `uv.lock` is committed and CI installs with `--frozen`. Add a dependency with `uv add --package smartparks-protect-shared <name>`, then pin it to the resolved version.

`shared/shared/` today: `config.py` (pydantic-settings, `get_settings()` cached, raises on missing values), `database.py` (one async engine per process, `get_session` dependency, `session_scope` for workers), `logger.py` (JSON or text, `request_id` and `trace_id` context variables, `get_logger(name).info("msg", key=value)`), `version.py` (reads `VERSION`, falls back to `v0.0.0-dev`).

`services/api/protect_api/`: `main.py` builds the app, `middleware.py` sets the request id (inbound `X-Request-ID` is kept), `health.py` runs the three dependency checks concurrently with a 3 second timeout each and answers 503 when one fails.

### Frontend

`npm run build` is `tsc -b && vite build`: a type error fails the build and the Docker image. `npm run lint` is ESLint, `npm run test` is Vitest with Testing Library. shadcn/ui components are added with `npx shadcn@latest add <name>` and land in `src/components/ui/`, which ESLint ignores. Brand colours and semantic tokens are CSS variables in `src/index.css`; the logo SVGs in `src/assets/brand/` use `currentColor`.

## Database migrations

Migrations live in `services/api/alembic/versions/`, named `<rev>_<slug>.py` with a four digit revision. They run synchronously through psycopg (`alembic/env.py` rewrites the async URL). `scripts/dev.sh migrate` applies them locally; in docker compose the one-shot `protect-migrate` container runs `alembic upgrade head` before the API starts (decision D30). `scripts/dev.sh revision "message"` autogenerates a draft from the models; hypertable creation, compression and retention policies are written by hand as explicit steps (see migration 0001). The test suite migrates the test database up at the start and down at the end, so every run is an up-and-down test. `alembic check` must report no drift; the Alembic environment ignores the time index TimescaleDB adds to every hypertable.

Hypertables cannot be referenced by foreign keys, so canonical rows carry `source_event_id` and `source_event_ingested_at` as plain columns.

## Authentication and access control

FastAPI-Users with JWT bearer tokens under `/api/v1/auth`. Registration is by invitation only (`POST /api/v1/auth/register` with the invitation token); the token proves the email, so accounts are verified on creation and the invitation's role becomes a membership. The JWT strategy adds `iat` and rejects tokens issued before `users.password_changed_at`, so a password change logs out other sessions. Password reset uses the FastAPI-Users flow; mail goes through `protect_api/mailer.py`, which logs instead of sending when SMTP is not configured or the recipient is not in `DEV_NOTIFY_EMAILS` on a non-production server.

Dependencies in `protect_api/deps.py`: `require_server_admin`, `get_project_context` (reads `{project_id}` from the path, 404 for unknown projects, 403 without membership), `require_project_role(role)` and `require_permission(key)`. Permission keys and their mapping from roles live in `shared/permissions.py`. Every mutating endpoint calls `record_audit` in the same transaction.

## API conventions

- Everything under `/api/v1` (D29). `/api/health` and `/api/version` stay unversioned.
- Every list endpoint takes `limit` (max 500) and `cursor` through `protect_api/pagination.py` and returns `{items, next_cursor}`. A test fails when a list endpoint lacks `limit`.
- Geometry goes in and out as GeoJSON (`geometry` field); the helpers in `protect_api/crud.py` convert with shapely.
- Constraint violations become 409 with the constraint name in the message (`flush_or_409`).
- Credentials of data sources are encrypted with Fernet (`shared/secrets.py`, key from `CREDENTIALS_KEY`) and never returned.

## Testing

```bash
uv run pytest -q                            # all python tests, needs the compose stack for `integration` tests
uv run pytest -q -m "not integration"       # unit tests only
uv run pytest tests/shared -q               # one package
cd services/frontend && npm run test && npm run build
```

`tests/conftest.py` sets default environment values that match `.env.example`, so tests run against the local compose stack without extra setup. CI runs one job per package (`tests/shared`, `tests/api`) against Postgres/Timescale and Redis service containers and a MinIO container.

All tests share one event loop (`asyncio_default_test_loop_scope = session`) because asyncpg connections cannot move between loops. `tests/api/conftest.py` has helpers for actors per role (`actor`, `project_actor`), committed fixture rows and invitations. `tests/api/test_phase1_scenario.py` runs the phase 1 exit criteria end to end.

- Drivers, adapters and rules are tested with recorded fixtures under `tests/fixtures/payloads/`. Add the source of every fixture in a `README.md` next to it.
- API tests use a real Postgres/Timescale container. No mocked SQL.
- Playwright smoke opens every page at 390, 768 and 1440 px.
- Benchmarks (`scripts/benchmark/`) run on demand, not in CI. Results go to `docs/operations/benchmarks.md`.

## Releases

`VERSION` is written and committed before each tag (it does not exist before v0.1.0; the code reports `v0.0.0-dev`). `CHANGELOG.md` has an Unreleased section that becomes the release notes. Servers run tags, never `main`, except a dev server.

## Logging

All services write one JSON object per line to stdout (`LOG_FORMAT=json`, the container default) with `service`, `trace_id` and `request_id` where set; `LOG_FORMAT=text` gives readable lines for development. `docker compose logs -f <service>` follows a service. Uvicorn's own access log is not yet routed through the structured logger.
