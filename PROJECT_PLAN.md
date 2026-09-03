# Smart Parks Protect project plan

Living plan for building Smart Parks Protect from the concept architecture (`Smart_Parks_Protect_Concept_Architecture.md`, draft v16, 23 August 2026). This document guides and tracks the work from the first commit until the project is complete. It is the first thing to read in every coding session and the last thing to update before the session ends. Claude and Codex sessions both work from this one file. It merges the two plans written on 2026-09-03 (`PROJECT_PLAN_CLAUDE.md` and `PROJECT_PLAN_CODEX.md`, both removed after the merge).

## How to use this document

1. **Start of a session.** Read "Current status" and the active phase. Pick the next unchecked item in order, unless the last session log entry says otherwise.
2. **During work.** Tick `[x]` only when the item is done and verified: code works, tests pass, docs are updated. Tick the box in the same commit as the code. An item that is started but not finished gets a short note in brackets after it, for example `(in progress, migration written, tests missing)`.
3. **End of a session.** Add an entry to the session log at the bottom: date, what was done, decisions taken, what is next, blockers. Update "Current status".
4. **Changing the plan.** The plan may change. Record why in the session log. If a decision from the decisions table changes, update the table and write or amend the ADR.
5. **Definition of done** below applies to every item, not only to phases.
6. `DEVELOPERS.md` describes how the code works today. This plan describes where it is going. Keep both current.
7. Session log entries name the agent that did the work (Claude or Codex) so either can pick up where the other stopped.

## Current status

| Field | Value |
| --- | --- |
| Active phase | Phase 4, analyze, export and the scale benchmark |
| Latest release | v0.1.0 (2026-09-03); the tagged commit misses `DataTable.tsx`, fix is on main, see the phase 3 log |
| Last session | 2026-09-03 |
| Next item | Phase 4: quick start on a clean checkout, then the aggregation API |
| Blockers | none |

## What we are building

Smart Parks Protect is a self-hosted operational data platform for Smart Parks deployments. It ingests data from heterogeneous devices and IoT platforms (OpenCollar over LoRaWAN first, then Traccar, satellite, MQTT, HTTP, camera detections from AddaxAI Connect), normalizes it into one Smart Parks domain (Entities, Devices, Positions, Measurements, Events), and makes that data useful through a live map, a Data Explorer with server-side aggregation, exports, a stateful rules and automation engine, bidirectional device control, and durable outbound integrations such as EarthRanger.

The central architectural value is separation of concerns:

- **Connectivity adapters** understand external platforms (ChirpStack, KPN, LORIOT, Traccar, Cloudloop) and nothing about devices.
- **Device drivers** understand device protocols and control actions (OpenCollar) and nothing about networks.
- **The normalized domain** understands Smart Parks entities and data and nothing about either.
- **Rules, analytics, integrations and control** operate on the normalized domain only.
- **Every record stays traceable** to its SourceEvent, DataSource and external identity, and time-bounded assignments keep Entity history correct when hardware is replaced.

AddaxAI Connect is the reference for patterns (multi-service Docker, FastAPI, React, projects with RBAC, Ansible deployment, notifications), but this project is written from scratch. See decision D1.

## Decisions

Answers to the 24 setup questions from 2026-09-03. Each decision gets an ADR in `docs/adr/` when the related phase starts.

| # | Decision | Choice | Reason |
| --- | --- | --- | --- |
| D1 | Code reuse from AddaxAI Connect | Start from scratch, reuse patterns only, after a reuse audit | Clean codebase without camera and AI coupling. AddaxAI Connect stays the reference for auth, RBAC, deployment, notification and frontend patterns. Copying single files is allowed when a pattern is worth taking as is, but nothing is copied blindly. Reconfirmed on 2026-09-03 against the Codex plan, which proposed importing modules; the Codex reuse audit is kept as a reading step in phase 0 that produces a reuse matrix. |
| D2 | Naming | `smartparks-protect` everywhere | Repo, product and technical name agree. Containers are `protect-<service>`, the shared Python package is `smartparks-protect-shared` importing as `shared`. |
| D3 | Database | PostgreSQL 17 + PostGIS + TimescaleDB from migration 1 | Positions, measurements, source events and gateway receptions are hypertables from the first migration. Retrofitting hypertables on big tables is expensive. Benchmark in phase 4 decides if Timescale stays; native partitioning is the fallback. Image: `timescale/timescaledb-ha`. |
| D4 | Event bus | Redis Streams with consumer groups | Durable, acknowledged, replayable, dead-letter per consumer, one broker to run. Behind an `EventBus` interface so a broker swap later touches one module. |
| D5 | Backend stack | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, FastAPI-Users, `uv` workspace | Same family as AddaxAI Connect so its patterns transfer, current versions, async only, one lockfile. |
| D6 | Entity model | One `entities` table, `entity_types` rows, JSONB attributes validated per type | Admins add types without migrations. Subtype tables only if a type later needs heavy relational queries. |
| D7 | Measurement typing | One hypertable with `value_num`, `value_bool`, `value_text`, `value_json`; metric registry declares the type | One table keeps aggregation and compression simple. Exactly one value column is set per row. |
| D8 | Raw payloads | `source_events` hypertable with JSONB payload, compressed after 7 days, default retention 2 years per DataSource; files in MinIO | Provenance joins stay in SQL, reprocessing is a query. MinIO holds raw log files, uploads and exports. |
| D9 | Rules | Versioned JSON rule documents, Pydantic-validated, Python stateful evaluator, form builder in the UI | Safe and testable. An expression language can become one condition type later. |
| D10 | Plugins | In-repo Python modules with an explicit registry, no dynamic loading | Simple, typed, greppable. Entry points only when a real external plugin need is proven. |
| D11 | Map | MapLibre GL JS only, vector tiles from PostGIS (`ST_AsMVT`) | WebGL rendering meets the 5,000 entity target. No Leaflet. |
| D12 | Frontend | React 19, Vite, TypeScript strict, Tailwind, shadcn/ui, TanStack Query, Zustand, React Hook Form + Zod, Vitest, Playwright | Same stack as AddaxAI Connect so conventions carry over. Smart Parks colours #52735E primary, #90AE9B secondary. |
| D13 | LoRaWAN order | ChirpStack (local docker) first, then KPN/ThingPark, then LORIOT | Full local end-to-end testing before paid networks. TTS and Actility later. |
| D14 | OpenCollar test data | Recorded real payloads as fixtures plus the public Smart Parks decoder repositories | Golden tests give repeatable driver development. Live devices connect once fixtures pass. |
| D15 | EarthRanger delivery | Gundi sensors API, like AddaxAI Connect | Known operational model, Gundi retries delivery. Direct EarthRanger API can become a second connector variant later. Gundi does not return stable EarthRanger object IDs, so updates of sent objects are out of scope. |
| D16 | AddaxAI Connect inbound | Poll the AddaxAI Connect API with a cursor | No change needed in AddaxAI Connect. Idempotency on detection id. Latency is the polling interval. A webhook can replace it later. |
| D17 | Development environment | Local docker compose on WSL2 first, dev VM with Ansible from phase 7 | Everything is testable locally with ChirpStack and a simulator. The VM comes when KPN, LORIOT and Gundi need a public HTTPS endpoint. |
| D18 | Timestamps | `TIMESTAMPTZ` UTC everywhere, per-record timestamp semantics | Canonical rows carry the device-origin time defined by the driver. Delivery times live on the SourceEvent. Display timezone is a user or project setting. |
| D19 | Testing | pytest per package with a payload fixture corpus, API tests against a real Postgres/Timescale container, Vitest, Playwright smoke, CI on every push | No mocked SQL. Benchmarks run outside CI. |
| D20 | Versioning | `VERSION` file, `CHANGELOG.md`, git tags from v0.1.0, servers run tags | Same as AddaxAI Connect. v1.0.0 is the first demonstrator (architecture section 33). |
| D21 | Tenancy | Project-level isolation, `organizations` table reserved but not enforced | Three-tier RBAC plus fine-grained permissions. Organization enforcement is a later decision. |
| D22 | MCP timing | Read-only proof of concept in phase 9, after the first demonstrator | API and RBAC must be stable before wrapping them. |
| D23 | Charts | Apache ECharts | Canvas rendering, dataZoom, brush, large-data mode, state and timeline charts. |
| D24 | Plan tracking | Read at session start, tick boxes as we go, session log at the end | Keeps plan and code in step. |
| D25 | Merged plan | One `PROJECT_PLAN.md` for Claude and Codex, delivery-ordered phases as the spine, Codex's thematic checklists folded in as sub-items | Two trackers drift. The delivery order follows architecture section 31; the thematic order put observability and scalability late, which the architecture forbids. |
| D26 | Database reconfirmed | TimescaleDB from migration 1 stays (D3) | The Codex plan proposed plain PostGIS with a later evaluation. Retrofitting hypertables on 250 million row tables is the expensive path; the gate in phase 4 keeps the exit open. |
| D27 | Assignment attribution | Canonical rows persist `project_id` and `entity_id` resolved at processing time and keep `device_id`; assignment tables stay the source for audit and recomputation | Both plans proposed this. Fast historical queries without range joins; timestamp curation in phase 12 reruns the resolution. |
| D28 | Commit trailers | Strip `Co-Authored-By` lines with the same commit-msg hook as AddaxAI Connect | Both repos behave the same and git history shows human authors only. Decided by Tim on 2026-09-03. |
| D29 | API versioning | `/api/v1` prefix from phase 1; `/api/health` and `/api/version` stay unversioned | ADR 0006. Monitoring paths never change. Decided by Tim on 2026-09-03. |
| D30 | Migrations | One-shot compose service `protect-migrate` runs `alembic upgrade head`; the API waits for it | `docker compose up` always gives a current schema, servers run the same service from the update script, no race between API replicas. Decided by Tim on 2026-09-03. |
| D31 | Primary keys | UUID for domain objects, bigint identity for time-series rows | Domain ids are not guessable and safe in URLs and exports; hypertable rows keep small indexes. Hypertable primary keys include the time column as TimescaleDB requires. Decided by Tim on 2026-09-03. |
| D32 | Raw payload placement | JSONB in `source_events` up to 64 KB, larger payloads in MinIO with a reference and SHA-256 on the row | Provenance joins stay in SQL for every normal uplink; raw log files do not bloat the hypertable. Decided by Tim on 2026-09-03. |
| D33 | Stream trimming | Approximate `MAXLEN` per topic, 100,000 entries by default, 10,000 for dead-letter streams | Bounded memory; the database is the source of truth. Decided by Tim on 2026-09-03. |
| D34 | Webhook authentication | Per-source bearer token, shown once at creation, stored hashed | Works with every IoT platform that can set a header. HMAC signatures can be added per adapter later. Decided by Tim on 2026-09-03. |
| D35 | OpenCollar sources | Driver and fixtures built from the public Smart Parks repositories; recorded live uplinks extend the golden tests when Tim provides them | Work can start without waiting for exports. Decided by Tim on 2026-09-03. |
| D36 | Icons | Lucide (ISC) for technical and UI icons, own monochrome silhouettes for wildlife and infrastructure under the project licence; EarthRanger mappings stay as registry keys | Clean licence today, assets can be swapped later without touching data. Decided by Tim on 2026-09-03. |
| D37 | Base map | OpenFreeMap vector tiles, no key; satellite imagery later behind an optional key as a user choice | Free, native to MapLibre, no tile server to run. Decided by Tim on 2026-09-03. |
| D38 | External deep links | `data_sources.link_templates` JSONB keyed `OPEN_DEVICE`, `OPEN_APPLICATION`, `OPEN_GATEWAY`; URL templates filled from ExternalIdentity attributes; adapters ship defaults, admins override per data source | Built as proposed in architecture 32 during phase 3; no reason found to deviate. Recorded by Claude on 2026-09-03. |

