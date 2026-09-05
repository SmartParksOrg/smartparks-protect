# Developer documentation

This file describes how the Smart Parks Protect codebase works today. The plan for where it is going lives in `PROJECT_PLAN.md`. The product and architecture rationale lives in `Smart_Parks_Protect_Concept_Architecture.md`. Conventions live in `CONVENTIONS.md`.

Status: v0.6.0 released (phases 7, 8 and 9: production LoRaWAN adapters, deployment automation, integrations, Traccar, AddaxAI Connect, gateways, the MCP server for AI clients), live verification pending; phase 10 (backups and recovery, observability, System Health per area, trace retention) is built and exercised locally. Phases 0 to 6 are done: workspace, compose stack, CI, docs, schema and migrations, authentication and RBAC, trace contract, admin API, the Redis Streams event bus, adapters, drivers, the ingest and decoder services, Needs Attention, live map data, WebSocket updates, LoRaWAN traffic, trace search, system health, the React frontend, the Data Explorer and exports, rules, events, alerts, automations, notifications, and device control. Sections marked "planned" describe agreed design that is not implemented; they are rewritten as the code lands.

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
| Event bus and cache | Redis 7.4, Redis Streams with consumer groups | One broker; `RedisStreamsBus` in `shared/bus.py`, `Worker` base in `shared/worker.py` |
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
│   ├── api/                 # FastAPI service `protect_api`: auth/, routers/, schemas/, deps.py, alembic/, bootstrap.py
│   ├── ingest/              # `protect_ingest`: runs adapter event connectors (MQTT, polling, websocket)
│   ├── decoder/             # `protect_decoder`: source events to canonical rows
│   ├── export/              # `protect_export`: export jobs to MinIO
│   ├── rules/               # `protect_rules`: rule evaluation, scheduler, system checks
│   ├── automation/          # `protect_automation`: actions, notification delivery, Telegram poller
│   ├── integration/         # `protect_integration`: outbound deliveries, retry loop, backfill
│   ├── mcp/                 # `protect_mcp`: MCP server for AI clients, calls the API with the client's token
│   └── frontend/            # React + Vite + TypeScript, nginx Dockerfile, FRONTEND_CONVENTIONS.md
├── shared/shared/           # package `shared`: config, database, logger, version, enums, permissions,
│                            # models/, domain/assignments.py, trace.py, timeutil.py, secrets.py, bus.py,
│                            # worker.py, ingest.py, storage.py, connectivity/ (base, transports, adapters),
│                            # device_drivers/ (base, registry, generic_json, opencollar), analytics.py, exports/,
│                            # rules/ (schema, templates, evaluator, data, events, replay), notifications/,
│                            # control/ (actions, commands), oauth.py (scopes, access tokens)
├── ansible/                 # playbook, roles, *.example inventory and vars (phase 7)
├── tests/                   # tests/shared, tests/api, tests/fixtures/payloads
├── docs/                    # MkDocs site, docs/adr/ holds the ADRs
├── docker/python.Dockerfile # one image for every Python service; compose sets the command per service
├── docker/chirpstack/       # ChirpStack, gateway bridge and Mosquitto config for the compose profile
├── docker/postgres/         # pgBackRest config and the protect-pgbackrest wrapper
├── docker/backup/           # object mirror script, compose overrides of the restore-test stack
├── examples/                # adapter, driver and payload skeletons to copy from
├── scripts/dev.sh           # daily commands; backup.sh, restore.sh, restore-verify.sh, verify-server.sh for servers
├── .githooks/commit-msg     # strips assistant trailers (D28), installed with scripts/dev.sh hooks
├── .github/workflows/ci.yml
├── docker-compose.yml
├── pyproject.toml           # uv workspace root, ruff, mypy, pytest config
└── uv.lock
```

The rules behind it:

- `services/<name>/` is one Python package each (`protect_<name>`), all built into one image (`docker/python.Dockerfile`) and started with a different command per compose service. Services import from `shared` and never from each other.
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

### Event bus

`shared/bus.py`, Redis Streams (ADR 0004). Topics are `<object>.<verb>` in past tense, listed on `Topic`: `source_event.received`, `position.created`, `measurement.created`, `device.state_changed`, `event.created`, `alert.created`, `command.updated`, `delivery.updated`, `needs_attention.created`.

- Publish after the database commit, never before (`shared.ingest.commit_and_publish`, `protect_decoder.pipeline.publish_outcome`), so a consumer never reads a row that is not committed.
- Each worker is one consumer group (`Worker(name)` in `shared/worker.py`; `worker.subscribe(topic, handler)`). A handler acknowledges by returning. A handler that raises leaves the message pending; it is re-delivered after `BUS_RETRY_BASE_SECONDS` doubling per attempt, and dead-lettered to `<topic>.dead` after `BUS_MAX_ATTEMPTS`. An `ApplicationError` with `retryable=False` is dead-lettered at once. Pending messages of a crashed consumer are reclaimed by any consumer of the group.
- Messages carry `schema_version`; a newer version than the consumer knows is dead-lettered with `SCHEMA_VERSION_UNSUPPORTED`.
- Streams are trimmed to about `BUS_MAXLEN` entries (D33). Dead-letter streams are listed, retried and resolved through `/api/v1/attention/dead-letters`.
- Every worker stamps `heartbeat:<worker>` each loop; `HEARTBEAT_STALE_MINUTES` (15) without a stamp is stale. `/api/v1/attention/summary` reads it, and the rules service turns a stale worker into a system alert.
- Tests use Redis database 1, flushed per session; the development stack uses database 0.

### Ingestion

`shared/ingest.py` is the one inbound path: resolve the external identity (create it unknown if new), store the source event (payload inline up to `PAYLOAD_INLINE_MAX_BYTES`, else in the MinIO uploads bucket with key, size and SHA-256 on the row, D32), start a compact trace, and after the commit publish `source_event.received`, or `needs_attention.created` for an unknown or ignored identity. Two callers: `POST /api/v1/ingest/http/{data_source_id}` (bearer token per source, D34; token returned once at creation or by `POST /data-sources/{id}/webhook-token`) and the ingest service, which runs the event connectors of enabled data sources and re-reads the sources every minute.

### Decoding

`services/decoder/protect_decoder/pipeline.py`: driver from the device type, decode, canonical key per record, repeat deliveries link to the existing row in `source_deliveries`, attribution at the record's time, canonical rows and current state in one transaction, domain events after commit. Unknown metric keys are registered automatically in the metric registry with category `uncategorized`. See `docs/architecture/processing-pipeline.md`.

### Log files and browser syncs

`shared/logfiles.py` parses the one-frame-per-line format (base64 or hex), stores a file in the `device-log-files` bucket and its `device_log_files` row (SHA-256 unique per device, `DuplicateLogFile`), and builds the `log_file.uploaded` message. `services/decoder/protect_decoder/logfiles.py` is the file processing worker: it splits the file, stores every frame with `store_inbound` on the channel's built-in source (the device known up front) and decodes it with `process_source_event`, `LOG_FILE_BATCH_SIZE` frames per transaction, counting frames, malformed frames, records found, new and known (the pipeline's `Outcome` now carries the period, firmware and decoder version); a re-decode reprocesses the stored frames (`provider_metadata.log_file_id`). The API (`routers/log_files.py`) uploads, syncs (`ble-sync`, frames in hex), lists, downloads and re-decodes, and serves the driver's protocol catalogue for the settings editor. Decision D77, ADR 0017, `docs/devices/raw-log-files.md`.

### Adapters and drivers

Contracts in `shared/connectivity/base.py` and `shared/device_drivers/base.py`, registries in `registry.py` next to them (D10, ADR 0011). An adapter may declare `push` (a webhook token is minted for its sources), `acquisition_channel`, `command_connector`, `config_example`, `credentials_schema` and `setup_hint`; `describe_adapter` turns that into the `GET /data-sources/adapters` answer the frontend builds its form from. `tests/shared/test_provider_boundary.py` fails when a provider is named outside `shared/connectivity/adapters/` or anywhere in the frontend. Adapters today: generic HTTP, generic MQTT, ChirpStack (MQTT events, REST management and queue), KPN/ThingPark (HTTP push, downlink API), LORIOT (websocket output, `tx` downlinks), Netmore (export format over HTTP push or MQTT; downlinks through the LoRaWAN Portal or Connect API per the `platform` setting), akenza.io (webhook samples, akenza device id as identity, REST downlinks). Cloudloop (Iridium: Lingo webhook with `?token=` and an address allow-list, `Data/DoSendSbdMessage` commands, `Data/GetThings`). Two built-in channel adapters, `webble` and `log_file`, have no platform: their sources are created by migration 0011 with fixed ids (`builtin`, `SOURCE_ID` in the module), `shared/ingest.py` `builtin_source` and `ensure_channel_identity` find or recreate them and the device's identity on them (its own id); `webble` declares `requires_client` and a command connector that only queues (the browser executes). Adapters produce `InboundMessage` (with gateway receptions and identity attributes for links, and `device_id` when the caller already knows the device, as browser syncs and uploads do) and never decode payloads; drivers produce `DecodedRecords` and never read provider fields. For LoRaWAN uplinks the decoder extracts the application frame (`frame` bytes and `f_port`) from the stored event and drivers work on that; on the `webble`, `log_file` and `iridium` channels the frame is the raw delivery (`data_hex`, `raw_frame` in `device_drivers/base.py`) and `SourceEventData.acquisition_channel` tells the driver how to read it (the OpenCollar driver: port byte in front over BLE and in files, a stored-record stream over Iridium); network-level events (`join`, `status`, `downlink_ack`, `downlink_transmitted`, `log`) need no driver: `status` yields `battery_level` and `link_margin` measurements, the rest update connectivity state. A driver declares `decodable_event_types` (default `uplink`). Skeletons to copy are in `examples/`. Documentation: `docs/integrations/adapter-interface.md`, `docs/devices/driver-interface.md`, `docs/integrations/chirpstack/`.

### ChirpStack locally

`docker compose --profile chirpstack up -d` starts ChirpStack 4.19, its gateway bridge, Mosquitto, Postgres and Redis and the REST API. `scripts/dev.sh chirpstack-bootstrap --protect-email ... --protect-password ...` mints an API key (a row in ChirpStack's `api_key` table plus a JWT signed with `CHIRPSTACK_API_SECRET`), creates tenant, application, device profile, simulated gateway and device, and registers the data source in Protect. `scripts/dev.sh simulate --application-id <id>` publishes uplinks as ChirpStack integration events on the broker. The gateway bridge config has the broker host written literally because the bridge does not expand environment variables.

### Live map, traffic, traces, health

- `GET /projects/{id}/map/current` returns entity current state as GeoJSON within a viewport and limit and says whether the client should switch to tiles (`use_tiles` above 2,000 entities); `GET /projects/{id}/map/tiles/{z}/{x}/{y}.mvt` serves the same as Mapbox vector tiles from `ST_AsMVT` (layer `entities`).
- `GET /projects/{id}/tracks?entity_id|device_id&from&to&max_points` returns a LineString with one time per vertex, decimated with a uniform step so at most `max_points` come back; `total_points` and `step` tell the client how much was skipped.
- `GET /projects/{id}/traffic` lists source events of the project's devices with port, frame counter, spreading factor, best RSSI and SNR, gateway receptions and processing status; `include_payload=true` adds the raw payload.
- `GET /projects/{id}/traces` searches traces by device, DevEUI, data source, status, error code and time; `GET /traces/{id}` has the steps.
- `GET /system/health` (server admin) reports workers with heartbeat, lag and dead letters, events per minute, failures, unknown identities and per data source counts.
- `WS /api/v1/ws/projects/{id}?token=...` streams `position.created`, `device.state_changed`, `event.created` and `alert.created` for the project. One reader per API process tails the streams with `XREAD` and fans out; there is no consumer group, so every API instance sees every message (`protect_api/realtime.py`).

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
scripts/dev.sh up                         # docker compose up -d --build: postgres, redis, minio, migrate, api, ingest, decoder, export, frontend
scripts/dev.sh bootstrap-admin you@example.org   # invitation link for the first server admin (once)
docker compose --profile chirpstack up -d # adds a local ChirpStack (web UI and gRPC on :8080, MQTT on :1883)
uv sync --all-groups                      # python environment for tests, linters and docs
cd services/frontend && npm ci            # frontend dependencies
```