### Open decisions from architecture section 32

These are not decided yet. A proposed default is given so work can start; each is confirmed or changed when its phase begins.

- [x] **External deep links.** Decided on 2026-09-03: built as proposed, see D38.
- [ ] **Control action schema versioning.** Proposed: action definitions are Python dataclasses in the driver with a `schema_version`; parameters are Pydantic models exported as JSON schema for the UI and rules. Decide in phase 6.
- [ ] **Integration delivery idempotency.** Proposed: `integration_deliveries` row per (integration, object type, object id, object version) with a unique key; backfill creates rows in batches. Decide in phase 8.
- [x] **Raw payload placement for very large events.** Decided on 2026-09-03: 64 KB threshold, see D32.
- [x] **Commit trailers.** Decided on 2026-09-03: strip them, see D28.

## Definition of done

Every checked item meets all of these:

- Code follows `CONVENTIONS.md`: crash early and loudly, type hints, simple solutions, no secrets, no em dashes, natural capitalisation.
- Tests exist and pass locally and in CI. Adapters, drivers and rules are tested with recorded fixtures.
- Documentation is updated in the same commit: `DEVELOPERS.md` for mechanisms, `docs/` for users and operators, an ADR for architectural choices, `CHANGELOG.md` under Unreleased.
- User-facing map, chart and table endpoints have an explicit bound (viewport, time range, pagination, resolution, row limit or aggregation). An unbounded endpoint is a defect (architecture 13.10).
- Every processing flow writes ProcessingTrace steps and uses the ApplicationError taxonomy.
- Access control is checked on every new endpoint, with a test per role.
- Provenance and trace behaviour are checked whenever data moves or changes.
- No provider-specific code outside `shared/connectivity/adapters/`, and no device-specific code outside `shared/device_drivers/`.
- The plan checkbox is ticked in the same commit.

## Review checklist: product principles

From architecture section 2, used when reviewing a change. These are never done; they are checked every time.

- Source-agnostic: no domain service or UI component depends on one provider.
- Device-agnostic: device logic lives in drivers, never in services or UI.
- Entity-centric: users work with animals, people, vehicles, gates, traps and sensors, not device ids.
- Raw data retained: original payloads stay available and immutable.
- Normalized data first-class: positions, measurements, states and events use stable schemas.
- Analytics is primary: tables, charts, aggregation and export are core.
- Rules produce meaning: versioned, testable, traceable events.
- Integrations first-class: durable delivery with retry, status and traceability.
- Control is bidirectional and capability-driven through one command path.
- Project-aware and self-hosted.
- Provenance visible: every canonical record links to source and trace.
- Bounded queries everywhere.
- Entity and device history stays correct across hardware replacement.

## Milestones and versions

| Version | End of phase | Meaning |
| --- | --- | --- |
| v0.1.0 | 3 | First vertical slice: simulator to ChirpStack to OpenCollar decode to live map, traffic viewer and trace explorer |
| v0.2.0 | 4 | Data Explorer, export jobs, benchmark fixture, TimescaleDB decision confirmed |
| v0.3.0 | 5 | Rules, events, alerts, automations, email and Telegram notifications |
| v0.4.0 | 6 | Device control through ChirpStack |
| v0.5.0 | 7 | KPN and LORIOT adapters, device control over a second network, dev server deployed with Ansible |
| v1.0.0 | 8 | First demonstrator: EarthRanger, AddaxAI Connect inbound, Traccar, gateways, provenance links, section 33 demonstration passes |
| v1.1.0 | 9 | MCP read-only proof of concept |
| v1.2.0 | 10 | Full observability, System Health, backup and disaster recovery proven |
| v1.3.0 | 11 | WebBLE, raw log files, Cloudloop/Iridium |
| v1.4.0 | 12 | Data curation and corrections |
| v1.5.0 | 13 | The Things Stack, Actility, WildlifeNL, FerusTracker, Movebank, dashboards, MCP write tools |
| v2.0.0 | 14 | Production hardening, full-scale benchmark, documentation audit |

## Architecture coverage map

Every section of the architecture document maps to at least one phase. Use this to check completeness.

| Architecture section | Phase |
| --- | --- |
| 1-4 Summary, principles, relationship, high-level architecture | 0 (ADRs), all |
| 5-6 Domain model and core entities | 1 |
| 7 Connectivity layer | 2, 3, 7, 8 |
| 8 LoRaWAN specialization, capabilities, traffic viewer | 3, 7 |
| 9 Device drivers and OpenCollar | 2, 3 |
| 10 Data model for analytics, metric registry, storage | 1, 4 |
| 11 Monitor workspaces, live updates | 3 |
| 12 Analyze, Data Explorer | 4 |
| 13 Scalability, geospatial serving, bounded queries | 1, 3, 4, 14 |
| 14 Export | 4 |
| 15 Rules and automation engine | 5 |
| 16 Events, alerts, actions | 5 |
| 17 Bidirectional control | 6, 7 |
| 18 Integrations, EarthRanger, AddaxAI Connect inbound | 8 |
| 19 Internal event bus | 2 |
| 20 Gateway and network monitoring | 3 (receptions), 8 (registry and health) |
| 21 Provenance and external navigation | 3, 8 |
| 22 Security, tenancy, traceability | 1, 10, 14 |
| 23 UI and branding | 3 |
| 24 Icon system and map symbology | 3, 8 |
| 25 Multi-path OpenCollar, WebBLE, raw logs, Iridium | 2 (dedup model), 11 |
| 26 Observability and traceability | 1 (contract), 2, 3 (basic screens), 10 (full) |
| 27 MCP | 9, 13 |
| 28 Documentation and developer experience | 0, every phase |
| 28 Outbound wildlife platforms, notification channels | 5 (notifications), 13 (platforms) |
| 28 Device onboarding and project assignment | 1, 2, 3 |
| 28 Backup and disaster recovery | 10 |
| 28 Data curation | 12 |
| 28 Application navigation | 3 |
| 29 Repository structure | 0 |
| 30 MVP recommendation | 1-8 |
| 31 Development sequence | phase order below |
| 32 Open decisions | decisions table above |
| 33 Definition of success | 8 |

## Target repository structure