Daily commands through `scripts/dev.sh`: `up`, `down`, `logs [service]`, `migrate`, `revision`, `bootstrap-admin`, `test`, `lint`, `format`, `docs`, `hooks`. `sweep` arrives in phase 3.

Ports (all bound to localhost except the frontend): API 8000, MCP 8001, frontend 3000, Postgres 5432, Redis 6379, MinIO 9000 and console 9001. `/api/docs` is the OpenAPI UI, `/api/health` reports database, Redis and MinIO, `/api/version` reports the version and commit.

The frontend dev server (`npm run dev` in `services/frontend`) runs on :5173 and proxies `/api` and `/ws` to `VITE_PROXY_TARGET` from the root `.env`. The frontend reads the root `.env`, there is no second env file.

### Python workspace

One `uv` workspace: `shared/` and `services/*` (the frontend is excluded). Every `pyproject.toml` pins exact versions; `uv.lock` is committed and CI installs with `--frozen`. Add a dependency with `uv add --package smartparks-protect-shared <name>`, then pin it to the resolved version.

`shared/shared/` today: `config.py` (pydantic-settings, `get_settings()` cached, raises on missing values), `database.py` (one async engine per process, `get_session` dependency, `session_scope` for workers), `logger.py` (JSON or text, `request_id` and `trace_id` context variables, `get_logger(name).info("msg", key=value)`), `version.py` (reads `VERSION`, falls back to `v0.0.0-dev`).