```
smartparks-protect/
├── services/
│   ├── api/                 # FastAPI: REST, WebSocket, OpenAPI, auth, admin, vector tiles
│   ├── frontend/            # React + Vite + TypeScript
│   ├── ingest/              # Adapter runners (MQTT subscriptions, pollers), SourceEvent intake
│   ├── decoder/             # Driver selection, decode, canonicalization, dedup, current state
│   ├── rules/               # Stateful rule evaluation, events, alerts
│   ├── automation/          # Actions: notifications, webhooks, commands
│   ├── integration/         # Outbound connectors with durable delivery (EarthRanger, webhooks, MQTT)
│   ├── aggregation/         # Continuous aggregates, retention, benchmark helpers
│   ├── export/              # Export jobs, streaming writers
│   └── mcp/                 # MCP server (phase 9)
├── shared/                  # smartparks-protect-shared, imported as `shared`
│   └── shared/
│       ├── config.py        # pydantic-settings
│       ├── database.py      # async engine and sessions
│       ├── models/          # SQLAlchemy models by domain area
│       ├── schemas/         # Pydantic schemas shared by services
│       ├── bus.py           # Redis Streams EventBus
│       ├── storage.py       # MinIO client
│       ├── logger.py        # structured JSON logging with trace ids
│       ├── trace.py         # ProcessingTrace helpers and error taxonomy
│       ├── metrics/         # metric registry seeds
│       ├── domain/          # assignment resolution, canonical keys, current state
│       ├── device_drivers/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── generic_json/
│       │   └── opencollar/
│       └── connectivity/
│           ├── base.py
│           ├── registry.py
│           ├── transports/  # mqtt, http, websocket, polling
│           └── adapters/    # chirpstack, kpn_thingpark, loriot, tts, actility, traccar, cloudloop, addaxai_connect
├── tests/
│   ├── fixtures/payloads/   # recorded real payloads per adapter and driver
│   └── <package>/           # one directory per package, mirrors CI matrix
├── docs/                    # MkDocs Material site, structure from architecture 28.2
│   └── adr/
├── examples/                # example payloads, adapter and driver skeletons
├── scripts/                 # dev simulator, benchmark generator, backup, restore
├── ansible/                 # deployment automation (phase 7)
├── docker-compose.yml
├── pyproject.toml           # uv workspace root
├── CONVENTIONS.md
├── DEVELOPERS.md
├── PROJECT_PLAN.md
├── CHANGELOG.md
├── VERSION
└── README.md
```

## Phases

Each phase has a goal, a reason for its place in the sequence, deliverables with checkboxes, and exit criteria. Phases follow the development sequence in architecture section 31. Phases 0-8 are the MVP from section 30.1. Sub-items can be reordered inside a phase; phases are not reordered without a session log note.

---

### Phase 0: repository foundation

**Goal.** A repository where every later phase has a place: tooling, empty services, compose stack, documentation skeleton and CI that is green on an empty project.

**Why first.** Architecture 28.12 asks for the documentation structure and contributor files at repository creation. CI and docs checks from the start keep the Definition of Done enforceable. Starting from scratch (D1) means the skeleton is the first real design act.

**Deliverables.**

- [x] Copy `CONVENTIONS.md` verbatim from AddaxAI Connect (2026-09-03).
- [x] Create `DEVELOPERS.md` and `PROJECT_PLAN.md` (2026-09-03).
- [x] `.gitignore` based on AddaxAI Connect, plus WSL `Zone.Identifier` files; remove the committed Zone.Identifier file (2026-09-03).
- [x] Compare the Claude and Codex plans and merge them into this file (2026-09-03). What was taken from each is in the session log.
- [x] Reuse audit of AddaxAI Connect (2026-09-03): `docs/architecture/addaxai-connect-reuse-audit.md` with a matrix of mechanisms to mirror, adapt as a pattern, or leave out (auth and invitation flow, RBAC, queue and worker liveness, logging, deployment roles and hardening, frontend shell and conventions, notification workers, backup scripts). Reading only, no code is copied.
- [x] `README.md` (2026-09-03): what Smart Parks Protect is, status (pre-alpha, nothing runs yet), core concepts in ten lines, link to the architecture document, plan and developer docs. Quick start is added at the end of phase 3.
- [x] `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md` with an Unreleased section (2026-09-03). `VERSION` is created with the first release.
- [x] `docs/` skeleton (2026-09-03) from architecture 28.2 (getting-started, architecture, concepts, devices, integrations, analytics, rules, administration, operations, troubleshooting, api, mcp, adr) with an index page each, `mkdocs.yml` (Material), `mkdocs build --strict` passing.
- [x] ADR template and ADR 0001 (2026-09-03) "Record architecture decisions". ADRs 0002-0005 for D1 (from scratch), D3 (database), D4 (event bus), D5 + D12 (stack). ADR 0006: schema versioning policy for bus messages, webhook payloads and API responses (architecture 28.6). Remaining ADRs are written in the phase where the decision lands.
- [x] Python workspace (2026-09-03): root `pyproject.toml` with `uv` workspace members `shared/` and `services/*`, `ruff` (lint and format), `mypy` strict for `shared/`, `pytest` config with markers. Python 3.12.
- [x] `shared/` skeleton (2026-09-03): `config.py`, `database.py` (async engine, session factory), `logger.py` (JSON, `trace_id` and `request_id` fields), package metadata, version reading from `VERSION`.
- [x] `docker-compose.yml` (2026-09-03): `protect-postgres` (`timescale/timescaledb-ha`, PostgreSQL 17), `protect-redis` (Redis 7), `protect-minio` and `protect-minio-init`, `protect-api`, `protect-frontend`. Profile `chirpstack` with ChirpStack, its MQTT broker and Postgres, ready for phase 3. `.env.example` with every variable documented. Named volumes, healthchecks, `restart: unless-stopped`.
- [x] `services/api` skeleton (2026-09-03): FastAPI app, `/api/health` returning database, Redis and MinIO status, request id middleware, OpenAPI at `/api/docs`, Dockerfile.
- [x] `services/frontend` skeleton (2026-09-03): Vite, React 19, TypeScript strict, Tailwind, shadcn/ui initialised, Smart Parks colours as CSS variables, MapLibre GL, ECharts, TanStack Query, React Router, Zustand, RHF + Zod installed. Login placeholder page. `npm run build` runs `tsc --noEmit && vite build`. Nginx Dockerfile. `FRONTEND_CONVENTIONS.md` written for this repo (colour system, z-index ladder, responsive rules, viewport targets 390/768/1440).
- [x] CI (`.github/workflows/ci.yml`) (2026-09-03, green on the first push): ruff, mypy, pytest per package against Postgres/Timescale and Redis service containers, `pip check` equivalent via `uv sync --frozen`, frontend `npm ci && npm run build && npm run test`, `mkdocs build --strict`. Fail-fast off.
- [x] `scripts/dev.sh` (2026-09-03, `make` is not installed on the dev machine and a shell script needs nothing else) with the daily commands: up, down, logs, migrate, test, lint, sweep.

**Exit criteria.** `docker compose up` starts the infrastructure, the empty API answers `/api/health` with all three dependencies OK, the frontend serves the placeholder, CI is green, docs build. All verified on 2026-09-03; CI green on the first push (run 33751856553).

---

### Phase 1: core domain, database and access control

**Goal.** The canonical schema, migrations, ORM models, authentication, RBAC and admin CRUD for every object that later phases build on. The ProcessingTrace contract exists before any adapter is written.

**Why here.** Architecture 31 step 2 and 26.11: define schemas and the trace contract before multiple adapters and workers exist. Everything downstream depends on Device, Entity, assignments, DataSource and ExternalIdentity being right.

**Deliverables.**

- [x] Alembic configured for async SQLAlchemy. Migration 0001 creates extensions `postgis` and `timescaledb`.
- [x] Access control tables: `users`, `organizations` (reserved, D21), `projects`, `project_memberships` (role per project), `invitations`, `audit_log`. Server admin flag on users. Fine-grained permission keys defined in code and mapped from roles: `devices:control`, `devices:control_high_impact`, `rules:write`, `integrations:write`, `data:curate`, `data:curate_bulk`, `data:approve`, `data:revert`, `traces:read`.
- [x] Domain tables: `entity_types` (icon key, JSON schema for attributes, group), `entities` (project, type, name, status, optional geometry, JSONB attributes), `features` (sites, zones, geofences, routes with PostGIS geometry), `device_types` (driver key, capabilities), `devices` (server-level, no project column), `device_project_assignments` and `device_entity_assignments` with `tstzrange` validity and a GiST exclusion constraint against overlaps, `data_sources` (adapter key, capabilities JSONB, encrypted credentials, project scoping, link templates), `external_identities` (unique per data source and external id), `metrics` (registry: key, unit, value type, category).
- [x] Time-series tables as hypertables: `source_events`, `positions` (PostGIS point, device, resolved entity and project, canonical key unique), `measurements` (D7), `gateway_receptions`, `device_state_history`. Latest-state tables: `device_current_state`, `entity_current_state`, `connectivity_state`. Compression and retention policies as parameterised migration steps.
- [x] Event tables: `events`, `alerts` (separate from events, architecture 16), placeholders for `rules` and `rule_versions` used in phase 5.
- [x] Trace tables: `processing_traces`, `processing_steps`, `application_errors` with the error code enum from architecture 26.5. `shared/trace.py` helper: start trace, add step, fail step with error, finish. Compact mode for successful routine telemetry (26.9).
- [x] `shared/domain/assignments.py`: resolve device to project and entity at a given canonical time. Tests include the architecture 28.9 example (raw log from 20 August with a fix from 15 July belongs to the old project).
- [x] Indexes from measured needs only: time plus device, time plus entity, GiST on geometry. Documented in `docs/architecture/data-model.md`. (BRIN on time deferred to the phase 4 benchmark, 2026-09-03.)
- [x] Authentication: FastAPI-Users with JWT, registration by invitation only, email verification, password reset, SMTP sender. Same flow as AddaxAI Connect, written fresh. (Verification is by the invitation token; there is no separate verify-email flow because nobody can register without an invitation, 2026-09-03.)
- [x] RBAC dependencies: `require_server_admin`, `require_project_role(project_id, role)`, `require_permission(key)`. Access to canonical rows follows historical project attribution (architecture 28.12).
- [x] Admin API: projects, users, memberships and invitations, entity types, entities, features, device types, devices, data sources (credentials write-only, never returned), external identities, metrics. Device handover workflow endpoint (28.10) that closes and opens assignments with validation.
- [x] Bulk device import from CSV (28.7 fields).
- [x] Bounded query dependency: every list endpoint takes limit and cursor; a shared test asserts no list endpoint lacks a bound.
- [x] Tests: migrations up and down from empty database, CRUD with RBAC per role, assignment resolution, overlap rejection, handover.
- [x] Docs: `docs/concepts/domain-model.md` (Device versus Entity, assignments, DataSource and ExternalIdentity, four data levels), `docs/architecture/data-model.md`, `docs/administration/permissions.md`. ADRs: canonical domain model, device timestamp deduplication, processing trace model, assignment attribution (open decision above).