`services/api/protect_api/`: `main.py` builds the app, `middleware.py` sets the request id (inbound `X-Request-ID` is kept), `health.py` runs the three dependency checks concurrently with a 3 second timeout each and answers 503 when one fails.

### Frontend

WebBLE (`src/lib/opencollar-ble.ts`, decision D76) implements the OpenCollar BLE protocol over an injected transport so `opencollar-ble.test.ts` runs without hardware; `stores/webble.ts` keeps one session per device in the tab, `hooks/useWebBle.ts` syncs received frames to `POST /devices/{id}/log-files/ble-sync`, `components/devices/WebBleCard.tsx` is the card and `DeviceControl` executes commands whose route is the browser. Web Bluetooth needs Chrome or Edge over HTTPS; the DOM lib does not type it, so the subset used is declared structurally in the protocol module.

`npm run build` is `tsc -b && vite build`: a type error fails the build and the Docker image. `npm run lint` is ESLint, `npm run test` is Vitest with Testing Library, `npm run sweep` is the screenshot sweep (see below). shadcn/ui components are added with `npx shadcn@latest add <name>` and land in `src/components/ui/`, which ESLint ignores. Brand colours and semantic tokens are CSS variables in `src/index.css`; the logo SVGs in `src/assets/brand/` use `currentColor` and are imported as React components. Rules are in `services/frontend/FRONTEND_CONVENTIONS.md`.

How the app is put together:

- `src/api/client.ts`: the one fetch wrapper. Attaches the bearer token, turns errors into `ApiError`, calls `useAuthStore.expire()` on a 401 so the router shows the login page with a return path. No `window.location` anywhere.
- `src/api/schema.d.ts` is generated from the API's OpenAPI document with `scripts/dev.sh openapi` (also `npm run generate:api` after the JSON is dumped); `src/api/types.ts` aliases the schemas the pages use. CI fails when the committed schema is stale.
- `src/api/queryKeys.ts` is the only place query keys are defined; `useMutationToast` invalidates by these keys and toasts the outcome.
- Stores: `useAuthStore` (token persisted in localStorage, user, status), `useProjectStore` (last opened project). Filters and selection live in the URL.
- Routing in `src/App.tsx`: `/projects/:projectId/...` behind `RequireAuth`, `/admin/...` behind `RequireServerAdmin`; pages are lazy loaded. Sidebar sections in `src/components/layout/navigation.ts`, items without a route show the phase they arrive in.
- Icons: `src/assets/icons/icon-registry.json` maps stable keys (`wildlife.rhino`) to SVGs with fallback chains and licence data (`src/components/icons/registry.ts`); `Icon` renders inline, `markers.ts` renders marker images for MapLibre with the family shape (round entity, square infrastructure, diamond event) and a state colour.
- Map: `useMap` creates one MapLibre map with OpenFreeMap styles (D37) and sends the bearer token on requests to our own origin; `layers.ts` owns the entity, track and feature sources. Live updates come from `useProjectStream` over the WebSocket and patch the current-state query cache.

Screenshot sweep: `npm run sweep` (Playwright, routes derived from `src/App.tsx`) logs in with `SWEEP_EMAIL` and `SWEEP_PASSWORD`, opens every route at 390, 768 and 1440 px, flags console errors and horizontal overflow and writes `ui-sweep-output/`. Chromium needs a few system libraries (`libnspr4 libnss3 libasound2t64` on Ubuntu 24.04); without them run the sweep in the Playwright image from `services/frontend`: `docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD:/work" -w /work -e SWEEP_EMAIL=... -e SWEEP_PASSWORD=... mcr.microsoft.com/playwright:v1.58.0-noble node scripts/ui-sweep.mjs`. The `--user` flag keeps the output owned by you.

## Rules, events, alerts

`shared/rules/schema.py` is the rule document (decision D9, ADR 0012): Pydantic models, `RuleDocument.reserved_types()` says what the evaluator cannot run, `json_schema()` feeds the frontend builder. `shared/rules/evaluator.py` is the stateful evaluator: `evaluate(doc, subject, sample, state, data)` returns a `Verdict`; it is pure apart from the `DataAccess` protocol, implemented for SQL in `shared/rules/data.py` (live mode reads the current-state tables, historical mode derives everything from rows before the sample time). Firing is edge-triggered with an optional cooldown reminder; `SubjectState` (active, holding since, last fired, inside geofences) is stored per rule and subject in `rule_state`. `shared/rules/events.py` creates events and alerts the same way for rules, system checks and later the API (`create_event`, `close_alert`, `event_messages`); `shared/rules/replay.py` replays canonical rows through the evaluator with in-memory state, bounded.

`services/rules/protect_rules/engine.py`: `RuleCache` re-reads enabled rules every `RULES_RELOAD_SECONDS`; `handle_position`, `handle_measurements` and `handle_state` build a `Sample` and run every rule in scope, each in its own transaction (`run_rules`), so one broken rule lands on `rules.last_error` plus a failed trace and the others continue. A rule that fires writes a compact trace (rule matched, conditions evaluated, event created) and publishes `event.created` and `alert.created` after the commit; silent evaluations write nothing. `Scheduler.tick()` runs schedule rules over the entities of the project (at most 5,000) every `every_seconds`. `system_checks.py` opens one system alert per stale worker, dead-letter stream and lagging consumer group and resolves it when the finding clears; system events have `project_id` null and are visible to server admins only.

Events and alerts API: `routers/events.py` (project lists newest first with the time of the last item as cursor, detail with deliveries, `map/events` GeoJSON for the last hours, acknowledge and resolve under `alerts:write`, which viewers hold) and the `/admin` variants for system events. Rules API: `routers/rules.py` (templates, schema, versions as immutable rows, `PUT /document` makes a new version, `POST /{id}/test` and `POST /test-document` replay).

## Automations and notifications

`services/automation/protect_automation/actions.py`: `handle_event` loads the matching automations of the event's scope, and for every action gets or creates the `ActionDelivery` row keyed on (event, automation, action index), so a re-delivered bus message runs only the actions that have not succeeded. Stale events (older than `max_event_age_seconds`) are recorded as skipped. `Skipped`, `PermanentFailure` and `TransientFailure` from `shared/notifications/dispatch.py` decide the delivery status; a transient failure makes the handler raise a retryable `ApplicationError` after the commit, so the bus re-delivers with backoff. Webhooks are signed with `X-Protect-Signature: sha256=<hmac>` when the action has a secret. `telegram_poller.py` long-polls the bot (offset in Redis `telegram:update_offset`) and links `/start <code>` messages to targets.

`shared/notifications/`: `render.py` (Jinja templates for event and test messages, the link back), `email.py` (SMTP with the development guard: non-production servers mail only `DEV_NOTIFY_EMAILS`, everything else is logged and the delivery is skipped), `telegram.py` (Bot API over httpx), `dispatch.py` (`deliver_to_target`, shared by the automation service and the API test send). The API mailer for invitations and password resets uses the same sender.

Targets, automations and deliveries API: `routers/automations.py`, one implementation for the project scope and the `/admin` scope (project null). `automations:write` is project admin only.

## Device control

`shared/control/actions.py` is the action contract (ADR 0013): a driver declares `control_actions`, each a `ControlAction` with a Pydantic parameter model, permission, confirmation policy, required capability, `encode` and optional `interpret`. `shared/control/commands.py` is the one command path: `request_command` creates the row, encodes, selects the route (`select_route`: an enabled data source holding an identity of the device whose adapter has a `command_connector` and the capability; most recently seen identity first; a `route_source_id` pins the route and adapters with `requires_client`, the browser, are skipped unless pinned, decision D79; `candidate_routes` lists every option for the control dialog), submits through the connector (the options carry the identity type and attributes, which Cloudloop needs for the thing id) and records every stage as a `CommandExecution`; `apply_provider_signal` (called by the decoder for `downlink_transmitted`, `downlink_ack` and `log` events, matched on `provider_ref`) and `interpret_device_records` (called by the decoder after decoding an uplink of a device with pending commands) move the lifecycle; `expire_commands` runs in the rules service ticker. Statuses only move forward (`RANK`); final states are `confirmed_by_device`, `failed`, `expired`. A refused submission is a failed command with the reason, not an exception to the caller.