**Exit criteria.** From an empty database, migrations apply, a server admin invites a project admin, who creates a project, a data source, a device with an external identity, assigns it to the project and to an entity with effective dates, hands it over to a second project, and every step is tested and audited. Met on 2026-09-03: `tests/api/test_phase1_scenario.py` runs exactly this (the server admin creates the project and the data source, which are server-level objects; the project admin does the rest).

---

### Phase 2: connectivity abstraction and ingestion pipeline

**Goal.** Source events flow from a generic inbound path through identity resolution, driver decoding, canonicalization and deduplication into positions, measurements and states, with a full trace. No provider-specific code yet: a generic HTTP webhook source and a generic MQTT source with a generic JSON driver prove the pipeline.

**Why here.** Architecture 30.1: the connectivity abstraction is implemented before provider-specific code. Building ChirpStack first would let ChirpStack shapes leak into the domain.

**Deliverables.**

- [x] `shared/bus.py`: Redis Streams EventBus. Publish, subscribe with consumer group, ack, retry with backoff, per-consumer dead-letter stream, pending message recovery on restart, heartbeat key per worker (15 minute staleness rule). Topics: `source_event.received`, `position.created`, `measurement.created`, `device.state_changed`, `event.created`, `alert.created`, `command.updated`, `delivery.updated`, `needs_attention.created`. Tests against a real Redis.
- [x] `shared/connectivity/base.py`: `EventConnector`, `CommandConnector`, `ManagementConnector` protocols; `AdapterCapabilities` model (architecture 8.2); adapter registry. `transports/`: MQTT client (aiomqtt), HTTP webhook receiver helpers, polling base class, websocket base class.
- [x] `shared/device_drivers/base.py`: `DeviceDriver` protocol with capabilities, `decode(source_event) -> DecodedRecords` (positions, measurements, states, events, log records), timestamp semantics declaration per record type, canonical key function, `encode(action, params) -> ProtocolPayload` (used in phase 6). Driver registry. `generic_json` driver for tests and simple custom devices.
- [x] `services/ingest`: runs adapter event connectors for every enabled data source, stores SourceEvent with provider metadata (network received time, ingestion method, acquisition channel), resolves ExternalIdentity, publishes `source_event.received`. Webhook inbound endpoints live in the API and publish the same way. SourceEvents carry a `processing_status` (received, processed, duplicate, failed, unassigned) so Needs Attention and health counts are cheap queries.
- [x] `services/decoder`: consumes `source_event.received`, selects the driver from the device type, decodes, resolves the canonical device timestamp, computes the canonical key (device EUI + device timestamp + record type + optional fingerprint, architecture 25.3), deduplicates against existing canonical rows and links additional deliveries, resolves project and entity at the canonical time, writes canonical rows and updates current state in one transaction, publishes domain events, writes trace steps, maps failures to ApplicationErrors.
- [x] Unknown device workflow: SourceEvents for unresolved identities are retained and appear in Needs Attention with data source, external id, first and last seen, count and inferred type. Actions: create device, link to existing device, assign project, ignore, reprocess (architecture 28.6).
- [x] Late data policy: canonical rows carry `ingested_at` next to `time`; a helper computes event age for phase 5 freshness checks (25.8).
- [x] Needs Attention and dead-letter API: list, retry, reprocess, reassign, ignore, resolve, each audited.
- [x] Generic MQTT and generic HTTP data source types configurable from the admin API.
- [x] Tests: pipeline with the generic driver; the same record delivered twice creates one position with two source deliveries; late record attributed to the historical project; unknown device retained and reprocessed after linking; decode failure lands in dead-letter with `PAYLOAD_DECODE_FAILED`.
- [x] Docs: `docs/architecture/processing-pipeline.md`, `docs/devices/driver-interface.md`, `docs/integrations/adapter-interface.md`, `docs/concepts/timestamps-and-deduplication.md`. ADR: connectivity adapter boundary. `examples/device-drivers/` and `examples/adapters/` skeletons.

**Exit criteria.** A JSON payload posted to the generic HTTP source produces a position visible through the API with a complete trace. Posting it again links a second delivery and creates no second position. An unknown device id appears in Needs Attention and its data is processed after linking. Met on 2026-09-03: `tests/api/test_ingest_and_attention.py` and a run against the compose stack with the ingest and decoder containers.

---

### Phase 3: ChirpStack, OpenCollar and the first frontend (v0.1.0)

**Goal.** The first end-to-end vertical slice: a simulated OpenCollar sends uplinks through a local ChirpStack, the OpenCollar driver decodes them, the entity appears on the live map, the traffic viewer shows raw and decoded data, and the trace explorer shows the steps.

**Why here.** Architecture 31 step 4. ChirpStack is the full-feature reference implementation and runs locally (D13). OpenCollar is the first comprehensive driver. A usable UI from this point gives every later phase something to demonstrate.

**Deliverables.**

Backend:

- [x] ChirpStack adapter (2026-09-03, management connector lists applications, devices and gateways; command connector in phase 6): MQTT event connector for uplink, join, ack, txack, log and status events mapped to the normalized LoRaWAN event types (8.1); gateway receptions with RSSI and SNR per uplink; management connector via the ChirpStack gRPC or REST API (list applications, devices, gateways); capabilities declared per data source; deep link templates for device, application and gateway. Command connector is completed in phase 6.
- [x] ChirpStack in docker compose (2026-09-03, `scripts/chirpstack_bootstrap.py` mints the API key and creates everything; the simulator publishes integration events, not radio frames) (profile `chirpstack`) with a documented bootstrap (tenant, application, device profile, simulated gateway). `scripts/simulate_opencollar.py` publishes recorded fixtures as uplinks through the ChirpStack MQTT integration, at a configurable rate.
- [x] OpenCollar driver (2026-09-03, from the public firmware 7.3.0 and decoder; ports 2, 4, 12, 13, 14, 16, 18, 19, 20, 29, 31, 3 and 30 decoded, scan and satellite ports accepted without canonical rows; recorded live uplinks still wanted): port mappings, decoder per message type ported from the public Smart Parks decoders, firmware and decoder version metadata, capabilities (gnss, accelerometer, battery, activity, remote settings, drop-off), timestamp semantics per record type including embedded log timestamps, canonical keys, golden tests over `tests/fixtures/payloads/opencollar/`. Driver documentation is the reference example for extension docs (28.12).
- [x] Metric registry seeds from architecture 10.2 plus the OpenCollar metrics (migration 0003, 2026-09-03).
- [x] Current-state API (2026-09-03) for the live map: bounded by project and viewport, served as vector tiles (`ST_AsMVT`) above a threshold and as GeoJSON below it. Track API with automatic simplification by period (13.4), maximum points per response, progressive drill-down.
- [x] WebSocket endpoint (2026-09-03) bridged from the event bus: per-project channel, sends compact current-state updates, target p95 under 2 seconds from commit (13.7).
- [x] LoRaWAN traffic API (2026-09-03): paginated normalized events with raw payload, decoded result, gateway receptions and trace link.
- [x] Trace API (2026-09-03): search by device, entity, EUI, trace id, data source, time range, status and error code; trace detail with ordered steps.
- [x] System Health API (basic, 2026-09-03): worker heartbeats, stream lag per consumer group, events per minute, dead-letter counts, data source connectivity.

Frontend:

- [x] App shell (2026-09-03): login, invitation acceptance, password reset, project switcher, sidebar navigation with the sections from architecture 28 (Monitor, Analyze, Network, Rules, Integrate, Control, Admin), responsive layout, Smart Parks logo and colours. Route guards per role. Empty states for screens that later phases fill.
- [x] Icon registry (2026-09-03, starter set of 20 own silhouettes under MIT, EarthRanger keys as mappings): `src/assets/icons/` by category, `icon-registry.json` with key, category, label, asset, source, licence, aliases, fallback and EarthRanger mapping. Marker renderer with shape families for entity, infrastructure and event, colour for state, badge overlay. Starter set covering the concepts in 24.10. Licence review recorded per asset.
- [x] Admin screens (2026-09-03): projects, users and invitations, data sources (with a capability inspector showing what the adapter and this account support, and a connection test), device types, devices (assignments, handover dialog, external identities, bulk import), entity types (icon and attribute schema), entities, features (draw geofences on the map), metrics.
- [x] Live map (2026-09-03): MapLibre, current-state layer with icon registry symbols and clustering, selection panel with entity, assigned device, connectivity state, last seen, quick link to device and trace, track toggle with period selection, features layer.
- [x] Devices and Entities list screens (2026-09-03) with status, last seen, project and assignment.
- [x] Network (2026-09-03): LoRaWAN traffic viewer (8.3) with expandable raw, decoded, gateway reception and trace details.
- [x] Trace Explorer (basic) and Needs Attention screen (2026-09-03) with the remediation actions from phase 2.
- [x] System Health (basic, 2026-09-03).
- [x] Provenance panel (2026-09-03) on a position and a source event: DataSource, external identity, all deliveries, Open in ChirpStack link.
- [x] Playwright sweep (2026-09-03, `npm run sweep`, routes derived from the router; a `@playwright/test` smoke with assertions follows when CI gets a browser): login and open every page at 390, 768 and 1440 px; screenshot sweep script.