The ChirpStack connector (`ChirpStackCommands`) posts to `/api/devices/{dev_eui}/queue` and returns the queue item id as `provider_ref` with statuses `accepted_by_network` and `queued`; `queue` and `flush` read and clear the platform queue. Adapters without a `command_connector` method cannot send commands, which the actions endpoint reports as the reason.

API in `routers/control.py`: permissions are judged in the device's current project (`_control_permissions`), confirmation policies other than `none` need `confirmed: true`, everything is audited. `GET /devices/{id}/routes` lists the routes, `POST /devices/{id}/routes/webble` registers the browser (the device's identity on the built-in WebBLE source), `CommandCreate.route_data_source_id` pins one, and `POST /commands/{id}/browser-result` is how the browser reports that it wrote (or could not write) a WebBLE command; the device's answer comes through the synced frames and `interpret_device_records`, as for any uplink. The automation action `command` calls `request_command` with the automation as actor and publishes `command.updated` after the commit.

## Integrations

`shared/integrations/base.py` is the outbound connector contract: `render(integration, item)` (pure) and `deliver(integration, item, payload)`, plus `test`. `DeliveryItem` is the canonical object with the names around it; `load_item` in `shared/integrations/deliveries.py` builds it from a delivery row (position, event or measurement, entity and type, device, project, data source, the event's link, and for an event without a point the entity's latest position as a fallback). Connectors live in `shared/integrations/connectors/` (`gundi` and `earthranger` for EarthRanger, `wildlifenl`, `ferustracker`, `webhook`, `mqtt`) and are registered in `shared/integrations/registry.py`; `describe_connector` feeds the frontend so it names no provider. `TransientFailure`, `PermanentFailure` and `Skipped` come from `shared/notifications/dispatch.py`.

`deliveries.py` is the mechanism (ADR 0014): `matches` applies the integration's filters to an `ObjectRef`; `enqueue` inserts queued rows with `ON CONFLICT DO NOTHING` on (integration, object type, object id, object version), records stale events as skipped and drops stale positions; `attempt` runs one try, sets the next attempt from `backoff_seconds` (30 s doubling to 6 h, `MAX_ATTEMPTS` 30) or the final status, keeps a compact trace per delivery and the integration's `last_delivery_at` and `last_error`; `backfill` walks a date range per object type in batches and commits progress on `integration.backfill`; `requeue` is the manual retry.

`services/integration/protect_integration/worker.py`: `handle_message` turns `position.created` (payload only), `event.created` and `measurement.created` (rows loaded) into refs and enqueues them for the project's enabled integrations (`IntegrationCache`, re-read every 30 s), then the bus message is acknowledged. `delivery_loop` calls `deliver_due` every two seconds: due rows in order, one integration's share of a cycle ends at its first transient failure, disabled integrations get their rows skipped. `handle_backfill` runs the backfill for `integration.backfill_requested`. The API (`routers/integrations.py`) only writes rows, publishes the backfill request and runs test sends inline.

## AI clients (MCP)

Architecture 27, ADR 0015. `services/mcp/protect_mcp` is a streamable HTTP MCP server built with the official SDK (`MCPServer`), stateless, at `/mcp` on port 8001 (`protect-mcp`). It never opens the database: every tool calls the API through `protect_mcp/api.py` with the client's own bearer and names the tool in `X-Protect-MCP-Tool`. `server.py` holds the tools (bounded reads: projects, entities, devices, positions, aggregated measurements, events, traces, plus the `search` and `fetch` pair ChatGPT expects), the `smartparks://` resource templates and the two prompts. `auth.py` verifies access tokens locally (`shared/oauth.py`). The protected resource metadata is served at both RFC 9728 paths; a request without a valid token gets 401 with `resource_metadata` in `WWW-Authenticate`, one without every read scope gets 403 with `insufficient_scope`.

The API is the OAuth 2.1 authorization server (`protect_api/oauth/`): `routes.py` mounts the SDK's authorize, token, registration and revocation handlers under `/api/v1/oauth` and serves `/.well-known/oauth-authorization-server`; `provider.py` implements the SDK's provider protocol on `oauth_clients`, `oauth_authorization_codes` and `oauth_refresh_tokens` (migration 0009): clients by client id metadata document (fetched from the client id URL, validated, cached an hour) or dynamic registration, consent requests that `/oauth/consent` in the frontend approves or denies (`POST /oauth/consent/{id}/approve|deny` return the redirect), JWT access tokens (`shared.oauth.mint_access_token`: audience the MCP URL, subject the user, `client_id` and `scope` claims, one hour), refresh tokens hashed and rotated. `scopes.py` is the AI action policy: `GET` only, one scope per path family, everything else refused. `middleware.py` admits an MCP token only through that policy, stores it in `mcp_access_var`, and writes an `mcp.request` audit row (user, client, tool, path, status) per request; the JWT strategy in `auth/users.py` accepts the MCP audience only when the middleware admitted the request. `GET /oauth/connections` and `POST /oauth/connections/revoke` back the Connected AI clients page.

Locally: `docker compose up -d` starts `protect-mcp`; the MCP inspector connects to `http://localhost:8001/mcp` (add `http://localhost:6274` to `CORS_ORIGINS`), Claude Code with `claude mcp add --transport http protect http://localhost:8001/mcp`. `tests/mcp` drives the MCP ASGI app with the API app in process over `httpx.ASGITransport`. User documentation: `docs/mcp/`.