Release:

- [x] `README.md` quick start (2026-09-03): clone, `.env`, `docker compose --profile chirpstack up`, bootstrap, run the simulator, open the map.
- [x] `VERSION` v0.1.0, `CHANGELOG.md` (2026-09-03); the tag is created after the commit.

**Exit criteria.** Run the quick start on a clean checkout and see a simulated collar move on the map, its uplinks in the traffic viewer, its trace in the explorer and a working Open in ChirpStack link. Met on 2026-09-03 on the development stack (bootstrap, simulator, map, traffic, traces, ChirpStack links from the identity attributes). A clean-checkout run is the first thing to do in the next session.

---

### Phase 4: analyze, export and the scale benchmark (v0.2.0)

**Goal.** The Data Explorer and export as backend capabilities, a synthetic scale dataset, and the decision whether TimescaleDB stays.

**Why here.** Architecture 31 step 5: implement Data Explorer and export early to validate the time-series storage decisions before rules and integrations depend on them.

**Deliverables.**

- [ ] Aggregation API: filters by project, entities, devices, metrics, data source and time range; automatic resolution selection targeting 2,000-5,000 samples per series with user override; `time_bucket` aggregates mean, min, max, median, sum, count, first, last; long and wide layouts; drill-down from a bucket to normalized rows and to source events.
- [ ] Continuous aggregates for hourly and daily buckets when benchmarks show repeated expensive queries.
- [ ] Data Explorer UI: filter builder, virtualized table with sort, filter, column selection and grouping, ECharts line, scatter, bar, histogram and state timeline, multi-series comparison across entities and devices, timezone selection, drill-down, saved views per project.
- [ ] Export jobs: `export_jobs` table, worker in `services/export`, streaming CSV, XLSX (with Excel row limits enforced), JSON, GeoJSON and GPX for tracks, data level selection (raw, decoded, normalized, aggregated), metadata columns, recorded filters and units for reproducibility, small exports returned directly, large ones as MinIO objects with a download link. Target: 10 million rows CSV without memory growth.
- [ ] Exports UI: job list with progress, download, reproduce.
- [ ] `scripts/benchmark/generate.py`: synthetic dataset generator scalable up to the reference envelope (13.9), with realistic spatial clustering and time distributions, multiple projects and data sources. `scripts/benchmark/run.py`: live map load, viewport tiles, 1-day, 30-day and 1-year tracks, Data Explorer aggregates, exports, ingest bursts. Results written to `docs/operations/benchmarks.md`.
- [ ] Benchmark run at 1/10 scale on the development machine. Compare against the performance budgets in 13.7. Fix what fails.
- [ ] TimescaleDB decision gate: confirm or replace with native partitioning. Update ADR 0003.
- [ ] Retention and compression policies verified against the benchmark dataset.
- [ ] Docs: `docs/analytics/data-explorer.md`, `docs/analytics/export.md`, `docs/architecture/scalability.md`.

**Exit criteria.** Benchmark results recorded and within budget at the tested scale, a 1 million row export streams with flat memory, the Timescale decision is written down.

---

### Phase 5: rules, events, alerts, automations and notifications (v0.3.0)

**Goal.** The stateful rules engine with the four initial rules, events and alerts as separate objects, automations that turn events into actions, and channel-neutral notifications over email and Telegram.

**Why here.** Architecture 31 step 6: add the rule and automation interfaces with a few simple rules before advanced scientific expressions. Notifications are the first action type and are needed by later phases for integration failures, command failures and backup alerts.

**Deliverables.**

- [ ] Rule schema (D9): trigger (position, measurement, state, event, schedule), condition tree (threshold, spatial ENTER/EXIT/INSIDE/OUTSIDE/NEAR/DWELL, movement, temporal FOR and COUNT, aggregation over windows, baseline, correlation, event chaining), event template (type, severity, context values), actions. Pydantic validation, JSON schema for the UI. `rules` and `rule_versions` tables; every event references the rule version.
- [ ] `services/rules`: consumes domain events, keeps per-rule and per-entity state (windows, dwell timers) in Postgres, evaluates geofences with PostGIS, emits events, respects late data freshness policy (25.8), traces every evaluation compactly.
- [ ] Rule testing: run a rule version over a historical time range by replaying canonical data, show the events it would have produced, without side effects.
- [ ] Initial rules shipped as templates: geofence enter and exit, speed limit inside an area, inactivity or no data for a duration, battery threshold.
- [ ] Events and alerts: event list and detail, alert lifecycle (open, acknowledged, resolved) with actor and time, alert inbox per project, event and alert markers on the map using the event marker family.
- [ ] `services/automation`: automations bind event types and filters to actions; action framework with delivery tracking (status, attempts, delivered time, error, trace). Action types: notification, webhook (basic), integration forward (completed in phase 8), device command (completed in phase 6).
- [ ] Notifications: notification targets at project and organization level, email over SMTP with templates and links back to the object, Telegram bot targets with chat registration, severity-aware formatting, delivery workers with retry and dead-letter.
- [ ] System alerts use the same path: worker down, stream lag, dead-letter growth, data source unreachable.
- [ ] Rules UI: list, form builder, version history, test run with results, enable and disable. Automations UI. Notification targets UI. Events and Alerts screens.
- [ ] Tests: each construct with fixtures, replay test, freshness test, delivery retry test.
- [ ] Docs: `docs/rules/` (concepts, constructs, examples from 15.3 and 15.4, testing), `docs/administration/notifications.md`. ADR: rule representation.

**Exit criteria.** The four template rules fire on simulated data, produce events and alerts, and deliver email and Telegram notifications with tracked status. A rule replay over the past week matches live results.

---

### Phase 6: device control through ChirpStack (v0.4.0)

**Goal.** The capability-driven Device Control Framework with the full command lifecycle, OpenCollar RESET and REQUEST_STATUS through the ChirpStack adapter, usable from the UI and from automations through one path.

**Why here.** Control needs the driver (phase 3), the trace model (phase 1) and the action framework (phase 5). Doing it on ChirpStack first means downlinks are tested locally before airtime is spent on KPN or LORIOT.

**Deliverables.**

- [ ] Control action definitions per driver (architecture 17.3): key, label, description, typed parameters with validation and units, required permission, confirmation policy, required connectivity capability, encoder, result interpretation. Exported as JSON schema for the UI and rules.
- [ ] `commands` and `command_executions` tables with the lifecycle states from 17.4; unsupported stages stay unknown, never fabricated.
- [ ] Command path: API creates the command, driver encodes, route selection chooses the connectivity adapter from active data sources and capabilities, adapter submits, provider events update the lifecycle (ChirpStack txack and ack), device responses close the loop where the driver interprets them. Every step traced (26.7).
- [ ] ChirpStack command connector: enqueue downlink, read queue state, flush.
- [ ] OpenCollar encoders for RESET and REQUEST_STATUS, plus SET_GNSS_INTERVAL if the protocol fixtures allow it.
- [ ] Permissions and confirmation: `devices:control` for operational actions, `devices:control_high_impact` for reset and configuration, explicit confirmation dialog, audit entries.
- [ ] Automations can invoke control actions through the same API as the UI.
- [ ] UI: actions menu on the device built from capabilities with disabled reasons, command dialog with parameter form and confirmation, command history with lifecycle timeline and trace link, Control section with command list.
- [ ] Tests: encoding golden tests, route selection with two data sources, lifecycle updates from provider events, permission checks.
- [ ] Docs: `docs/devices/device-control.md`, `docs/devices/opencollar.md` control section. ADR: control action schema versioning.

**Exit criteria.** RESET issued from the UI appears in the ChirpStack downlink queue, the lifecycle shows SUBMITTED, QUEUED and TRANSMITTED from ChirpStack events, and the same action fired by an automation follows the identical path.

---

### Phase 7: production LoRaWAN networks and the dev server (v0.5.0)

**Goal.** KPN/ThingPark and LORIOT adapters with no change to domain or UI code, OpenCollar control over a second network, and a deployed dev server with Ansible.

**Why here.** Architecture 31 step 8: add KPN and LORIOT and verify that no domain or UI code needs provider-specific changes. Push integrations from public networks need a reachable HTTPS endpoint, so the dev VM arrives now (D17).

**Deliverables.**

- [ ] KPN/ThingPark adapter: HTTP push event connector (uplink, downlink status where exposed), REST management where the account allows, downlink command connector, capabilities per data source, timestamps mapping, deep links, runbook with setup, authentication, uplink and downlink flow, timestamps and troubleshooting (28.7).
- [ ] LORIOT adapter: websocket or HTTP push event connector, downlink command connector, management where available, capabilities, deep links, runbook.
- [ ] Guard test: a test asserts that no file outside `shared/connectivity/adapters/` imports or names a provider, and the frontend has no provider string outside the adapter display metadata.
- [ ] OpenCollar RESET or REQUEST_STATUS executed through KPN or LORIOT, proving the same action over two networks (30.1).
- [ ] Ansible: roles for docker, nginx with TLS, security hardening (ufw, unattended upgrades, fail2ban on SSH, SSH keys only, sshd drift check), app deploy from a git tag, env and secrets handling with vault, `inventory.yml.example` and host vars examples. Dev server can run `main`.
- [ ] `scripts/verify-server.sh` and `scripts/security-status.sh` equivalents.
- [ ] Dev server deployed, real collars from KPN and LORIOT visible on the map.
- [ ] Docs: `docs/getting-started/deployment.md`, `docs/operations/update-guide.md`, `docs/integrations/kpn-thingpark/`, `docs/integrations/loriot/`.