## Gateways

`shared/models/network.py`: `Gateway` (server level, unique on data source and provider id) and `DataSourceCursor`. `shared/ingest.py` keeps the registry: `upsert_gateways` for every reception (online, last seen, a location from the reception's `location` attribute) and `apply_gateway_update` for `GatewayUpdate` messages (`InboundMessage.gateway`, `external_id` None): stored as a source event without a device, `processing_status` processed, no bus message. The ChirpStack adapter parses `gateway/+/event/stats` and `gateway/+/state/conn` and its management connector's `list_gateway_updates` backs `POST /data-sources/{id}/sync-gateways`. `routers/gateways.py` aggregates `gateway_receptions` per project window: gateways busiest first, gateway detail with the devices heard, and `connectivity` per device (gateways heard, best gateway and its share of uplinks, mean signal).

## Application platforms

Platforms whose data arrives decoded (Traccar positions, AddaxAI Connect detections) deliver the generic JSON shape (`time`, `lat`, `lon`, `speed` in m/s, `measurements`, `state`, `events` with optional `lat`, `lon`, `description`) with the original record under `raw`, and their devices use the Generic JSON driver, whose `decodable_event_types` include `position`, `event`, `state` and `detection`. That keeps adapters ignorant of devices and drivers ignorant of networks. The driver also declares `PLATFORM_COMMAND` (`type` plus `attributes` encoded as JSON), which a command connector such as Traccar's maps to the platform's command API.

Polling connectors keep their position in `data_source_cursors` through `DataSourceContext.cursors` (`DatabaseCursorStore` in production, `MemoryCursorStore` in tests). `POST /data-sources/{id}/cursor` writes `{"since": ...}`, which the connector honours at its next poll and then replaces with its own state. The AddaxAI Connect connector pages `GET /api/images` newest first from `captured_after`, rescans an overlap window daily, and logs in again on 401 (the JWT lives an hour).

## Backups and recovery

Architecture 28, decisions D72 to D75, `docs/operations/backup-and-recovery.md` and `restore-guide.md`. pgBackRest runs inside the database container (the TimescaleDB image ships it): `docker/postgres/pgbackrest.conf` holds the stanza and the container paths, everything per deployment arrives as `PGBACKREST_*` environment variables from compose (`BACKUP_*` in `.env`). `docker/postgres/pgbackrest-wrapper.sh` is mounted as `protect-pgbackrest` and is the only way pgBackRest is called: it drops an archive-push while `BACKUP_ENABLED` is false, removes options compose had to leave empty and S3 options for a non-S3 repository (pgBackRest refuses both), creates the log and spool directories in the `pgbackrest-state` volume, and is the `cmd` pgBackRest writes into a restored cluster's `restore_command`. PostgreSQL always runs with `archive_mode=on` and `archive_timeout=900`; the wrapper decides whether a segment goes anywhere.

`scripts/backup.sh database full|incr`, `objects` (the `object-mirror` compose service in the backup profile: `mc mirror` of every bucket to the backup bucket, never deleting on the remote, `MIRROR_DIRECTION=restore` for the way back) and `check` record every run through `python -m protect_api.backup record` (`backup_runs`, migration 0010; a pgBackRest info document on stdin is summarised) or `integrity` (the newest 500 referenced objects per store against the backup bucket with the MinIO client). `scripts/restore-verify.sh` restores the newest backup into a second compose project (`docker/backup/verify.yml`: own network, container names and volumes, no ports, archiving off, a local repository read from the production state volume), replays WAL, migrates, starts the API, checks health, row counts and object references, records a `restore_test` run and removes the project. `scripts/restore.sh` is the clean-server recovery. `shared/backup.py` assesses the state (runs plus `pg_stat_archiver`) for the Backup and recovery page (`routers/backups.py`) and for the `SYSTEM_BACKUP` findings of the rules service's system checks. Ansible installs the schedule as cron jobs when `backup_enabled` is set.

## Observability

Architecture 26.8, `docs/operations/observability.md`. `shared/telemetry.py` installs the OpenTelemetry SDK when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (`configure_telemetry(service)` in `Worker.__init__`, the API and the MCP app): OTLP/HTTP exporters, SQLAlchemy, httpx and redis instrumentation, FastAPI in the API. `RedisStreamsBus._handle` wraps every message in a span with `protect.trace_id` and records `protect.bus.messages` and `protect.bus.handler.duration`; `Tracer.start` puts the processing trace id on the current span. The compose profile `observability` runs `grafana/otel-lgtm`. `protect_api/health_areas.py` computes the per-area System Health (architecture 26.2) that `GET /system/health` returns as `areas`; `protect_rules/retention.py` applies the per-class trace retention daily from the rules ticker.

## Deployment

`ansible/playbook.yml` with the roles security, docker, nginx, ssl, dev-tools, app-deploy and security-check, mirrored from AddaxAI Connect without FTPS and GPU: firewall with SSH, HTTP and HTTPS only; sshd hardening in a `01-` drop-in read back with `sshd -T`; security updates with a reboot at 04:30 only when required; fail2ban on sshd; nginx in front of the frontend container and the API with rate limits, websocket upgrade for `/api/v1/ws/` and a generous limit on `/api/v1/ingest/`; certbot without an interactive pause (the playbook refuses when the domain does not resolve to the host); checkout of the newest `vX.Y.Z` tag unless `git_version` is set; `.env` written from host vars; `docker compose up` with the migrate service; a daily cron for `scripts/security-status.sh`. `scripts/verify-server.sh` is the read-only gate after an update: containers versus `docker compose config --services`, Alembic head, health and version, worker heartbeats from Redis, error lines in the logs. Only the `*.example` files are committed; a private repository holds the filled-in inventory and the vault-encrypted host vars.

## Platform expansion (phase 13)

`shared/connectivity/adapters/tts/` is The Things Stack: `parse_message` maps the webhook documents (`uplink_message`, `join_accept`, the downlink events, `location_solved`) to inbound messages with gateway receptions, `TtsCommands` pushes to the application's downlink queue with a `smartparks-protect:<command id>` correlation id that the downlink events echo as `queue_ref` in the provider metadata (`apply_provider_signal` now also matches on that), `TtsManagement` lists devices and gateways with connection stats. `actility_thingpark/` subclasses the KPN adapter. `cra_iot/` (D90) is České Radiokomunikace: `parse_webhook` unwraps the `{type, data, tech, tags}` envelope and `parse_message` reads the LORIOT-shaped message (`gw` as the uplink by default, `rx` ignored, `geo` as a location), `CraClient` takes a token from the CRA single sign-on with the password grant and caches it, `CraCommands` posts to `/lora/devices/{EUI}/down/messages`, `CraManagement` pages through `/lora/devices`. `shared/integrations/connectors/earthranger.py` is the direct EarthRanger connector; `DeliveryItem.previous_external_id` (set by `load_item` from the last sent delivery of a lower object version) lets a connector update instead of duplicate. `connectors/wildlifenl.py` is the WildlifeNL connector (D88): readings and detections from the platform's open source API, species resolved by name against a cached `GET /species/`, one detection per species; `DeliveryItem.device_identity` (the device's most recently seen, not ignored external identity, loaded by `load_item`) is its default sensor id. `connectors/ferustracker.py` (D89) renders the document the Node-RED flow posts to ferustracker.nl (`devEUI`, `fPort`, `tags.payloadType`, `objectJSON` with the decoder's field names per payload family, `provider`, `site`) from positions and measurements; `DeliveryItem.device_type_key` selects the payload type. Movebank is two export datasets in `shared/exports/datasets.py` (`movebank_events`, `movebank_reference`). `shared/models/platform.py` holds `server_settings`, `mcp_pending_actions`, `project_icons` and `dashboards` (migration 0013). `routers/platform.py`: the manual event endpoint (`create_manual_event`, used by people and by the AI action endpoint), SVG icon validation (`validate_svg`) and dashboards; `routers/mcp_actions.py`: the AI action policy (`ACTIONS`, `DEFAULT_POLICY`, `load_policy`), `POST /mcp/actions` and `.../confirm` (ADR 0019). `protect_api/oauth/scopes.py` allows MCP tokens those paths and nothing else that writes; `shared/oauth.py` defines the write scopes. The MCP server's write tools call `ProtectApi.post` and check the token's scope before asking the API. Frontend: `stores/icons.ts` (loaded by the layout, read by `Icon`), `pages/project/DashboardsPage.tsx` with `components/dashboards/tiles.tsx`, `pages/admin/AiPolicyPage.tsx`.

## Production hardening (phase 14)

Data sources are their channels: adapters declare `channels` (or `channels_of` in `shared/connectivity/registry.py` derives them from the adapter's flags); `GET /data-sources/{id}/status` combines configuration presence, the last 24 hours of source events per ingestion method, the connector state the transports write to Redis through `shared/connectivity/state.py` (`report_connector`, read by the API) and the last Test connection outcome (`report_api_test`), and holds back capabilities of unconfigured channels. The ChirpStack adapter talks to the platform over gRPC only (`grpc_api.py`, the `chirpstack-api` package; `api_url` is `grpcs://` or `grpc://`). `routers/admin_traffic.py` is the server-wide traffic page's API (inbound across sources through `traffic_rows` from `routers/network.py`, outbound deliveries and commands with project and integration names, the hourly summary); the frontend page is `pages/admin/AdminTrafficPage.tsx` with three tabs. `shared/exports/cleanup.py` (`expire_exports`) is the retention sweep the export service runs hourly through `Worker.background`; migration 0014 adds the `expired` status.

Security (D94): `protect_api/ratelimit.py` is an ASGI middleware over `shared/ratelimit.py` (Redis fixed windows; `RATE_LIMIT_*` settings; the test suite raises the limits in `tests/conftest.py`); `tests/api/test_access_matrix.py` walks every OpenAPI operation with an anonymous caller, a viewer of another project, a viewer of the own project and an AI client with read scopes, so a new endpoint without its dependency fails CI; a viewer write that is allowed by design goes into `VIEWER_WRITES_ALLOWED` there. Permissions belong in route dependencies (`require_permission`), never inside the handler after the body is parsed. CI runs `pip-audit` over the exported lock and `npm audit` (job `audit`, also weekly). Docs (28.8): `scripts/docs_check.py` checks internal links and anchors in the built site, Mermaid fences and the MCP tool reference; the docs CI job runs it after the strict build. Organizations (D92): `admin.py` CRUD under `/admin/organizations`, `Project.organization_id` (server admins only in `update_project`), `?organization_id=` on the project list. Translation (D93): `src/i18n.ts` initialises i18next with the English catalogue `src/locales/en/translation.json`; every string a person reads goes through `t()` from `useTranslation()` in components and hooks or `i18n.t()` at module level, with the English text as the key; ESLint's `i18next/no-literal-string` refuses JSX text and the listed attributes; `npm run i18n:extract` regenerates the catalogue and `npm run i18n:check` fails when it is stale (CI); a language is added by dropping its catalogue in `src/locales/<code>/` and listing it in `LANGUAGES`. Benchmark (D91): `generate.py` writes in time blocks (`--block-days`) with a barrier between workers, and `--compress` compresses chunks behind the write frontier; inside a container run it as `/app/.venv/bin/python`. Release process: `docs/operations/release-process.md`.

## Data curation

`shared/curation/effective.py` defines the effective value (ADR 0018, decision D80): `effective_time`, `effective_geom`, `effective_number` and `effective_value_num` (coalesce of the `curated_*` overlay column and the original), `in_window` and `before` (time predicates written as a disjunction so uncurated rows use the ordinary time indexes with chunk exclusion and curated rows the partial index on `curated_time`), and `visible` (`valid`). Every reader of positions and measurements goes through these: the map track, the positions list, `shared/analytics.py`, the analytics rows and metrics, `shared/rules/data.py` and `replay.py`, `shared/exports/datasets.py` (with `view=original` reading the original columns) and `shared/integrations/deliveries.py` (`load_item`, `curated_ref`). New readers must too.

`shared/curation/apply.py`: `CURATABLE` (position: time, coordinates, valid; measurement: time, value, valid), `normalize_value`, `apply_correction` (writes the overlay, supersedes an active correction on the field, reruns the attribution on a time change, bumps `curation_version`, flags sent deliveries stale), `revert_correction` (restores the value before, refuses while a newer correction is active, brings a superseded one back) and `recompute_current_state`. `shared/curation/jobs.py`: `Transformation` (time offset, validity, value offset or scale), `preview` (count, samples, impact on attribution, deliveries and rules over the first 5,000 rows), `apply_job` and `revert_job` (batches of 500 rows in their own transactions, progress on the job row, a replay report on request) and `run_job`, the handler of `curation.job_requested` in the export service. The API is `routers/curation.py` (project setting `curation_requires_approval`, decision D81; the proposer never approves their own); stale deliveries are listed with `?stale=true` and resent with `POST /integrations/deliveries/{id}/resend`, which enqueues the object's current `curation_version` as a new idempotency key. Migration 0012. Docs: `docs/analytics/curation.md`.

## Analytics and exports

`shared/analytics.py` holds the aggregation statement the API and the export worker share: the bucket ladder and the automatic resolution (decision D41), the bound of 5,000 points per series and 20 series per request, and `aggregate_statement` built on `time_bucket`, `first` and `last`. The router is `protect_api/routers/analytics.py` (series, drill-down rows, metrics with data, saved views).

`shared/exports/` is the export engine: `ExportParameters` (what a job stores), `datasets.py` (one streamed query per dataset, rows as dicts, `yield_per` server-side cursor), `writers.py` (CSV, XLSX in write-only mode with sheet splitting, JSON, GeoJSON, GPX; rows in, bytes out) and `runner.py` (a job to a temporary file to MinIO, or a direct stream bounded at 100,000 rows). Progress writes go through a separate session, because a commit on the streaming session closes the cursor. The export service (`services/export`) consumes `export.requested`. Docs: `docs/analytics/`.

## Benchmark

`scripts/benchmark/generate.py --scale 0.01` loads a synthetic dataset at a fraction of the reference envelope (architecture 13.9) with COPY: eight benchmark projects, devices walking around a home range, four measurements per position. `scripts/benchmark/run.py --email ... --password ... --manifest ...` times the map, tiles, tracks, Data Explorer, exports and an ingest burst against the running stack and writes `docs/operations/benchmarks.md`. `generate.py --reset` removes the dataset. See `docs/architecture/scalability.md` for the reading of the results.

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

`tests/conftest.py` sets default environment values that match `.env.example`, so tests run against the local compose stack without extra setup. CI runs one job per package (`tests/shared`, `tests/api`, `tests/decoder`, `tests/export`, `tests/rules`, `tests/automation`, `tests/integration`, `tests/mcp`) against Postgres/Timescale and Redis service containers and a MinIO container. A test that reads rows a worker committed in another session must end its own transaction first (`await db.rollback()`): the test session's snapshot predates the commit otherwise.

All tests share one event loop (`asyncio_default_test_loop_scope = session`) because asyncpg connections cannot move between loops. `tests/api/conftest.py` has helpers for actors per role (`actor`, `project_actor`), committed fixture rows and invitations. `tests/api/test_phase1_scenario.py` runs the phase 1 exit criteria end to end.

- Drivers, adapters and rules are tested with recorded fixtures under `tests/fixtures/payloads/`. Add the source of every fixture in a `README.md` next to it.
- API tests use a real Postgres/Timescale container. No mocked SQL.
- Playwright smoke opens every page at 390, 768 and 1440 px.
- Benchmarks (`scripts/benchmark/`) run on demand, not in CI. Results go to `docs/operations/benchmarks.md`.

## Releases

`VERSION` is written and committed before each tag (it does not exist before v0.1.0; the code reports `v0.0.0-dev`). `CHANGELOG.md` has an Unreleased section that becomes the release notes. Servers run tags, never `main`, except a dev server.

## Logging

All services write one JSON object per line to stdout (`LOG_FORMAT=json`, the container default) with `service`, `trace_id` and `request_id` where set; `LOG_FORMAT=text` gives readable lines for development. `docker compose logs -f <service>` follows a service. Uvicorn's own access log is not yet routed through the structured logger.