**Exit criteria.** Live OpenCollar data from two different LoRaWAN backends shows on one map, a control action works over the second network, the dev server is reproducible from the playbook.

---

### Phase 8: integrations, Traccar, gateways and the first demonstrator (v1.0.0)

**Goal.** Durable outbound integrations with EarthRanger first, the AddaxAI Connect inbound connector, a Traccar proof of concept, gateway monitoring, complete provenance links, and the section 33 demonstration.

**Why here.** Architecture 31 steps 7 and 9. Integrations need stable domain events (phase 2), rules (phase 5) and a public endpoint (phase 7). Traccar proves the platform is not LoRaWAN-only before the core abstractions are declared done.

**Deliverables.**

- [ ] Integration framework in `services/integration`: `integrations` (per project, connector key, credentials, filters for entities, devices, event types, measurements, historical data) and `integration_deliveries` (object, version, status, attempts, request and response, external id, trace) tables; worker with retry and backoff, idempotency keys, backfill over a date range in batches, project enable and disable, isolation so an outage never blocks ingestion (18).
- [ ] EarthRanger connector via Gundi (D15): positions as observations, events with type slugs in a `smartparks_protect_` namespace, entity mapping to subjects, per-project Gundi key, test event, health status. Direct EarthRanger API connector recorded as a later option.
- [ ] Webhook outbound connector with signed payloads. MQTT outbound connector.
- [ ] AddaxAI Connect inbound connector (D16): polling event connector with a cursor per data source, authentication with an AddaxAI Connect API token, per-project filters (detection types, species, confidence threshold, AddaxAI projects), mapping to `SPECIES_DETECTION` events with taxonomy, confidence, camera and site context, position, source detection id as ExternalIdentity, Open in AddaxAI Connect link, idempotency on detection id, raw payload retained.
- [ ] Traccar adapter: websocket or polling event connector for positions, device list management, command connector proof of concept, deep links. One Traccar-fed entity on the map.
- [ ] Gateways: `gateways` registry with location and state, ChirpStack gateway state and statistics, gateway diversity and best-gateway analysis over receptions, Network section screens for gateways and connectivity health. Provider diagnostics kept as attributes (20).
- [ ] ExternalLink coverage: every data source type ships link templates; provenance panel works for every adapter.
- [ ] Integrate section UI: integrations per project, delivery log with payload and response inspection, retry, backfill dialog. AddaxAI Connect source configuration screen.
- [ ] Demonstrator script (architecture 33) written as `docs/getting-started/demonstration.md` and executed: two LoRaWAN backends, same entities on the map, raw and normalized traffic, battery and RSSI analysed and exported, geofence or speed rule creating an event, event forwarded to EarthRanger, one Traccar entity, one AddaxAI Connect wolf detection entering as an event with a source link and forwarded by a rule, an alert acknowledged, a device reassigned to another entity with historical positions staying with the old entity, and one command sent through the abstract control path.
- [ ] `VERSION` v1.0.0, changelog, tag.

**Exit criteria.** The demonstration passes end to end and its result is recorded in the session log with screenshots in `docs/assets/`.

---

### Phase 9: MCP read-only proof of concept (v1.1.0)

**Goal.** A separate MCP service exposing the seven read tools from architecture 27.13 through the normal API with OAuth, tested with Claude and ChatGPT.

**Why here.** D22: the API and RBAC are stable after the demonstrator. The proof of concept validates authentication, tool schemas, permissions and traceability before any write tool exists.

**Deliverables.**

- [ ] `services/mcp`: MCP server over HTTP using the official Python SDK, calling the API with the user's token, never the database.
- [ ] OAuth 2.1 authorization server endpoints on the API (or a small dedicated module) issuing scoped tokens for MCP clients, scopes from 27.5, dynamic client registration if the clients require it.
- [ ] Resources from 27.2 for projects, entities, devices, events, rules, data sources and traces.
- [ ] Tools: `search_entities`, `get_entity`, `get_device`, `get_latest_position`, `query_measurements`, `query_events`, `get_processing_trace`, plus `list_projects`. Every tool bounded (27.7).
- [ ] Prompts: `analyze-device-health`, `investigate-missing-data`.
- [ ] Audit: every tool invocation logged with user, client type and name, tool and trace id.
- [ ] AI action policy table with all write classes disabled.
- [ ] Verified with Claude and ChatGPT. Results and screenshots in `docs/mcp/`.
- [ ] Docs: `docs/mcp/` (setup, authentication, tools, limits). ADR: MCP security boundary.

**Exit criteria.** Both clients answer "Why has device X stopped updating?" using the tools against the dev server.

---

### Phase 10: observability, System Health, backup and disaster recovery (v1.2.0)

**Goal.** The full observability model from architecture 26 and a proven disaster recovery from the backup section, before any production deployment.

**Why here.** The backup Definition of Done says a production deployment is not complete without off-server backups, PITR and a tested rebuild. This phase must land before the first production server.

**Deliverables.**

- [ ] OpenTelemetry evaluation and, if accepted, instrumentation of API and workers with correlation to ProcessingTrace ids; metrics for throughput, stream lag, latency and error rates; a documented way to ship them to an external stack (optional Prometheus and Grafana compose profile).
- [ ] System Health full: every area from 26.2 with drill-down into affected traces; Trace Explorer complete with visual timeline; object-level "View processing trace" on positions, measurements, events, alerts, commands, deliveries and log files.
- [ ] Trace retention policies per trace class (26.9) as scheduled jobs.
- [ ] PostgreSQL backups with pgBackRest or WAL-G: base backups plus continuous WAL archiving to S3-compatible off-server storage, encrypted, PITR documented and tested.
- [ ] MinIO replication or versioned backup to remote S3-compatible storage; database-to-object integrity check.
- [ ] Secrets and configuration recovery procedure, separate from the repository.
- [ ] Automated restore verification job in an isolated compose project: restore, migrate, start, health check, record result.
- [ ] Backup and Recovery health page for server admins (28.11 example) integrated with System Health; backup failures raise system alerts through the notification framework.
- [ ] Full clean-server recovery executed once on a throwaway VM and timed against the 4 hour RTO; RPO under 1 hour verified.
- [ ] Security review of the deployment: credentials storage, backup encryption, least privilege, audit of restore access.
- [ ] Docs: `docs/operations/backup-and-recovery.md`, `docs/operations/restore-guide.md`, `docs/operations/observability.md`, `docs/troubleshooting/`.

**Exit criteria.** A recorded clean-server rebuild from off-server backups, restore verification running on a schedule, backup health visible in the UI.

---

### Phase 11: multi-path OpenCollar: WebBLE, raw log files and Cloudloop/Iridium (v1.3.0)

**Goal.** The same OpenCollar record can arrive over LoRaWAN, WebBLE, a raw log file and Iridium, all retained as deliveries and shown once.

**Why here.** The deduplication model exists since phase 2; this phase adds the acquisition paths. It depends on the OpenCollar driver, MinIO and the trace model.

**Deliverables.**

- [ ] `device_log_files` as managed assets (25.6): upload, SHA-256 duplicate detection, association with a device, parse status, record counts (found, new, duplicate, malformed), firmware and decoder version, re-decode, download original. Storage in MinIO.
- [ ] Log file parser in the OpenCollar driver with the same canonical keys, run by a file processing worker with traces.
- [ ] WebBLE in the frontend based on the public Smart Parks OpenCollar WebBLE application: connect, read settings and status, control actions, retrieve stored logs, sync to the backend as deliveries with `ble_synced_at`.
- [ ] Device Control route selection extended with WebBLE and satellite routes (25.5).
- [ ] Cloudloop adapter: inbound Iridium messages as SourceEvents with satellite delivery time separate from device time, outbound MT/SBD command connector, Thing management sync to ExternalIdentity, deep links, runbook (28.7 example).
- [ ] Provenance panel shows all deliveries per canonical record with acquisition channel filter.
- [ ] Late data: rules evaluate offloaded history for completeness, automations skip stale alerts by policy.
- [ ] Docs: `docs/devices/opencollar-webble.md`, `docs/devices/raw-log-files.md`, `docs/integrations/cloudloop/`.

**Exit criteria.** One GNSS record delivered by simulator over ChirpStack, uploaded in a log file and synced over WebBLE results in one position with three deliveries.

---

### Phase 12: data curation and corrections (v1.4.0)

**Goal.** Controlled, versioned, auditable corrections on canonical records with bulk jobs, impact analysis, recomputation and export metadata.

**Why here.** Needs the full pipeline, rules, integrations and exports to recompute and flag downstream effects correctly.

**Deliverables.**

- [ ] `data_corrections` and `curation_jobs` tables with the fields from the curation section; curatable fields declared per record type; status ACTIVE, REVERTED, SUPERSEDED, PENDING; structured reason codes.
- [ ] Effective value layer: canonical rows keep original values; reads for map, analytics, rules and exports use the effective value; original and history available through provenance.
- [ ] Bulk curation workflow: select project, devices, record type, period, transformation (for example timestamp plus 12 hours), preview with sample validation and impact analysis (project and entity attribution changes, affected aggregates, rules, deliveries), apply, revert.
- [ ] Recomputation: change events invalidate aggregates, rebuild track segments and derived measurements, re-evaluate configured rules, flag stale outbound deliveries for review.
- [ ] Permissions and optional two-step approval (propose, approve).
- [ ] Curation workspace UI under Analyze: pending, applied, bulk jobs, reverted, downstream impact; curate action on records in the Data Explorer; curated fields visibly marked.
- [ ] Export options for effective, original canonical and raw views with curation metadata columns.
- [ ] Docs: `docs/analytics/curation.md`. ADR: immutable source data and layered interpretation.

**Exit criteria.** A bulk timestamp correction over a device range shifts the effective values, moves attribution where applicable, recomputes affected aggregates, flags EarthRanger deliveries, and can be reverted without loss.

---

### Phase 13: platform expansion (v1.5.0)

**Goal.** Remaining adapters and outbound platforms from the architecture, project dashboards, and MCP write tools.

**Why here.** Each item reuses proven frameworks. They are ordered by Smart Parks demand and can be picked individually.

**Deliverables.**

- [ ] The Things Stack adapter (events, gateways, downlinks).
- [ ] Actility ThingPark adapter (private and public variants share code with KPN).
- [ ] WildlifeNL outbound connector (API and mappings confirmed in a spike first).
- [ ] FerusTracker outbound connector.
- [ ] Movebank outbound connector with entity, assignment period, timestamp and sensor mappings.
- [ ] Direct EarthRanger API connector variant with stable object ids and updates.
- [ ] Project dashboards: saved views arranged on a grid, shared per project. Not a Grafana clone (30.2).
- [ ] MCP write tools by impact class with the AI action policy: `acknowledge_alert`, `create_event`, `request_device_status`, confirmation flows, privileged scopes.
- [ ] Project-specific SVG icon upload with validation (24.6, optional).
- [ ] Docs and runbooks per connector.

**Exit criteria.** Each connector has a runbook, fixture tests and a recorded live test.

---

### Phase 14: production hardening and 2.0

**Goal.** Full-scale benchmark, documentation audit, security audit, and the remaining architecture items needed for production use across multiple parks.

**Deliverables.**

- [ ] Benchmark at the full reference envelope (13.9) on a representative server; performance budgets met or documented.
- [ ] Documentation Definition of Done audit over the whole site; link check, OpenAPI freshness check and diagram validation in CI (28.8).
- [ ] Security audit: RBAC on every endpoint tested, credential handling, MCP scopes, rate limits, dependency audit.
- [ ] Organization tenancy decision revisited (D21).
- [ ] Multi-language UI decision.
- [ ] Release process documented: version, changelog, upgrade notes, migration and rollback guidance (28.9).
- [ ] `VERSION` v2.0.0.

**Exit criteria.** A new operator deploys production from the docs alone; a new developer adds a driver from the extension docs alone.

---

## Continuous work in every phase

- [ ] Keep `CHANGELOG.md` Unreleased current.
- [ ] Add every recorded real payload to `tests/fixtures/payloads/` with provenance notes.
- [ ] Run the benchmark subset after changes to hypertables, aggregation or map endpoints and compare against the last recorded run.
- [ ] Update `DEVELOPERS.md` when a mechanism is added or changed.
- [ ] Tick boxes here and write the session log.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| OpenCollar decoder details are spread over firmware, Node-RED flows and dashboards | Driver correctness | Fixture corpus from real payloads first, golden tests, driver docs as the single reference, ask Smart Parks for protocol tables early (phase 3 input) |
| KPN or LORIOT expose fewer events or no downlink status | Lifecycle gaps, gateway data missing | Capabilities per data source; unknown stages stay unknown; document per provider |
| TimescaleDB does not meet the budget or licensing is a concern | Storage redesign | Decision gate in phase 4 with native partitioning fallback; hypertable creation isolated in one migration; Timescale community licence is fine for self-hosting, no managed-service resale |
| Vector tile and WebGL map work is larger than expected | Phase 3 delay | Start with bounded GeoJSON under a threshold, add MVT once the current-state table is stable |
| Gundi cannot update or delete sent objects | Curation cannot correct EarthRanger | Flag stale deliveries (phase 12); direct EarthRanger connector in phase 13 |
| Polling AddaxAI Connect adds latency and load | Slow detections | Cursor polling with short intervals; webhook upgrade later |
| Scope is large for one developer and an assistant | Schedule | Strict phase order, MVP through phase 8, every phase demonstrable alone |
| Scope creep from the architecture's later sections | Delayed demonstrator | Sections 25-28 extras stay in phases 10-13 by design |
| Rules become powerful before they are versioned and testable | Irreproducible events | Rule versions and replay testing land in phase 5 before any advanced construct |
| Documentation structure grows without being maintained | Stale docs | Docs land in the same commit as code; `mkdocs build --strict` and link checks in CI |

## Inputs needed from Tim

Listed by the phase where they are first needed.

- [x] Phase 0: decide on the commit trailer hook (D28, 2026-09-03).
- [x] Phase 0: Codex `DEVELOPERS.md` question closed on 2026-09-03, the file on disk stands.
- [x] Phase 0: Smart Parks logo received on 2026-09-03 as Illustrator, PDF and PNG in `LOGO_Smartparks_Typo/` (gitignored). SVGs derived from the PDF in `services/frontend/src/assets/brand/`. The wide variant is composed from the delivered emblem and wordmark; confirm with Smart Parks before public use. Colours #52735E and #90AE9B confirmed.
- [ ] Phase 3: recorded OpenCollar uplinks (ChirpStack, KPN or LORIOT exports) and links to the public Smart Parks decoder and protocol repositories.
- [ ] Phase 3: confirmation which EarthRanger icons may be reused and under which licence.
- [ ] Phase 7: KPN/ThingPark and LORIOT test accounts, a dev VM (Ubuntu 24.04) and a domain.
- [ ] Phase 8: Gundi connection and EarthRanger test site, an AddaxAI Connect dev server API token, a Traccar test instance or account.
- [ ] Phase 11: Cloudloop test account and an OpenCollar with BLE for WebBLE work.
- [ ] Phase 13: WildlifeNL, FerusTracker and Movebank API access.

## Session log

### 2026-09-03

- Read the concept architecture (draft v16) and the AddaxAI Connect repository (`/home/tim/apps/AddaxAI-Connect`, v0.9.0 plus 57 commits) for patterns.
- Copied `CONVENTIONS.md` verbatim. Wrote `DEVELOPERS.md`, `.gitignore`, this plan. Removed the committed `Zone.Identifier` file.
- Asked 24 setup questions; answers recorded in the decisions table. Tim chose from scratch over copying code (D1), Gundi over the direct EarthRanger API (D15), and polling over a webhook for AddaxAI Connect (D16). All other recommendations accepted.
- Next: compare with the Codex plan, then start the phase 0 skeleton.

### 2026-09-03, plan merge (Claude)

- Compared `PROJECT_PLAN_CLAUDE.md` (15 delivery-ordered phases, 180 items) with `PROJECT_PLAN_CODEX.md` (25 thematic phases, 438 items). Tim resolved the conflicts: from scratch with a reuse audit, TimescaleDB from migration 1, Claude's order as the spine, one shared `PROJECT_PLAN.md`. Both originals removed.
- Taken from the Codex plan: the reuse audit as a reading step, the product principles review checklist, the schema versioning ADR, `processing_status` on source events, route guards and empty states in the shell, the capability inspector, access control and provenance checks in the definition of done, two risks, and the extra demonstrator steps (alert acknowledged, device reassignment preserving history, one command).
- Not taken from the Codex plan: eleven ADRs before any code (five foundational ones in phase 0 instead), observability and scalability as late standalone phases (they stay in phases 1 to 4 as the architecture requires), the demonstrator after backup, curation and MCP (it stays at phase 8 as v1.0.0), and a definition of done that allows tests to be skipped.
- Codex decisions folded in: resolved project and entity ids persisted on canonical rows (D27), `REQUEST_STATUS` as the first command (phase 6 keeps RESET as well).
- Open: whether Codex's `DEVELOPERS.md` was overwritten by the Claude version (see inputs needed).
- Next: phase 0 in order, starting with README and contributor files, then the reuse audit.

### 2026-09-03, phase 0 (Claude)

- Tim decided: strip commit trailers (D28), the Codex `DEVELOPERS.md` question is closed, the whole of phase 0 in one session, logo delivered in `LOGO_Smartparks_Typo/` (Illustrator, PDF, PNG; no SVG). Three SVGs were extracted from the vector PDF: stacked, mark and a composed wide variant.
- Dev machine setup: `uv` installed in `~/.local/bin`, Node 24 through nvm, Docker Desktop WSL integration switched on by Tim. `make` is not installed, so the task runner is `scripts/dev.sh`.
- Reuse audit done with three parallel read-only passes over AddaxAI Connect (backend, tooling and deployment, frontend). Result in `docs/architecture/addaxai-connect-reuse-audit.md`. Main findings: no lockfile, linters, changelog or database tests there; Redis lists without acknowledgement; the commit hook exists but nothing installs it; forms use `useState` although React Hook Form is installed. The Ansible tree, backup interlocks and `verify-server.sh` are the parts to mirror closely.
- Built: uv workspace with exact pins (FastAPI 0.141.1, SQLAlchemy 2.0.52, Pydantic 2.13.5, redis-py 8.1.0, ruff 0.16.5, mypy 2.3.1, pytest 9.1.1), `shared` (config, database, logger, version), `protect_api` (health with three concurrent dependency checks, request id middleware, `/api/version`), tests (unit and integration), compose stack (TimescaleDB pg17.10, Redis 7.4, MinIO pinned, ChirpStack 4.19.1 profile with gateway bridge, Mosquitto and REST API), frontend (Vite 8, React 19, TypeScript 6, Tailwind 4, shadcn/ui on Radix, React Router 8, TanStack Query 5, Zustand 5, RHF 7, Zod 4, MapLibre 6, ECharts 6, Vitest 4, ESLint 10), nginx image with immutable assets, no-cache index, gzip and security headers, MkDocs site with six ADRs, CI workflow with a Python matrix, frontend, docs and compose jobs, Dependabot security-only.
- Verified locally: ruff, mypy strict, 9 python tests (3 integration against the running stack), frontend lint, type check, build and 2 tests, `docker compose up` with `/api/health` reporting database, Redis and MinIO OK, frontend on :3000 serving the placeholder and proxying `/api/version`, `mkdocs build --strict`.
- Decisions taken without a table entry: MkDocs stays on 1.x (`mkdocs<2`; MkDocs 2 removes the plugin system), API path versioning `/api/v1` from phase 1 (ADR 0006), frontend reads the root `.env` so there is one env file, shadcn `components.json` written by hand because the new CLI preset prompt cannot run non-interactively, uvicorn access logs not yet routed through the structured logger.
- Committed as 9c60e34 and pushed to SmartParksOrg/smartparks-protect. CI green on the first run: python (shared), python (api), frontend, docs, compose. Phase 0 exit criteria met.
- Next: phase 1 in order, starting with Alembic and migration 0001.

### 2026-09-03, phase 1 (Claude)

- Tim decided D29 (`/api/v1` now), D30 (one-shot `protect-migrate` compose service), D31 (UUID for domain objects, bigint for time series), whole phase in one session.
- Built the schema: 32 tables in migration 0001 (autogenerated draft, then hand edited for extensions, five hypertables, columnstore compression after 7 days, 730 day retention on source events). `btree_gist` is needed for the UUID exclusion constraints. Enumerations are text plus check constraint from `shared/enums.py`. The Alembic environment ignores TimescaleDB's own time indexes so `alembic check` reports no drift.
- Built `shared/trace.py` (Tracer, ApplicationError, compact mode), `shared/domain/assignments.py`, `shared/timeutil.py` (naive datetimes raise), `shared/permissions.py`, `shared/secrets.py` (Fernet for data source credentials).
- Built the API: FastAPI-Users auth with invitation-only registration and the `iat` versus `password_changed_at` strategy, mailer with the development guard, RBAC dependencies returning a `ProjectContext`, audit writer, bounded pagination with a guard test, and routers for projects, members, invitations, admin, entity types, entities, features, entity assignments, device types, devices, project assignments, handover, identities, CSV import, data sources, metrics. 46 paths.
- Tests: 41, of which 38 run against the migrated test database (created, upgraded, downgraded and dropped per run). Role matrix, phase 1 scenario, handover with historical access, import all-or-nothing, credentials write-only, cursor pagination, trace and attribution tests.
- Docs: domain model, data model, permissions, ADRs 0007 to 0010. `DEVELOPERS.md` describes migrations, auth, API conventions.
- Not done on purpose: BRIN indexes wait for the phase 4 benchmark; uvicorn access logs are still not routed through the structured logger; the frontend is untouched (phase 3).
- Not committed. Tim reviews and commits.
- Next: phase 2 in order, starting with `shared/bus.py`.

### 2026-09-03, phase 2 (Claude)

- Tim decided D32 (payloads above 64 KB to MinIO), D33 (approximate MAXLEN trimming), D34 (per-source bearer token for webhooks), whole phase in one session.
- Built `shared/bus.py` (Redis Streams, consumer groups, backoff re-delivery, dead letters, pending reclaim, heartbeats, schema version check, trimming) and `shared/worker.py`; eight bus tests against the real Redis. Tests now use Redis database 1, flushed per session.
- Built the connectivity contract (`Adapter`, `EventConnector`, `CommandConnector`, `ManagementConnector`, `InboundMessage`, `AdapterCapabilities`), transports (MQTT with reconnect, polling, websocket, HTTP token helpers), generic HTTP and generic MQTT adapters, the driver contract with decoded record types and canonical keys, the generic JSON driver, both registries.
- Built `shared/ingest.py` (identity resolution, out-of-line payloads, compact trace, publish after commit), the API webhook endpoint with per-source tokens (returned once, rotatable), the ingest service (connector runner re-reading data sources every minute), the decoder service (driver selection, decode, dedup with `source_deliveries`, attribution at canonical time, current state, domain events), migration 0002, `Tracer.resume`.
- Needs Attention API: summary with worker heartbeats and dead-letter counts, unknown identities, create device or link, ignore, reprocess, failed source events, dead letters retry and resolve. Read endpoints for positions per project (bounded by time window and limit), source event detail with deliveries, trace detail with steps.
- One Docker image for every Python service (`docker/python.Dockerfile`), compose services `ingest` and `decoder`, CI matrix extended with `decoder`. `protect_api.bootstrap` creates the invitation for the first server admin (`scripts/dev.sh bootstrap-admin`).
- Docs: processing pipeline, timestamps and deduplication, driver interface, adapter interface, ADR 0011; skeletons in `examples/`.
- Adapter default time field is `received_at`, not `time`, so the platform's receive time and the device's own time never collide.
- Data sources with an unregistered adapter key are rejected (422); the phase 1 tests were changed to the generic adapters.
- 68 tests pass. Not committed. Tim reviews and commits.
- Next: phase 3 in order, starting with the ChirpStack adapter.

### 2026-09-03, phase 3 (Claude)

- Tim decided D35 (OpenCollar from the public repositories), D36 (Lucide plus own silhouettes), D37 (OpenFreeMap), backend first then frontend; the frontend followed in the same session while the protocol research ran.
- CI fix from phase 2 (landed after the v0.1.0 tag, see below): MinIO buckets are created on first use, so CI needs no bucket setup.
- ChirpStack adapter (events, gateway receptions, identity attributes for deep links, REST management, HTTP integration), compose profile fixed (the gateway bridge needs a literal broker host), bootstrap script that mints a ChirpStack API key from the database and secret, simulator publishing integration events. Verified live: bootstrap, ingest connects, simulated uplinks become positions with receptions.
- Drivers get the LoRaWAN frame and port; network-level status and join events need no driver. Metric seeds in migration 0003.
- APIs: current state as GeoJSON and vector tiles, tracks with uniform decimation, WebSocket fan-out per API process, traffic, trace search, system health, deep links from templates and identity attributes.
- OpenCollar Edge driver from a research pass over twenty public repositories (the research document is in `docs/devices/`), golden tests over the wiki examples, ports 2, 4, 12, 13, 14, 16, 18, 19, 20, 29, 31, 3, 30. A port 16 resend and a port 29 flash log record map to the same canonical key as the original fix. Recorded live uplinks are still wanted (input list).
- Frontend: typed client, generated OpenAPI types with a CI freshness check, Zustand stores, router with guards, app shell, icon registry with twenty starter silhouettes, live map with clustering and marker families, entities, devices, device detail with provenance and links, traffic viewer, trace explorer, members, features with drawing, project settings, Needs Attention, health, projects, users, devices with handover, data sources with webhook tokens, catalogues, audit. Screenshot sweep derives routes from the router; all 3 viewports times 31 routes clean after the nginx WebSocket fix.
- Live map fixes found with the sweep and a screenshot script: MapLibre 6 ships its worker as a module, so Vite bundles it (`?worker&url`, `setWorkerUrl`) and nginx serves `.mjs` as JavaScript; MapLibre's own CSS sets `position: relative` on the container, so the map page uses `absolute!`; symbol layers use Noto Sans, the only glyphs OpenFreeMap serves. `/api` in nginx now passes WebSocket upgrades.
- Tim installed Chromium's system libraries (`libnspr4 libnss3 libasound2t64`), so `npm run sweep` and `scripts/dev.sh sweep` run natively; the Playwright image stays documented as a fallback with `--user` so it leaves no root-owned files.
- Known gaps for later phases: uvicorn access logs are unstructured; the sweep has no assertions yet (`@playwright/test` smoke when CI gets a browser); satellite base map behind a key; ChirpStack command connector in phase 6.
- D38 recorded: external deep links built as proposed in architecture 32.
- CI on the release commit failed twice: `.gitignore` had `data/`, which hid `src/components/data/DataTable.tsx` from git, so the frontend build failed on a clean checkout (rule is now `/data/`); the decoder test job failed because the CI MinIO has no `uploads` bucket (the on-demand creation noted in phase 2 had never been written); pytest steps now print failures as workflow annotations because the logs are not readable without a token (no `gh` on this machine). Fixed on main after the tag; CI is green on main at `49d8098` (seven jobs). Open for Tim: move the `v0.1.0` tag to the fixed commit, or tag `v0.1.1` (recommended, the tag was already public).
- 100 python tests, 2 frontend tests, lint and types clean, docs strict, sweep 31 routes times 3 viewports clean. Committed and tagged v0.1.0 on Tim's instruction.
- Next session: run the quick start on a clean checkout (phase 3 exit criterion on a fresh machine), then phase 4 starting with the aggregation API.
- Decisions to ask Tim when phase 4 starts: where the export worker runs (proposed: `services/export` in the shared Python image, own compose service); XLSX writer (proposed: openpyxl write-only mode); resolution selection rule for aggregates (proposed: pick the coarsest `time_bucket` that keeps a series at or under 5,000 points); saved views storage (proposed: `saved_views` table per project, JSONB filter). Everything phase 4 needs is in place: TimescaleDB hypertables, MinIO, ECharts installed, the Redis bus and worker base class. Inputs still wanted: recorded live OpenCollar uplinks, confirmation of the composed wide logo.
