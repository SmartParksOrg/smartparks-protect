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
| Active phase | Phase 14 complete except the v2.0.0 release (everything committed through 5ede00a, CI green; the data source form per channel with switches, migration 0015, is built and awaits commit). Live verification started on 2026-09-05 with Tim's ChirpStack (chirpstack-dev4): uplinks of collar SP051307 flow over the HTTP integration; the gRPC API direction waits for a `grpc_pass` location on that nginx and a tenant API key |
| Latest release | v0.6.0 (2026-09-04): phases 7, 8 and 9; phases 10 to 13 and the deployment fixes unreleased |
| Last session | 2026-09-05 |
| Next item | Finish the ChirpStack live check (nginx `grpc_pass`, tenant API key, `api_url` grpcs://chirpstack-dev4.smartparks.org:443, then Test connection, Sync devices, Request status on SP051307), then v2.0.0 on Tim's word (a docs-only deployment lands on v0.6.0 and fails the security check until 2.0 is tagged); the ChatGPT half of the phase 9 check waits for a Pro or Business account; the live items of phases 7, 8, 11 and 13 follow the accounts, a collar with BLE, a The Things Stack application, a ThingPark deployment and an EarthRanger site |
| Blockers | Live verification: no KPN, LORIOT, Netmore, akenza, Gundi, AddaxAI Connect, Traccar or Cloudloop account in use yet, and no OpenCollar with BLE at hand; deep link paths for Netmore, akenza, Traccar, AddaxAI Connect and Cloudloop are guesses until seen live. The dev server (dev-protect.smartparks.org, DigitalOcean) and the backup bucket exist since 2026-09-04 |

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
| D39 | Export worker | Own `services/export` package in the shared Python image, compose service `protect-export`, same worker base class as decoder and ingest | Isolated from live decoding, one image to build. Decided by Tim on 2026-09-03. |
| D40 | XLSX writer | openpyxl in write-only mode; the Excel row limit is enforced by splitting into sheets, never silently truncated | Pure Python, MIT, streams rows. Decided by Tim on 2026-09-03. |
| D41 | Aggregate resolution | Fixed ladder 1 s, 10 s, 1 min, 5 min, 15 min, 1 h, 6 h, 1 d, 7 d; pick the smallest bucket with at most 5,000 buckets over the range; user override allowed | Deterministic, cache friendly, matches continuous aggregates later. Decided by Tim on 2026-09-03. |
| D42 | Saved views | `saved_views` table per project with the filter and layout as JSONB and a schema version | Simple, versioned, no new service. Recorded by Claude on 2026-09-03. |
| D43 | Telegram targets | One bot per installation (`TELEGRAM_BOT_TOKEN`); chats link to a target by sending `/start <code>` to the bot, the automation service polls the bot | Same pattern as AddaxAI Connect, one bot to create, no tokens per project. Decided by Tim on 2026-09-04. |
| D44 | Phase 5 services | Two services: `protect-rules` (evaluation, scheduler, system checks) and `protect-automation` (actions, email and Telegram delivery in-process, bot poller) | A slow SMTP server never stalls evaluation; two containers, not four. Decided by Tim on 2026-09-04. |
| D45 | Rule constructs in phase 5 | Threshold, spatial enter/exit/inside/outside, speed as a derived metric, FOR, no-data, window aggregates; `near`, `dwell`, `crossed`, `baseline`, `correlation` and `event_chain` reserved in the schema until phase 13 | Covers the four template rules and the immobility example; reserved types can be written now but not enabled. Decided by Tim on 2026-09-04. |
| D46 | Alert lifecycle permission | `alerts:write` (acknowledge, resolve) is held by project viewers as well as admins | Rangers are viewers and acknowledging is their daily workflow; read-only stays read-only for everything else. Recorded by Claude on 2026-09-04, easy to revert in `shared/permissions.py`. |
| D47 | System alerts | System findings (stale worker, dead letters, consumer lag) are events with `project_id` null and an alert that resolves itself when the finding clears; server-level automations and targets (project null) deliver them | One event and alert path for everything, no second notification mechanism; server admins see them under System alerts. Recorded by Claude on 2026-09-04. |
| D49 | Control action schema | Actions are Python dataclasses in the driver with a `schema_version`, parameters as Pydantic models exported as JSON schema; commands store the version they were created with; no database table for definitions | Encoding is code; a second source of truth would drift. ADR 0013. Decided by Tim on 2026-09-04. |
| D50 | ChirpStack downlinks | The REST API device queue, the same client and token as the management connector | No new dependency; `txack` and `ack` carry the queue item id back. Decided by Tim on 2026-09-04. |
| D51 | Device confirmation | An action may declare an interpreter that recognises the device's answer in later decoded records; without one the lifecycle ends at the last stage the network reports | Nothing is fabricated (architecture 17.4); OpenCollar confirms status and position requests and resets. Decided by Tim on 2026-09-04. |
| D52 | Command routing and audit | The route is the most recently seen identity on an enabled data source whose adapter can send and whose capabilities fit; a refused submission is stored as a failed command; commands have an audit-class trace and expire after the action's expiry | The attempt stays in the history for audit; a device with two networks uses the one that heard it last. Recorded by Claude on 2026-09-04. |
| D53 | KPN/ThingPark integration | ThingPark HTTP application server push to the source's webhook with the bearer token; downlinks through the ThingPark downlink API in `token` (AS id, time, SHA-256 token) or `bearer` mode | No broker to run, works with the public KPN network. Built from the ThingPark documentation; the live run confirms the downlink security scheme. Decided by Tim on 2026-09-04. |
| D54 | LORIOT integration | The application's websocket output for events; downlinks as `tx` frames over a short-lived connection to the same output; the HTTP output accepted as well | One credential, bidirectional, reconnects like the MQTT transport. Built from the LORIOT documentation. Decided by Tim on 2026-09-04. |
| D55 | Phase 7 without accounts | Adapters, guard test, Ansible, scripts and runbooks are built from public documentation with invented fixtures; the items that need live networks or a server stay open until Tim provides access | Work proceeds; recorded payloads replace the fixtures and the live run closes the items. Decided by Tim on 2026-09-04. |
| D56 | Adapter metadata from the API | `GET /data-sources/adapters` describes every adapter (push, commands, channel, config schema and example, credential fields, setup hint); the frontend builds the data source form from it and names no provider; a guard test enforces the boundary in backend and frontend | Architecture principle 2 made mechanical. Recorded by Claude on 2026-09-04. |
| D57 | Netmore | A third production LoRaWAN network, added on Tim's request on 2026-09-04: events in Netmore's export format over HTTP push (static `Authorization` header) or the Netmore MQTT broker; downlinks through the Netmore Connect REST API with an API key | Built from the published documentation and the Connect OpenAPI document; the decoded export formats are refused because they carry no raw frame. Live verification pending. |
| D58 | Netmore platforms | One adapter with a `platform` setting: `lorawan_portal` (portal.blink.services; login token, sensor downlink queue, clear) or `connect` (API key); events share the export format | Tim's account is on the LoRaWAN Portal; both are offered without duplicating the parser. Decided by Tim on 2026-09-04. |
| D59 | akenza.io | Webhook output connector for events (the whole sample; the device type must keep `payloadHex`), REST `POST /v3/devices/{id}/downlink` with `{"raw": true, "loraDownlink": {...}}` and `x-api-key`; the akenza device id is the external identity, the DevEUI an attribute | akenza addresses devices by its own id, so downlinks need it. Built from docs.akenza.io and the published API collection. Decided by Tim on 2026-09-04. |
| D60 | Integration delivery idempotency | One `integration_deliveries` row per (integration, object type, object id, object version) with a unique index; positions and measurements are version 1, events carry a version curation can bump; backfill inserts in batches and skips existing keys | An object is never sent twice to the same integration, replays and backfills included. Decided by Tim on 2026-09-04 (open decision from architecture 32 closed). |
| D61 | Integration retries | Table-driven: deliveries carry `next_attempt_at` and `attempts`; the integration service polls due rows and retries with exponential backoff from 30 s to 6 h, up to 30 attempts, then marks failed with manual retry; the bus acknowledges at once | A target outage of hours never fills the stream or blocks other consumers (architecture 18). Decided by Tim on 2026-09-04. |
| D62 | Gundi identities | Observations use the Smart Parks entity id as Gundi `source`, the entity name as `source_name`, the subject type mapped per integration from the entity type; the device and data source travel in `additional`; event types live in the `smartparks_protect_` namespace | The EarthRanger track stays continuous across collar swaps. Decided by Tim on 2026-09-04. |
| D63 | AddaxAI Connect authentication | The data source stores the email and password of a dedicated AddaxAI Connect viewer account; the connector logs in, caches the JWT and logs in again on 401 or before expiry | AddaxAI Connect has only user login today; an API key mode is added when it grows one. Decided by Tim on 2026-09-04. |
| D64 | AddaxAI Connect cursor | Poll the image list newest first with a captured-at cursor; a rescan over an overlap window (default 7 days) runs daily and a manual "rescan from date" covers older bulk imports; idempotency on the image uuid | Bulk SD-card imports arrive with old capture times and the list has no ingest-time filter. Decided by Tim on 2026-09-04. |
| D65 | Traccar | Session login (`POST /api/session`), the `/api/socket` websocket for positions, events and device status with reconnect, `GET /api/positions` on every connect, `GET /api/devices` for management, `POST /api/commands/send` as the command proof of concept, deep links to the Traccar web UI | Real time with Traccar's own event stream; polling would lose geofence and alarm events. Built from the Traccar OpenAPI document. Decided by Tim on 2026-09-04. |
| D66 | Gateway registry | Server-level `gateways` table unique on (data source, provider gateway id) with name, location, state, last seen, statistics and provider diagnostics in attributes; rows come from receptions, gateway events and a sync against the platform; a project sees the gateways that received its devices | Matches "devices are server-level physical objects"; public-network gateways belong to nobody. Decided by Tim on 2026-09-04. |
| D67 | Phase 8 release | Everything buildable from documentation and the local stack ships as v0.6.0 once CI is green; v1.0.0 waits for the section 33 demonstration with real accounts | The demonstration needs a second LoRaWAN network, an EarthRanger site, an AddaxAI Connect account and a Traccar instance. Decided by Tim on 2026-09-04. |
| D68 | MCP authorization server | The API hosts OAuth 2.1 with the MCP SDK's authorize, token, registration and revocation handlers under `/api/v1/oauth`, metadata at the well-known path of the public URL, a database-backed provider, consent as a frontend page | One authorization model and audit trail; the MCP service stays database-free (27.1); the SDK's handlers carry PKCE and the registration rules. ADR 0015. Decided by Tim on 2026-09-04. |
| D69 | MCP client registration | Client id metadata documents (fetched from the client id URL, self-referential, redirect URIs on the client's host or loopback) and dynamic registration (HTTPS or loopback redirect URIs); loopback URIs match with the port ignored | Claude and ChatGPT prefer metadata documents and fall back to dynamic registration; Claude Code and the inspector use loopback ports. Recorded by Claude on 2026-09-04. |
| D70 | MCP access tokens | JWTs signed with `JWT_SECRET`, audience the MCP URL, subject the user, `client_id` and `scope` claims, one hour; refresh tokens hashed and rotated, thirty days; the MCP service verifies locally and calls the API with the same bearer, which the API admits read-only within the scopes and audits per request | Stateless and no introspection round trip; the API is the issuer, so admitting its own audience under a stricter policy is deliberate, not token passthrough. Decided by Tim on 2026-09-04. |
| D71 | MCP tool set of the proof of concept | The eight tools of the plan plus `list_metrics` and `search_traces` (needed by the prompts), ChatGPT's `search` and `fetch`, `smartparks://` resources for projects, entities, events, devices and traces, two prompts; entities and events carry the project in their URI | ChatGPT deep research requires `search` and `fetch`; the API is project scoped. Decided by Tim on 2026-09-04. |
| D72 | Database backups | pgBackRest inside the database container (shipped by the TimescaleDB image): continuous WAL archiving, weekly full and hourly incremental backups to an encrypted S3-compatible repository at another provider, retention in full generations; a wrapper handles the empty options compose cannot omit and the disabled state | Point-in-time recovery from the first production server, nothing to install. ADR 0016. Decided by Tim on 2026-09-04. |
| D73 | Object backups | `mc mirror` of every MinIO bucket to the backup bucket, incremental, never deleting on the remote, plus a daily check of referenced objects | Works with any S3-compatible provider; MinIO replication would need MinIO on both ends. Decided by Tim on 2026-09-04. |
| D74 | Backup jobs and status | Host cron from Ansible runs `scripts/backup.sh` and `scripts/restore-verify.sh`; every run is a `backup_runs` row; the Backup and recovery page and `SYSTEM_BACKUP` alerts derive from the rows and `pg_stat_archiver`; the restore test restores into a second compose project on the same host | No container with the Docker socket; a job that never ran is as visible as one that failed. Decided by Tim on 2026-09-04. |
| D75 | Technical telemetry | OpenTelemetry in every service, exporting over OTLP/HTTP only when an endpoint is configured; the `observability` compose profile runs Grafana with a collector; spans carry the processing trace id | One standard, off by default, joins with the application traces. Decided by Tim on 2026-09-04. |
| D76 | WebBLE implementation | Our own implementation of the OpenCollar BLE protocol in the frontend (Nordic UART service, frames `[port][msg_id][len][data]`, flash logs paged with `cmd_flash_get_from_head`): connect, status, settings read and write, commands, flash log count, download, erase and sync. The public GPL-3.0 app is a behavioural reference only; no code is copied into this MIT repository | Same product, one licence; the protocol is documented in the research document. Decided by Tim on 2026-09-04. |
| D77 | Raw log files and BLE syncs | Every line of a raw log file and every BLE notification frame is one SourceEvent (channel `log_file` or `webble`) under a built-in data source per channel, grouped by a `device_log_files` row; the file lives in the `device-log-files` bucket; the port 29 record parser decodes the frames; re-decode reprocesses the frames; a BLE sync is stored as a log file of channel `webble` so both share status, counts, download and re-decode | Provenance per frame with the same pipeline as LoRaWAN, and one worker for both paths. Decided by Tim on 2026-09-04. |
| D78 | Cloudloop | Lingo JSON webhook at the source's URL with the token as a query parameter (Cloudloop sends no authentication header) and an optional allow-list of its two source addresses; the IMEI is the device identity with the Cloudloop thing id as an attribute; `Data/GetThings` for management sync, `Data/DoSendSbdMessage` for commands (satellite frame `[port][msg_id][len][data]`), `Platform/Ping` as the connection test; the pull endpoints only for a manual catch-up | Push is Cloudloop's recommended path and has retries for twelve hours; pull would add latency and calls. Decided by Tim on 2026-09-04. |
| D79 | Command routes | The control dialog lists every route (each enabled source holding an identity of the device with a command connector, plus WebBLE while the device is connected in this browser) with the most recently seen route preselected; WebBLE is never chosen automatically; a WebBLE command is created on the backend, written by the browser and its confirmation arrives through the synced frames, so lifecycle, audit and trace are the same as over a network | Architecture 25.5 keeps the action with the driver and the route separate. Decided by Tim on 2026-09-04. |
| D80 | Effective value layer | Nullable overlay columns on `positions` and `measurements` (`curated_time`, `curated_geom`, `curated_value_num`, `valid`, `curated_fields`, `curation_version`); null means the original applies, so the large tables need no backfill; every reader (map, analytics, rules, exports, integrations, current state) uses the effective value through one shared expression; the original stays in the row and the history in `data_corrections`. Curatable: position time, coordinates and validity; measurement time, numeric value and validity | Originals never change and the time column that partitions the hypertable is never rewritten (architecture 28.1, 28.3). Decided by Tim on 2026-09-04. |
| D81 | Curation approval | Project setting `curation_requires_approval`, off by default: off, `data:curate` applies single corrections at once and bulk jobs need `data:curate_bulk` plus a preview; on, corrections and jobs stay `PENDING` until a different user with `data:approve` approves; reverting needs `data:revert` | Architecture 28.11 makes the two-step workflow optional per project. Decided by Tim on 2026-09-04. |
| D82 | Recomputation after curation | Timestamp corrections rerun project and entity attribution; device and entity current state are recomputed; analytics aggregates are computed live, so nothing is cached; outbound deliveries of corrected records are flagged stale for review with a resend that bumps the object version; rule re-evaluation is a per-job option that runs the existing rule replay over the affected window | Architecture 28.8 to 28.10 ask for controlled recomputation and reviewed retransmission, not automatic resends. Decided by Tim on 2026-09-04. |
| D83 | Export views | Export parameter `view` (`effective`, default, or `original`) for positions and measurements plus `curation_metadata` adding the columns of architecture 28.13; the raw view is the source events dataset; any project member may export either view | Scientific reproducibility needs the original next to the effective value. Decided by Tim on 2026-09-04. |
| D84 | Phase 13 scope | The Things Stack and Actility ThingPark adapters, a direct EarthRanger API connector, Movebank as an export format, project SVG icon upload, project dashboards and MCP write tools now; WildlifeNL and FerusTracker (no public API found at the time) wait for access | Everything chosen builds from published documentation; the two deferred platforms could not. Decided by Tim on 2026-09-04. Amended the same day: WildlifeNL's API turned out to be open source (see D88); FerusTracker stays deferred. |
| D85 | Movebank | An export dataset in Movebank's import format (reference data per animal, tag and deployment plus the event rows with timestamp, location and sensor attributes) instead of a push connector | Movebank ingests through arranged live feeds or file import only; the export fits its custom tabular import. Decided by Tim on 2026-09-04. |
| D86 | Project dashboards | Dashboards per project, shared, stored as a grid layout of tiles; tiles are saved Data Explorer views and built-in tiles (latest positions map, active alerts, recent events, entity status counts) with a size and an order; no free-form canvas | Architecture 30.2: not a Grafana clone. Decided by Tim on 2026-09-04. |
| D87 | MCP write tools | `create_event`, `acknowledge_alert`, `request_device_status`, `request_device_position` and `confirm_action`; a server-level AI action policy per class (allowed, confirmation, privileged, disabled) edited by server admins; a two-step confirmation flow where the tool returns a confirmation token that `confirm_action` executes; scopes `events:write`, `alerts:write`, `devices:control`; high-impact control disabled by default | Architecture 27.4 and 27.6: the same frameworks as people use, no alternative control path. Decided by Tim on 2026-09-04. |
| D88 | WildlifeNL connector | Built from the platform's open source API (github.com/UtrechtUniversity/wildlifenl): positions and temperature measurements as borne sensor readings, `SPECIES_DETECTION` events as detections with the species resolved by name, other events skipped; the sensor id is the device's primary identity by default, configurable to the device name or the entity id | The API is the published contract; WildlifeNL links readings to animals through deployments a herd manager registers by sensor id, so the value printed on the collar is the natural key. Decided by Tim on 2026-09-04. |
| D89 | FerusTracker connector | Built from the Node-RED flow that feeds ferustracker.nl today: the same unauthenticated document (`devEUI`, `fPort`, `tags.payloadType`, `objectJSON` with the collar decoder's field names, `provider`, `site`) rendered from canonical positions and measurements, the payload type per device type, plus a top-level `time`; events skipped | FerusTracker publishes no API; the flow is the only contract, and reproducing it lets the platform keep working unchanged when the flow is retired. Decided by Claude on 2026-09-04 after Tim shared the flow; to confirm live. |
| D90 | CRA IoT adapter | České Radiokomunikace's platform as a push source: the HTTP endpoint's envelope with the LORIOT-shaped message (`gw` as the uplink, `rx` ignored unless configured, `geo` as a location), downlinks through `POST /lora/devices/{EUI}/down/messages` and the device list through `GET /lora/devices`, with tokens from the CRA single sign-on password grant | Tim asked for it on 2026-09-04; the platform's documentation and Swagger are public and its message is LORIOT's, so the parser shares LORIOT's field reading. Decided by Claude on 2026-09-04; to confirm live. |
| D91 | Full-scale benchmark | The phase 14 benchmark runs at reduced scale (0.2 of the envelope: 50 million positions, 200 million measurements) on the dev server, with the generator writing in time order so chunks compress behind the write frontier; the full envelope waits for a production-sized server and is documented as extrapolated | The dev server has 146 GB of disk and 8 GB of memory; a temporary 32 GB droplet with a 1 TB volume was offered and declined. Decided by Tim on 2026-09-04. |
| D92 | Tenancy revisited (D21) | Project isolation stays the security boundary; organizations become a visible, optional grouping of projects for server admins (list, filter, assignment) without an enforced boundary; enforcement is reconsidered when two organizations share one server | No deployment shares a server between organizations yet; grouping gives the admin pages structure without a second RBAC tier. Decided by Tim on 2026-09-04. |
| D93 | Multi-language UI | The frontend becomes translation-ready: an i18n layer, every UI string in an English catalogue, a lint rule against hard-coded text, language detection and a switch; English is the only shipped language, translations come after 2.0 | The mechanical extraction is best done once before 2.0; a second language is a content job for native speakers. Decided by Tim on 2026-09-04. |
| D94 | Security audit scope | A generated access matrix test over every API operation and role, MCP scope tests, a credential handling review, dependency audits in CI failing on high severity, application-level throttling of login, password reset, registration, token and webhook calls that holds without nginx, and a written audit report with findings and fixes | Production across parks needs the guarantees tested, not assumed; nginx limits protect deployed servers only. Decided by Tim on 2026-09-04. |
| D48 | Firing semantics | Edge-triggered: a rule fires when its condition becomes true and, while it stays true, again only after the cooldown; FOR makes the condition count once it has held that long | A battery rule sends one event per drop and one reminder per cooldown, never one per measurement. Recorded by Claude on 2026-09-04. |

### Open decisions from architecture section 32

These are not decided yet. A proposed default is given so work can start; each is confirmed or changed when its phase begins.

- [x] **External deep links.** Decided on 2026-09-03: built as proposed, see D38.
- [x] **Control action schema versioning.** Decided on 2026-09-04: built as proposed, see D49 and ADR 0013.
- [x] **Integration delivery idempotency.** Decided on 2026-09-04: built as proposed, see D60 and ADR 0014.
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
| 7 Connectivity layer (ChirpStack, KPN, LORIOT, Netmore, TTS, Actility, Traccar, Cloudloop, AddaxAI) | 2, 3, 7, 8, 11, 13 |
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
│           └── adapters/    # chirpstack, kpn_thingpark, loriot, tts, actility, cra_iot, traccar, cloudloop, addaxai_connect
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

- [x] Aggregation API (2026-09-03, `shared/analytics.py`, `/analytics/series`, `/rows`, `/metrics`, saved views): filters by project, entities, devices, metrics, data source and time range; automatic resolution selection targeting 2,000-5,000 samples per series with user override; `time_bucket` aggregates mean, min, max, median, sum, count, first, last; long and wide layouts; drill-down from a bucket to normalized rows and to source events.
- [x] Continuous aggregates for hourly and daily buckets when benchmarks show repeated expensive queries. Not needed at the tested scale (raw `time_bucket` scans answer in tens of milliseconds, see `docs/architecture/scalability.md`); revisit with the 1/10 run.
- [x] Data Explorer UI (2026-09-03; sort, column selection and grouping are the shared table's, virtualization follows when a screen needs it): filter builder, virtualized table with sort, filter, column selection and grouping, ECharts line, scatter, bar, histogram and state timeline, multi-series comparison across entities and devices, timezone selection, drill-down, saved views per project.
- [x] Export jobs (2026-09-03, 1.34 million rows CSV in 45 s with the export container flat at about 90 MiB): `export_jobs` table, worker in `services/export`, streaming CSV, XLSX (with Excel row limits enforced), JSON, GeoJSON and GPX for tracks, data level selection (raw, decoded, normalized, aggregated), metadata columns, recorded filters and units for reproducibility, small exports returned directly, large ones as MinIO objects with a download link. Target: 10 million rows CSV without memory growth.
- [x] Exports UI (2026-09-03): job list with progress, download, reproduce.
- [x] `scripts/benchmark/generate.py` (2026-09-03): synthetic dataset generator scalable up to the reference envelope (13.9), with realistic spatial clustering and time distributions, multiple projects and data sources. `scripts/benchmark/run.py`: live map load, viewport tiles, 1-day, 30-day and 1-year tracks, Data Explorer aggregates, exports, ingest bursts. Results written to `docs/operations/benchmarks.md`.
- [x] Benchmark run at 1/10 scale on the development machine (2026-09-03: 22.4 million positions, 89.7 million measurements, 39 minutes to generate; every read path within budget; the decoder throughput is the open item, see `docs/architecture/scalability.md`). Compare against the performance budgets in 13.7. Fix what fails.
- [x] TimescaleDB decision gate (2026-09-03, confirmed): confirm or replace with native partitioning. Update ADR 0003.
- [x] Retention and compression policies verified against the benchmark dataset (2026-09-03: compression measured at 16x on measurements and 10x on positions after compressing the old chunks by hand; retention policy present on source events only, canonical rows stay by design).
- [x] Docs (2026-09-03): `docs/analytics/data-explorer.md`, `docs/analytics/export.md`, `docs/architecture/scalability.md`.

**Exit criteria.** Benchmark results recorded and within budget at the tested scale, a 1 million row export streams with flat memory, the Timescale decision is written down. Met on 2026-09-03 at 1/10 scale, with the decoder throughput (90 events per second per process) recorded as the open performance item.

---

### Phase 5: rules, events, alerts, automations and notifications (v0.3.0)

**Goal.** The stateful rules engine with the four initial rules, events and alerts as separate objects, automations that turn events into actions, and channel-neutral notifications over email and Telegram.

**Why here.** Architecture 31 step 6: add the rule and automation interfaces with a few simple rules before advanced scientific expressions. Notifications are the first action type and are needed by later phases for integration failures, command failures and backup alerts.

**Deliverables.**

- [x] Rule schema (D9): trigger (position, measurement, state, event, schedule), condition tree (threshold, spatial ENTER/EXIT/INSIDE/OUTSIDE/NEAR/DWELL, movement, temporal FOR and COUNT, aggregation over windows, baseline, correlation, event chaining), event template (type, severity, context values), actions. Pydantic validation, JSON schema for the UI. `rules` and `rule_versions` tables; every event references the rule version. (2026-09-04; NEAR, DWELL, CROSSED, baseline, correlation and event chaining are reserved types per D45, COUNT is the window `count` aggregate)
- [x] `services/rules`: consumes domain events, keeps per-rule and per-entity state (windows, dwell timers) in Postgres, evaluates geofences with PostGIS, emits events, respects late data freshness policy (25.8), traces every evaluation compactly. (2026-09-04; geofences are evaluated with shapely on cached feature geometries, a compact trace is written per fired rule and per failure, silent evaluations write nothing; event age travels on the event for the automation freshness bound)
- [x] Rule testing: run a rule version over a historical time range by replaying canonical data, show the events it would have produced, without side effects. (2026-09-04)
- [x] Initial rules shipped as templates: geofence enter and exit, speed limit inside an area, inactivity or no data for a duration, battery threshold. (2026-09-04; plus possible immobility)
- [x] Events and alerts: event list and detail, alert lifecycle (open, acknowledged, resolved) with actor and time, alert inbox per project, event and alert markers on the map using the event marker family. (2026-09-04)
- [x] `services/automation`: automations bind event types and filters to actions; action framework with delivery tracking (status, attempts, delivered time, error, trace). Action types: notification, webhook (basic), integration forward (completed in phase 8), device command (completed in phase 6). (2026-09-04; integration and command are rejected until their phases)
- [x] Notifications: notification targets at project and organization level, email over SMTP with templates and links back to the object, Telegram bot targets with chat registration, severity-aware formatting, delivery workers with retry and dead-letter. (2026-09-04; organization level is server level, project null, per D21)
- [x] System alerts use the same path: worker down, stream lag, dead-letter growth, data source unreachable. (2026-09-04; data source unreachable has no signal yet: connectors log and restart, the ingest heartbeat covers the worker; a per-source health check comes with the production adapters in phase 7)
- [x] Rules UI: list, form builder, version history, test run with results, enable and disable. Automations UI. Notification targets UI. Events and Alerts screens. (2026-09-04)
- [x] Tests: each construct with fixtures, replay test, freshness test, delivery retry test. (2026-09-04)
- [x] Docs: `docs/rules/` (concepts, constructs, examples from 15.3 and 15.4, testing), `docs/administration/notifications.md`. ADR: rule representation. (2026-09-04, ADR 0012)

**Exit criteria.** The four template rules fire on simulated data, produce events and alerts, and deliver email and Telegram notifications with tracked status. A rule replay over the past week matches live results.

---

### Phase 6: device control through ChirpStack (v0.4.0)

**Goal.** The capability-driven Device Control Framework with the full command lifecycle, OpenCollar RESET and REQUEST_STATUS through the ChirpStack adapter, usable from the UI and from automations through one path.

**Why here.** Control needs the driver (phase 3), the trace model (phase 1) and the action framework (phase 5). Doing it on ChirpStack first means downlinks are tested locally before airtime is spent on KPN or LORIOT.

**Deliverables.**

- [x] Control action definitions per driver (architecture 17.3): key, label, description, typed parameters with validation and units, required permission, confirmation policy, required connectivity capability, encoder, result interpretation. Exported as JSON schema for the UI and rules. (2026-09-04)
- [x] `commands` and `command_executions` tables with the lifecycle states from 17.4; unsupported stages stay unknown, never fabricated. (2026-09-04)
- [x] Command path: API creates the command, driver encodes, route selection chooses the connectivity adapter from active data sources and capabilities, adapter submits, provider events update the lifecycle (ChirpStack txack and ack), device responses close the loop where the driver interprets them. Every step traced (26.7). (2026-09-04)
- [x] ChirpStack command connector: enqueue downlink, read queue state, flush. (2026-09-04)
- [x] OpenCollar encoders for RESET and REQUEST_STATUS, plus SET_GNSS_INTERVAL if the protocol fixtures allow it. (2026-09-04; plus REQUEST_POSITION)
- [x] Permissions and confirmation: `devices:control` for operational actions, `devices:control_high_impact` for reset and configuration, explicit confirmation dialog, audit entries. (2026-09-04)
- [x] Automations can invoke control actions through the same API as the UI. (2026-09-04)
- [x] UI: actions menu on the device built from capabilities with disabled reasons, command dialog with parameter form and confirmation, command history with lifecycle timeline and trace link, Control section with command list. (2026-09-04)
- [x] Tests: encoding golden tests, route selection with two data sources, lifecycle updates from provider events, permission checks. (2026-09-04; route selection is tested through the availability reasons: disabled source, missing downlink capability)
- [x] Docs: `docs/devices/device-control.md`, `docs/devices/opencollar.md` control section. ADR: control action schema versioning. (2026-09-04, ADR 0013)

**Exit criteria.** RESET issued from the UI appears in the ChirpStack downlink queue, the lifecycle shows SUBMITTED, QUEUED and TRANSMITTED from ChirpStack events, and the same action fired by an automation follows the identical path.

---

### Phase 7: production LoRaWAN networks and the dev server (v0.5.0)

**Goal.** KPN/ThingPark and LORIOT adapters with no change to domain or UI code, OpenCollar control over a second network, and a deployed dev server with Ansible.

**Why here.** Architecture 31 step 8: add KPN and LORIOT and verify that no domain or UI code needs provider-specific changes. Push integrations from public networks need a reachable HTTPS endpoint, so the dev VM arrives now (D17).

**Deliverables.**

- [x] KPN/ThingPark adapter: HTTP push event connector (uplink, downlink status where exposed), REST management where the account allows, downlink command connector, capabilities per data source, timestamps mapping, deep links, runbook with setup, authentication, uplink and downlink flow, timestamps and troubleshooting (28.7). (2026-09-04, from the ThingPark documentation with invented fixtures; no management connector, the public account exposes none; live confirmation pending)
- [x] LORIOT adapter: websocket or HTTP push event connector, downlink command connector, management where available, capabilities, deep links, runbook. (2026-09-04, from the LORIOT documentation with invented fixtures; live confirmation pending)
- [x] Netmore adapter: event connector, downlink command connector, capabilities, deep links, runbook. Added on 2026-09-04 (D57). (2026-09-04, from docs.connect.netmoregroup.com, the Blink Portal API document and the Connect OpenAPI document; HTTP push and MQTT events; downlinks, queue and clear on the LoRaWAN Portal and downlinks and clear on Connect per D58; the device deep link path is a guess to adjust on the live run; live confirmation pending)
- [x] akenza.io adapter: webhook samples, akenza device id as identity, REST downlinks, runbook. Added on 2026-09-04 (D59) from docs.akenza.io and the published API collection; live confirmation pending.
- [x] Guard test: a test asserts that no file outside `shared/connectivity/adapters/` imports or names a provider, and the frontend has no provider string outside the adapter display metadata. (2026-09-04; the frontend now has no provider string at all, it reads `GET /data-sources/adapters`)
- [ ] OpenCollar RESET or REQUEST_STATUS executed through KPN or LORIOT, proving the same action over two networks (30.1). (connectors and their tests exist; the live run waits for an account)
- [x] Ansible: roles for docker, nginx with TLS, security hardening (ufw, unattended upgrades, fail2ban on SSH, SSH keys only, sshd drift check), app deploy from a git tag, env and secrets handling with vault, `inventory.yml.example` and host vars examples. Dev server can run `main`. (2026-09-04; run against the dev server the same day, five fixes from the first runs, then fully green)
- [x] `scripts/verify-server.sh` and `scripts/security-status.sh` equivalents. (2026-09-04; both pass on the dev server)
- [ ] Dev server deployed, real collars from KPN, LORIOT, Netmore and akenza visible on the map. (dev server deployed on 2026-09-04 at dev-protect.smartparks.org; the collars wait for the accounts)
- [x] Docs: `docs/getting-started/deployment.md`, `docs/operations/update-guide.md`, `docs/integrations/kpn-thingpark/`, `docs/integrations/loriot/`. (2026-09-04; a Netmore runbook follows with its adapter)

**Exit criteria.** Live OpenCollar data from two different LoRaWAN backends shows on one map, a control action works over the second network, the dev server is reproducible from the playbook. Netmore joins as a third backend (D57).

---

### Phase 8: integrations, Traccar, gateways and the first demonstrator (v1.0.0)

**Goal.** Durable outbound integrations with EarthRanger first, the AddaxAI Connect inbound connector, a Traccar proof of concept, gateway monitoring, complete provenance links, and the section 33 demonstration.

**Why here.** Architecture 31 steps 7 and 9. Integrations need stable domain events (phase 2), rules (phase 5) and a public endpoint (phase 7). Traccar proves the platform is not LoRaWAN-only before the core abstractions are declared done.

**Deliverables.**

- [x] Integration framework in `services/integration`: `integrations` (per project, connector key, credentials, filters for entities, devices, event types, measurements, historical data) and `integration_deliveries` (object, version, status, attempts, request and response, external id, trace) tables; worker with retry and backoff, idempotency keys, backfill over a date range in batches, project enable and disable, isolation so an outage never blocks ingestion (18).
- [x] EarthRanger connector via Gundi (D15): positions as observations, events with type slugs in a `smartparks_protect_` namespace, entity mapping to subjects, per-project Gundi key, test event, health status. Direct EarthRanger API connector recorded as a later option.
- [x] Webhook outbound connector with signed payloads. MQTT outbound connector.
- [x] AddaxAI Connect inbound connector (D16): polling event connector with a cursor per data source, authentication with an AddaxAI Connect API token, per-project filters (detection types, species, confidence threshold, AddaxAI projects), mapping to `SPECIES_DETECTION` events with taxonomy, confidence, camera and site context, position, source detection id as ExternalIdentity, Open in AddaxAI Connect link, idempotency on detection id, raw payload retained.
- [x] Traccar adapter (built from the OpenAPI document; the entity on the map waits for a Traccar instance): websocket or polling event connector for positions, device list management, command connector proof of concept, deep links. One Traccar-fed entity on the map.
- [x] Gateways: `gateways` registry with location and state, ChirpStack gateway state and statistics, gateway diversity and best-gateway analysis over receptions, Network section screens for gateways and connectivity health. Provider diagnostics kept as attributes (20).
- [x] ExternalLink coverage: every data source type ships link templates; provenance panel works for every adapter.
- [x] Integrate section UI: integrations per project, delivery log with payload and response inspection, retry, backfill dialog. AddaxAI Connect source configuration screen.
- [ ] Demonstrator script (architecture 33) written as `docs/getting-started/demonstration.md` (done) and executed (local steps pass; the live steps wait for accounts): two LoRaWAN backends, same entities on the map, raw and normalized traffic, battery and RSSI analysed and exported, geofence or speed rule creating an event, event forwarded to EarthRanger, one Traccar entity, one AddaxAI Connect wolf detection entering as an event with a source link and forwarded by a rule, an alert acknowledged, a device reassigned to another entity with historical positions staying with the old entity, and one command sent through the abstract control path.
- [ ] `VERSION` v0.6.0 for the code (D67), changelog, tag; v1.0.0 after the demonstration.

**Exit criteria.** The demonstration passes end to end and its result is recorded in the session log with screenshots in `docs/assets/`.

---

### Phase 9: MCP read-only proof of concept (v1.1.0)

**Goal.** A separate MCP service exposing the seven read tools from architecture 27.13 through the normal API with OAuth, tested with Claude and ChatGPT.

**Why here.** D22: the API and RBAC are stable after the demonstrator. The proof of concept validates authentication, tool schemas, permissions and traceability before any write tool exists.

**Deliverables.**

- [x] `services/mcp`: MCP server over HTTP using the official Python SDK, calling the API with the user's token, never the database. (2026-09-04, `mcp` 2.1.1, streamable HTTP, stateless, `protect-mcp` on :8001)
- [x] OAuth 2.1 authorization server endpoints on the API (or a small dedicated module) issuing scoped tokens for MCP clients, scopes from 27.5, dynamic client registration if the clients require it. (2026-09-04, D68 to D70: `protect_api/oauth`, client id metadata documents and dynamic registration, PKCE, JWT access tokens, rotated refresh tokens, consent page, Connected AI clients page)
- [x] Resources from 27.2 for projects, entities, devices, events, rules, data sources and traces. (2026-09-04, projects, entities, events, devices and traces; rules and data sources wait for their scopes in phase 13)
- [x] Tools: `search_entities`, `get_entity`, `get_device`, `get_latest_position`, `query_measurements`, `query_events`, `get_processing_trace`, plus `list_projects`. Every tool bounded (27.7). (2026-09-04, plus `list_metrics`, `search_traces`, `search` and `fetch`, D71)
- [x] Prompts: `analyze-device-health`, `investigate-missing-data`. (2026-09-04)
- [x] Audit: every tool invocation logged with user, client type and name, tool and trace id. (2026-09-04, one `mcp.request` audit row per API request a tool makes, with the tool name and the client id; the request id links to the API log)
- [x] AI action policy table with all write classes disabled. (2026-09-04, `protect_api/oauth/scopes.py`: reads per scope, everything else refused)
- [ ] Verified with Claude and ChatGPT. Results and screenshots in `docs/mcp/`. (Claude verified on 2026-09-04 against dev-protect.smartparks.org: registration by client id metadata document, consent, and the three questions answered through list_projects, search_entities, get_latest_position, get_device, search_traces, query_events, list_metrics and query_measurements, every call in the audit log. ChatGPT waits for access: custom MCP servers need Developer mode, which OpenAI gates to Pro, Business, Enterprise and Education; Tim's Plus account does not offer it. The server meets ChatGPT's documented requirements, including `search` and `fetch`.)
- [x] Docs: `docs/mcp/` (setup, authentication, tools, limits). ADR: MCP security boundary. (2026-09-04, ADR 0015)

**Exit criteria.** Both clients answer "Why has device X stopped updating?" using the tools against the dev server.

---

### Phase 10: observability, System Health, backup and disaster recovery (v1.2.0)

**Goal.** The full observability model from architecture 26 and a proven disaster recovery from the backup section, before any production deployment.

**Why here.** The backup Definition of Done says a production deployment is not complete without off-server backups, PITR and a tested rebuild. This phase must land before the first production server.

**Deliverables.**

- [x] OpenTelemetry evaluation and, if accepted, instrumentation of API and workers with correlation to ProcessingTrace ids; metrics for throughput, stream lag, latency and error rates; a documented way to ship them to an external stack (optional Prometheus and Grafana compose profile). (2026-09-04, D75: `shared/telemetry.py`, spans and metrics per bus message, the `observability` profile with `grafana/otel-lgtm`; stream lag and dead letters stay on System Health rather than as OTLP metrics)
- [x] System Health full: every area from 26.2 with drill-down into affected traces; Trace Explorer complete with visual timeline; object-level "View processing trace" on positions, measurements, events, alerts, commands, deliveries and log files. (2026-09-04, `protect_api/health_areas.py`, the timeline in the trace dialog, a trace link on Data Explorer rows; log files arrive in phase 11)
- [x] Trace retention policies per trace class (26.9) as scheduled jobs. (2026-09-04, `protect_rules/retention.py`, daily, `TRACE_RETENTION_*`)
- [x] PostgreSQL backups with pgBackRest or WAL-G: base backups plus continuous WAL archiving to S3-compatible off-server storage, encrypted, PITR documented and tested. (2026-09-04, D72; exercised locally against a posix repository: full backup of the 6.6 GB benchmark database in 79 s, incremental, WAL archiving healthy; PITR documented in the restore guide; the S3 provider and a point-in-time restore on a server wait for the VM)
- [x] MinIO replication or versioned backup to remote S3-compatible storage; database-to-object integrity check. (2026-09-04, D73, exercised against the local MinIO as the target)
- [x] Secrets and configuration recovery procedure, separate from the repository. (2026-09-04, the vaulted host vars, the cipher passphrase and the bucket credentials in a password manager; in the backup guide)
- [x] Automated restore verification job in an isolated compose project: restore, migrate, start, health check, record result. (2026-09-04, `scripts/restore-verify.sh`, passed locally in 54 s with 22.4 million positions and 89.7 million measurements restored)
- [x] Backup and Recovery health page for server admins (28.11 example) integrated with System Health; backup failures raise system alerts through the notification framework. (2026-09-04)
- [x] Full clean-server recovery executed once on a throwaway VM and timed against the 4 hour RTO; RPO under 1 hour verified. (2026-09-04, DigitalOcean: a fresh droplet deployed by the playbook and restored from the Spaces bucket with `scripts/restore.sh --test` in 435 s from droplet creation to a verified server, every row that had reached the archive present; the recovery point on the dev server was 24 s after an incremental and at most `archive_timeout` (15 min) plus push time otherwise)
- [x] Security review of the deployment: credentials storage, backup encryption, least privilege, audit of restore access. (2026-09-04, recorded in the backup guide's security section; the restore is an audited manual action; MCP scopes and rate limits were reviewed in phase 9)
- [x] Docs: `docs/operations/backup-and-recovery.md`, `docs/operations/restore-guide.md`, `docs/operations/observability.md`, `docs/troubleshooting/`. (2026-09-04)

**Exit criteria.** A recorded clean-server rebuild from off-server backups, restore verification running on a schedule, backup health visible in the UI.

---

### Phase 11: multi-path OpenCollar: WebBLE, raw log files and Cloudloop/Iridium (v1.3.0)

**Goal.** The same OpenCollar record can arrive over LoRaWAN, WebBLE, a raw log file and Iridium, all retained as deliveries and shown once.

**Why here.** The deduplication model exists since phase 2; this phase adds the acquisition paths. It depends on the OpenCollar driver, MinIO and the trace model.

**Deliverables.**

- [x] `device_log_files` as managed assets (25.6): upload, SHA-256 duplicate detection, association with a device, parse status, record counts (found, new, duplicate, malformed), firmware and decoder version, re-decode, download original. Storage in MinIO. (2026-09-04, D77, migration 0011, `shared/logfiles.py`, `routers/log_files.py`, the Log files card)
- [x] Log file parser in the OpenCollar driver with the same canonical keys, run by a file processing worker with traces. (2026-09-04, `protect_decoder/logfiles.py`: one source event per frame on the built-in channel source, the driver reads frames by channel; the file has its own trace, every frame a compact one)
- [x] WebBLE in the frontend based on the public Smart Parks OpenCollar WebBLE application: connect, read settings and status, control actions, retrieve stored logs, sync to the backend as deliveries with `ble_synced_at`. (2026-09-04, D76: our own protocol implementation `lib/opencollar-ble.ts` tested against a scripted transport, the card "Nearby over Bluetooth", settings editor from the driver's catalogue; control actions over the WebBLE route through Control; a real collar still to be tried)
- [x] Device Control route selection extended with WebBLE and satellite routes (25.5). (2026-09-04, D79: `candidate_routes`, `route_data_source_id`, the route choice in the dialog, the browser executes and reports)
- [x] Cloudloop adapter: inbound Iridium messages as SourceEvents with satellite delivery time separate from device time, outbound MT/SBD command connector, Thing management sync to ExternalIdentity, deep links, runbook (28.7 example). (2026-09-04, D78, `adapters/cloudloop`, webhook token in the URL with an address allow-list; the runbook is `docs/integrations/cloudloop/index.md`)
- [x] Provenance panel shows all deliveries per canonical record with acquisition channel filter. (2026-09-04, `GET /deliveries`, the deliveries dialog on the device page and in the source event dialog)
- [x] Late data: rules evaluate offloaded history for completeness, automations skip stale alerts by policy. (2026-09-04: records from files are attributed at their own time and evaluated; automations had `max_event_age_seconds` since phase 5; covered by the exit criterion test)
- [x] Docs: `docs/devices/opencollar-webble.md`, `docs/devices/raw-log-files.md`, `docs/integrations/cloudloop/`. (2026-09-04, plus ADR 0017)

**Exit criteria.** One GNSS record delivered by simulator over ChirpStack, uploaded in a log file and synced over WebBLE results in one position with three deliveries. (Met in `tests/decoder/test_logfiles.py` with the wiki's port 13 fix over LoRaWAN, the port 29 flash example as a file and the same record as a browser sync: one position, deliveries `lorawan`, `log_file`, `webble`. The same through the API in `tests/api/test_log_files_api.py`. The browser half against a physical collar is pending.)

---

### Phase 12: data curation and corrections (v1.4.0)

**Goal.** Controlled, versioned, auditable corrections on canonical records with bulk jobs, impact analysis, recomputation and export metadata.

**Why here.** Needs the full pipeline, rules, integrations and exports to recompute and flag downstream effects correctly.

**Deliverables.**

- [x] `data_corrections` and `curation_jobs` tables with the fields from the curation section; curatable fields declared per record type; status ACTIVE, REVERTED, SUPERSEDED, PENDING; structured reason codes. (2026-09-04, migration 0012, `shared/curation/apply.py` `CURATABLE`, `CurationReason`)
- [x] Effective value layer: canonical rows keep original values; reads for map, analytics, rules and exports use the effective value; original and history available through provenance. (2026-09-04, D80: overlay columns and `shared/curation/effective.py`; every reader switched; `GET .../curation/history`)
- [x] Bulk curation workflow: select project, devices, record type, period, transformation (for example timestamp plus 12 hours), preview with sample validation and impact analysis (project and entity attribution changes, affected aggregates, rules, deliveries), apply, revert. (2026-09-04, `shared/curation/jobs.py`, batches in the export service; aggregates are computed live so the impact lists attribution changes, sent deliveries and enabled rules)
- [x] Recomputation: change events invalidate aggregates, rebuild track segments and derived measurements, re-evaluate configured rules, flag stale outbound deliveries for review. (2026-09-04, D82: attribution rerun, current state recomputed, tracks and aggregates read the effective value live, stale deliveries flagged with a resend as a new version, rule replay as a report on request; `curation.applied` on the bus)
- [x] Permissions and optional two-step approval (propose, approve). (2026-09-04, D81: project setting `curation_requires_approval`, `data:curate`, `data:curate_bulk`, `data:approve`, `data:revert`; the proposer never approves their own)
- [x] Curation workspace UI under Analyze: pending, applied, bulk jobs, reverted, downstream impact; curate action on records in the Data Explorer; curated fields visibly marked. (2026-09-04, `CurationPage`, `CurateDialog`, `CuratedBadge` with the record history, also on device page positions)
- [x] Export options for effective, original canonical and raw views with curation metadata columns. (2026-09-04, D83: `view`, `curation_metadata`; raw is the source events dataset)
- [x] Docs: `docs/analytics/curation.md`. ADR: immutable source data and layered interpretation. (2026-09-04, ADR 0018)

**Exit criteria.** A bulk timestamp correction over a device range shifts the effective values, moves attribution where applicable, recomputes affected aggregates, flags EarthRanger deliveries, and can be reverted without loss. (Met in `tests/api/test_curation_api.py`: a +12 h job over three positions shifts the effective times, moves the two records that cross a device handover to the other project, flags the delivery already sent to an integration, which is resent as version 2, and the revert restores times, attribution and counts; aggregates are computed on the effective value, verified through the analytics series.)

---

### Phase 13: platform expansion (v1.5.0)

**Goal.** Remaining adapters and outbound platforms from the architecture, project dashboards, and MCP write tools.

**Why here.** Each item reuses proven frameworks. They are ordered by Smart Parks demand and can be picked individually.

**Deliverables.**

- [x] The Things Stack adapter (events, gateways, downlinks). (2026-09-04, D84, `adapters/tts`, from the webhook, downlink and gateway documentation)
- [x] Actility ThingPark adapter (private and public variants share code with KPN). (2026-09-04, `adapters/actility_thingpark`, a subclass of the KPN adapter)
- [x] CRA IoT adapter (added on Tim's request). (2026-09-04, D90, `adapters/cra_iot`, from the platform's public documentation and Swagger; the live check waits for an account with a LoRa device)
- [x] WildlifeNL outbound connector (API and mappings confirmed in a spike first). (2026-09-04, D88, `connectors/wildlifenl.py`, from the platform's open source API after Tim sent the repository; the live check waits for the platform's URL and a data-system account)
- [x] FerusTracker outbound connector. (2026-09-04, D89, `connectors/ferustracker.py`, from the Node-RED flow Tim shared; the live check waits for the site value and a look at the platform)
- [x] Movebank outbound connector with entity, assignment period, timestamp and sensor mappings. (2026-09-04, D85: two export datasets in Movebank's import format instead of a push connector, since Movebank ingests through arranged live feeds or file import)
- [x] Direct EarthRanger API connector variant with stable object ids and updates. (2026-09-04, `connectors/earthranger.py`, updates through the previous delivery's id)
- [x] Project dashboards: saved views arranged on a grid, shared per project. Not a Grafana clone (30.2). (2026-09-04, D86)
- [x] MCP write tools by impact class with the AI action policy: `acknowledge_alert`, `create_event`, `request_device_status`, confirmation flows, privileged scopes. (2026-09-04, D87, ADR 0019; plus `request_device_position`, `confirm_action`, `get_ai_policy`; high-impact control disabled)
- [x] Project-specific SVG icon upload with validation (24.6, optional). (2026-09-04)
- [x] Docs and runbooks per connector. (2026-09-04: The Things Stack, Actility, EarthRanger direct, dashboards, icons, MCP write tools)

**Exit criteria.** Each connector has a runbook, fixture tests and a recorded live test. (Runbooks and fixture tests exist for The Things Stack, Actility, CRA IoT, the direct EarthRanger connector, WildlifeNL and FerusTracker; the recorded live tests wait for an application, a deployment and a site, listed under the inputs.)

---

### Phase 14: production hardening and 2.0

**Goal.** Full-scale benchmark, documentation audit, security audit, and the remaining architecture items needed for production use across multiple parks.

**Deliverables.**

- [x] Benchmark at the full reference envelope (13.9) on a representative server; performance budgets met or documented. (2026-09-05, D91: scale 0.2 on the dev server, 44 million positions and 177 million measurements generated in 4.1 hours with compression behind the write frontier; every interactive read path within budget; over budget and documented: the direct positions export at 10.3 s against 10 s, and the decoder path under a burst at 77 s p95 from webhook to canonical row, 15 uplinks per second on 4 vCPU; the export job streamed 22.6 million rows in 73 minutes within 129 MiB. `docs/operations/benchmarks.md` and the scalability page carry the reading; the full envelope stays extrapolated.)
- [x] Documentation Definition of Done audit over the whole site; link check, OpenAPI freshness check and diagram validation in CI (28.8). (2026-09-04: `scripts/docs_check.py` for links, anchors, Mermaid fences and the MCP tool reference in the docs CI job next to the OpenAPI freshness job; the audit walked the navigation against the feature list and fixed what was stale: the getting-started page became the quick start with the language note, the deployment and update guides lost their pre-phase-10 wording, phase numbers left the OpenCollar, adapter interface, ChirpStack, MCP and rules pages, and new pages cover security, the release process and organizations)
- [x] Security audit: RBAC on every endpoint tested, credential handling, MCP scopes, rate limits, dependency audit. (2026-09-04, D94: `tests/api/test_access_matrix.py`, application-level throttling, `pip-audit` and `npm audit` in CI, `docs/operations/security.md` with the findings; one fix: curation permissions moved into route dependencies)
- [x] Organization tenancy decision revisited (D21). (2026-09-04, D92: organizations as a grouping; `/admin/organizations`, `organization_id` on projects, filter and column on the Projects page, `docs/administration/organizations.md`)
- [x] Multi-language UI decision. (2026-09-04, D93: translation-ready with i18next, the English catalogue extracted from every component, the lint rule, the catalogue check in CI, a language switch; English only)
- [x] Release process documented: version, changelog, upgrade notes, migration and rollback guidance (28.9). (2026-09-04, `docs/operations/release-process.md`; the update and deployment guides lost their pre-phase-10 wording)
- [ ] `VERSION` v2.0.0.

**Exit criteria.** A new operator deploys production from the docs alone; a new developer adds a driver from the extension docs alone. (Developer half checked on 2026-09-04 by writing a throwaway driver for a vendor GPS tracker from the guide and its public manual alone; the guide gained what the check missed: how a LoRaWAN frame reaches the driver, metric seeds through a migration, control actions, fixtures, the docs page and the device type. The driver itself was removed at Tim's request on 2026-09-05: the product focuses on OpenCollar. Operator half checked the same day: a throwaway droplet deployed from the deployment guide alone in 7 minutes 41 seconds; the run ended on the security check's finding that v0.6.0, the newest tag the playbook chooses, binds the frontend to every interface, which the unreleased deployment fix resolves; `bootstrap-admin` and `verify-server.sh` passed; the update guide's `env-refresh` to `main` took 3 minutes 39 seconds and all seventeen checks passed. The droplet was destroyed afterwards. Two doc additions came out of it: the wildcard DNS tip for throwaway servers and the note on the strict final check.)

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
- [ ] Phase 7: KPN/ThingPark, LORIOT, Netmore (portal.blink.services, LoRaWAN Portal) and akenza test accounts. The dev VM and domain exist since 2026-09-04 (dev-protect.smartparks.org). Device deep link paths for Netmore and akenza are guesses until seen live.
- [x] Phase 10: an S3-compatible bucket for backups and a throwaway VM for the timed clean-server recovery. (2026-09-04, DigitalOcean Spaces and droplets through the API token)
- [ ] Phase 9: a ChatGPT account with Developer mode (Pro or Business) to connect https://dev-protect.smartparks.org/mcp; Claude was verified on 2026-09-04.
- [ ] Phase 8: Gundi connection and EarthRanger test site (event type `smartparks_protect_event` created there), an AddaxAI Connect viewer account on a dev server (D63), a Traccar test instance or account. Deep link paths for Traccar and AddaxAI Connect are guesses until seen live.
- [ ] Phase 11: Cloudloop test account and an OpenCollar with BLE for WebBLE work. (Built from documentation on 2026-09-04; the card and the adapter wait for a collar and an account.)
- [ ] Phase 13: WildlifeNL, FerusTracker and Movebank API access. (2026-09-04: WildlifeNL's API is open source and the connector is built; FerusTracker's contract is the Node-RED flow Tim shared and the connector is built; Movebank became an export format. Still needed for live checks: a The Things Stack application, an Actility ThingPark deployment, an EarthRanger site with a token, WildlifeNL's API URL with a data-system account, FerusTracker's site value, and a CRA IoT account with a LoRa device.)

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
- CI on the release commit failed twice: `.gitignore` had `data/`, which hid `src/components/data/DataTable.tsx` from git, so the frontend build failed on a clean checkout (rule is now `/data/`); the decoder test job failed because the CI MinIO has no `uploads` bucket (the on-demand creation noted in phase 2 had never been written); pytest steps now print failures as workflow annotations because the logs are not readable without a token (no `gh` on this machine). Fixed on main after the tag; CI is green on main at `49d8098` (seven jobs). Tim chose to tag `v0.1.1` on the fixed main rather than move the public `v0.1.0` tag. The v0.1.1 run failed only the OpenAPI freshness job, because the committed schema carried the old version string; the export now pins `info.version`, so releases do not touch the schema. The tagged code itself is fine.
- 100 python tests, 2 frontend tests, lint and types clean, docs strict, sweep 31 routes times 3 viewports clean. Committed and tagged v0.1.0 on Tim's instruction.
- Next session: run the quick start on a clean checkout (phase 3 exit criterion on a fresh machine), then phase 4 starting with the aggregation API.
- Decisions to ask Tim when phase 4 starts: where the export worker runs (proposed: `services/export` in the shared Python image, own compose service); XLSX writer (proposed: openpyxl write-only mode); resolution selection rule for aggregates (proposed: pick the coarsest `time_bucket` that keeps a series at or under 5,000 points); saved views storage (proposed: `saved_views` table per project, JSONB filter). Everything phase 4 needs is in place: TimescaleDB hypertables, MinIO, ECharts installed, the Redis bus and worker base class. Inputs still wanted: recorded live OpenCollar uplinks, confirmation of the composed wide logo.

### 2026-09-03, phase 4 (Claude)

- Tim decided D39 (export worker as its own service in the shared image), D40 (openpyxl write-only), D41 (bucket ladder, at most 5,000 points per series), whole phase backend first; D42 (saved views table) recorded by Claude.
- Quick start on a clean checkout, from GitHub at v0.1.1: the stack came up and ChirpStack, traffic, traces and deep links worked, but no positions appeared. Two causes fixed: the simulator sent generic JSON while the README's device type uses the OpenCollar driver (the simulator now encodes real OpenCollar port 2 and port 4 frames, with a test that the driver decodes them, and `--interval` spaces the fixes), and the bootstrap passed no API key to the Protect data source when it minted one. `chirpstack-bootstrap --demo` now creates the Protect side (project, types, device, identity, entity, assignments) so the quick start has no UI clicks. Re-verified on the clean stack with the fixed scripts: 12 uplinks processed, 10 positions on the map.
- Aggregation API in `shared/analytics.py` and `routers/analytics.py`: series, long and wide layouts, automatic resolution, drill-down rows, metrics with data, saved views. Cursor pagination learned bigint keys.
- Export engine in `shared/exports/` and the `protect-export` service (migration 0004: `export_jobs`, `saved_views`): jobs to MinIO with progress, SHA-256 and metadata, direct downloads bounded at 100,000 rows, CSV, XLSX with sheet splitting, JSON, GeoJSON, GPX. Three bugs found by the benchmark and fixed: a progress commit closed the server-side cursor (progress has its own session), ORM rows grew the worker to 269 MiB (plain columns now, flat at about 90 MiB for 1.35 million rows), and the on-demand MinIO bucket creation.
- Frontend: Data explorer (filter builder from metrics with data, ECharts line, scatter, bar, histogram and state timeline, table with drill-down to rows and source events, saved views, timezone, export from the current view) and Exports (jobs with progress, download through the API, reproduce, details). State lives in the URL. Sweep clean on 33 routes times 3 viewports.
- Benchmark: `scripts/benchmark/generate.py` (COPY, eight parks, home-range walks) and `run.py` (writes `docs/operations/benchmarks.md`, `--only` for one section). Run at 1/100 and then at 1/10 on this machine (22.4 million positions, 89.7 million measurements, 39 minutes to generate, 73 GB before compression): every read path within budget at both scales, an 11.4 million row export streamed with the worker flat at about 100 MiB, compression measured at 16x (measurements) and 10x (positions). TimescaleDB confirmed, ADR 0003 updated, `docs/architecture/scalability.md` written. The dataset stays in the local database; `generate.py --reset` removes it.
- What failed and what was done: the decoder handled 60 events per second sequentially. The bus now handles batches in lanes per device (`BUS_CONCURRENCY`), which gave 90 per second; more lanes changed nothing, so the rest is CPU per event. Open for the next session: profile the decoder (statements per event, batch the trace steps), and make the decoder count a deployment variable in phase 7.
- Lessons: `docker compose up --build` fails silently in a chained shell command when the compose file is invalid, and the old containers keep running; after every rebuild the code inside the container is now checked before a benchmark is trusted.
- Not done in this phase: table virtualization, column selection and grouping in the Data explorer (the shared table sorts only); noted on the deliverable. The Playwright sweep still has no assertions.
- 117 python tests, 5 frontend tests, lint and types clean, docs strict, OpenAPI schema regenerated. Committed and tagged v0.2.0 on Tim's instruction.

### 2026-09-04, phase 5 (Claude)

- Tim decided D43 (one Telegram bot per installation, chats linked with a code), D44 (two services: rules and automation), D45 (constructs for this phase, the rest reserved), whole phase in one session backend first. Claude recorded D46 (viewers hold `alerts:write`), D47 (system alerts are events without a project), D48 (edge-triggered firing with cooldown reminders).
- Built `shared/rules` (schema with six templates, evaluator, SQL data access in live and historical mode, event creation, replay), `shared/notifications` (render, email with the guard moved out of the API mailer, Telegram, dispatch), migration 0005, `protect-rules` (engine with rule cache and per-rule transactions, scheduler, system checks) and `protect-automation` (idempotent deliveries, signed webhooks, retry through the bus, Telegram poller). API: rules with versions, templates, schema and replay; events and alerts for projects and the server; automations, notification targets, deliveries and test sends for both scopes; recent events on the map.
- Frontend: Rules with the editor (template picker, condition builder, JSON fallback, versions, replay tab), Events with detail and deliveries, Alerts inbox, Automations with deliveries and retry, Notifications with the Telegram link dialog; the same pages serve the server scope under Server admin; events on the live map with the event marker family; the map's alert count links to the inbox. Placeholders for Alerts, Rules and Events are gone.
- Lessons: a `DeliveryRead` schema name collided with the attention router's and the generated TypeScript type got a module prefix, so the class is `ActionDeliveryRead`; a test that reads a worker's commit from its own session sees it fine (read committed), the stale row was a missing status filter that a silent string replace had skipped after ruff reformatted the line. Patch scripts now assert their matches.
- First start on the development stack: a new consumer group reads a stream from its beginning, so the rules service saw the 9,884 benchmark messages per topic as lag and opened two system alerts, which resolved themselves as it caught up; a backlog is evaluated against no enabled rules cheaply because the handlers now return before loading rows when no rule has that trigger. On a production server the same happens once when a new worker joins; the automation freshness bound stops any stale notification.
- Not done on purpose: NEAR, DWELL, CROSSED, baseline, correlation and event chaining (phase 13, reserved in the schema); a data source health signal for system alerts (phase 7); rule state for the `any` branch keeps geofence memory for every branch evaluated, which is intended. Late samples older than the last firing are evaluated normally; the automation freshness bound is the guard against stale notifications.
- Verification: 157 python tests, 5 frontend tests, ruff, mypy strict, eslint and tsc clean, docs strict, OpenAPI regenerated, compose stack rebuilt with the two new services running, screenshot sweep clean on 34 routes at three viewports against the rebuilt stack. The sweep account `sweep@example.org` (server admin, local development stack only) was created directly in the development database because the environment has no sweep credentials; delete it or set `SWEEP_EMAIL` and `SWEEP_PASSWORD` in `.env` for the next sweep.
- Committed as f119a80 and pushed on Tim's instruction. The v0.3.0 tag is pending Tim's review.
- Decisions asked at the start of phase 6, see the next entry. Earlier list: how action definitions are versioned (open decision, proposed dataclasses with a `schema_version` and Pydantic parameter models), whether the ChirpStack command connector uses the REST API or gRPC (proposed REST, already used by the management connector), whether commands wait for a device response before CONFIRMED_BY_DEVICE (proposed: the driver interprets the next matching uplink), and where the OpenCollar encoders get their port and payload table (the protocol research document has RESET and REQUEST_STATUS).

### 2026-09-04, release v0.3.0 and phase 6 (Claude)

- CI green on the phase 5 commits; tagged v0.3.0 on Tim's instruction (a662b21).
- Tim decided D49 (action definitions as versioned driver code with Pydantic parameters), D50 (ChirpStack downlinks over the REST API queue), D51 (the driver's interpreter confirms a command from later uplinks). Claude recorded D52 (routing, failed submissions stay in the history, audit-class traces, expiry).
- Built `shared/control` (action contract, the command path with route selection, provider signals, device interpretation, expiry), OpenCollar actions `REQUEST_STATUS`, `REQUEST_POSITION`, `SET_GNSS_INTERVAL`, `RESET` with encoders from protocol research section 4 and interpreters, the ChirpStack command connector (queue post, read, flush), migration 0006, the decoder hooks, expiry in the rules ticker, the automation `command` action, the control API, `command.updated` on the WebSocket.
- Frontend: Actions menu with disabled reasons, parameter form from the JSON schema, confirmation for confirm and privileged policies, command history with the lifecycle timeline and trace link, the platform queue with flush, the Commands page under Control, command actions in the automation editor.
- Not done on purpose: a `SCHEDULED` stage is never reached with ChirpStack (it reports no scheduling); `SET_GNSS_INTERVAL` has no interpreter because a settings write returns a confirmation only for settings with an action; the guard test that no provider code lives outside the adapters arrives in phase 7 as planned.
- Verification: 185 python tests, 5 frontend tests, ruff, mypy strict, eslint and tsc clean, docs strict, OpenAPI regenerated, compose stack rebuilt, screenshot sweep clean on 35 routes at three viewports. Live exit criterion on the local ChirpStack: `REQUEST_STATUS` and `RESET` issued through the API for the demo collar were queued with payloads `a400` and `a100` on port 32, both visible in the ChirpStack device queue, the timeline shows created, encoded, submitted, accepted by network and queued, the queue was flushed afterwards. The simulator does not transmit downlinks, so transmitted and confirmed stages were verified with the fixture tests, not live.
- The demo collar in this development database still had the pre-v0.2.0 generic JSON type; it now has an OpenCollar Edge type (created through the API), which is what the current bootstrap creates on a fresh stack.
- Committed as f540569 and pushed on Tim's instruction. The v0.4.0 tag is pending Tim's review.
- Decisions asked at the start of phase 7, see the next entry. Earlier list: KPN/ThingPark integration style (proposed: HTTP push from ThingPark to the webhook endpoint with the per-source bearer token, downlinks through the ThingPark REST API), LORIOT integration style (proposed: the LORIOT websocket application output with the downlink API), which accounts and devices exist for live tests, and whether the dev VM is provisioned by Ansible from this repository from the first run (proposed: yes, DigitalOcean Ubuntu 24.04).

### 2026-09-04, release v0.4.0 and phase 7 (Claude)

- CI green on the phase 6 commits; tagged v0.4.0 on Tim's instruction (288320d).
- Tim decided D53 (KPN through ThingPark HTTP push and the downlink API), D54 (LORIOT through the websocket output with downlinks on the same connection), D55 (build from public documentation now, verify live later), and asked for Netmore as a third production network (D57). Claude recorded D56 (adapter metadata from the API, no provider names in the frontend).
- Built the KPN/ThingPark adapter (uplink, downlink sent, location and notification documents; LRR receptions; the downlink connector in token and bearer mode), the LORIOT adapter (websocket connector with reconnect on the transport base, `rx`, `gw`, `txd` frames, the HTTP output variant, downlinks as `tx` frames), adapter metadata in the registry and `GET /data-sources/adapters`, push tokens for every adapter that declares `push`, the acquisition channel on the adapter instead of a provider table in the control module, the provider boundary guard test (backend and frontend), the Ansible playbook with security, docker, nginx, ssl, dev-tools, app-deploy and security-check roles plus the example inventory and vars, `scripts/verify-server.sh` and `scripts/security-status.sh`, the runbooks for KPN and LORIOT, the deployment and update guides. The data source form reads adapters from the API.
- Fixtures for KPN and LORIOT are invented from the documentation and say so in their README; recorded payloads replace them at the live run.
- Netmore, on Tim's pointer to the online documentation: built from docs.connect.netmoregroup.com (export format with its four variants, HTTP push with static headers, the MQTT broker and topics, downlink over MQTT with its responses) and the Netmore Connect OpenAPI document (`POST /devices/LoRaWAN/{devEui}/LoRaWAN/downlink` with `payloadHex`, `fPort`, `confirmed`, `validity` and the `api-key` header, `clearDownlink`). Netmore has two platforms (the older LoRaWAN Portal and Netmore Connect); the export format is shared, downlinks use the Connect API. The decoded export formats are refused with an explanation because they carry no raw frame.
- Not done, waiting for inputs: the live run of a command over KPN, LORIOT or Netmore, the dev server (no VM, no domain), real collars on the map. The Ansible playbook is YAML-validated but has not been run against a server.
- Verification: 214 python tests (adapter parsing for KPN, LORIOT and Netmore, downlink connectors against mocked transports, the provider guard, the adapter metadata endpoint), 5 frontend tests, ruff, mypy strict, eslint and tsc clean, docs strict, Ansible YAML loaded and the shell scripts parsed, OpenAPI regenerated, compose stack rebuilt, `GET /data-sources/adapters` answered live with six adapters (seven after akenza), screenshot sweep clean on 35 routes at three viewports. Migration 0007 changes a column comment that named a provider; 0006 is untouched because v0.4.0 ships it.
- Not committed. Tim reviews and commits; v0.5.0 waits for the live items, so no tag yet.

### 2026-09-04, Netmore platforms and akenza (Claude)

- Tim's Netmore account is on portal.blink.services, the LoRaWAN Portal. Its API document (api.blink.services/rest/swagger.json) has a login endpoint returning a bearer token, `POST /net/sensors/{devEui}/downlink` with `fPort`, `payloadHex`, `confirmed`, `validity` and `requestId`, a queue list with `deliveryStatus`, and a clear call. Tim decided D58: one adapter, a `platform` setting, both downlink paths. Built the portal connector (token cached, renewed on 401, `requestId` set to the command id so an MQTT `downlink-response` can move the command), kept the Connect connector, and the queue reads through the portal.
- Tim asked for akenza.io. From docs.akenza.io (the webhook connector posts the whole sample; the LoRaWAN uplink event carries `data.port`, `data.payloadHex`, `uplinkMetrics` and `device`) and the published API collection (`POST /v3/devices/{id}/downlink` with `{"raw": true, "loraDownlink": {"port", "payloadHex", "confirmed"}}`, `x-api-key`, `GET /v3/devices/by-device-id`). Tim decided D59: webhook events, REST downlinks, the akenza device id as the external identity with the DevEUI as an attribute. Built the adapter with a new identity type `akenza_device_id`, the runbook, fixtures from the documentation's sample.
- Decoded akenza samples and decoded Netmore export formats are refused with an explanation, because neither carries the raw frame the driver needs.
- Verification: 226 python tests (both Netmore downlink connectors against mocked transports, the akenza sample and downlink, the provider guard), ruff, mypy strict, docs strict, compose stack rebuilt, `GET /data-sources/adapters` answers live with seven adapters. Committed as e3379f0 and pushed on Tim's instruction; v0.5.0 waits for the live items.

### 2026-09-04, phase 8 (Claude)

- Asked the phase 8 decisions (D60 to D67, all recommendations accepted): object-keyed idempotent deliveries, table-driven retries, the entity as Gundi source, a dedicated AddaxAI Connect account, a captured-at cursor with rescans, Traccar over its websocket, a server-level gateway registry, v0.6.0 for the code and v1.0.0 after the live demonstration.
- Built `shared/integrations` (contract, Gundi, webhook and MQTT connectors, the delivery mechanism with backoff, backfill and traces), migration 0008, the `protect-integration` service, the integrations and gateways API, the Traccar and AddaxAI Connect adapters with fixtures from their documentation, gateway updates from receptions and ChirpStack gateway events with a sync action, polling cursors, the Integrate and Gateways screens, rescan and gateway sync on the data sources page, runbooks, ADR 0014 and the demonstration script.
- Found that the provider boundary guard had a literal backspace where `\b` was meant and matched nothing since phase 7; fixed, and the guard now also covers AddaxAI, Gundi and EarthRanger names. It flagged one description in the new UI, which was reworded.
- Verification: ruff, mypy strict, 316 Python tests against the local stack (new suites for integration, Traccar, AddaxAI Connect, gateways, API), eslint, tsc, vite build, vitest, mkdocs strict, the stack rebuilt with migration 0008 and the integration worker running, screenshot sweep, and a live webhook delivery on the dev stack (see below).
- Live check on the dev stack: a webhook integration on Demo park pointing at a local receiver; three simulated OpenCollar uplinks became three sent deliveries (signed body, `X-Protect-Delivery`, target response recorded), the local gateway appeared in the registry with 22 receptions and a ChirpStack deep link, the connectivity view showed the collar heard by one gateway, and Sync gateways read the gateway from the ChirpStack API. The integration was removed again afterwards.
- Open: the live steps of the demonstration and the deep links of four platforms wait for accounts.

### 2026-09-04, phase 9 (Claude)

- Tim decided to defer the live tests of phases 7 and 8 until the dev server exists, with two limits: run the Ansible playbook against any VM before phase 10 adds to it, and confirm one documentation-built adapter live before phase 13 adds more. Phase 9 started; the four decisions (D68 to D71, all recommendations accepted): the API is the OAuth 2.1 authorization server reusing the MCP SDK's handlers, JWT access tokens with the MCP URL as audience, the full tool set with `search` and `fetch`, resources and prompts, a consent page plus a connections page.
- Researched the current documentation first: the MCP authorization specification (protected resource metadata, RFC 8414 metadata, PKCE, resource indicators, client id metadata documents as the preferred registration, dynamic registration deprecated), Claude's connector requirements (streamable HTTP, callback `https://claude.ai/api/mcp/auth_callback`, loopback for Claude Code, `WWW-Authenticate` with `resource_metadata` on 401, CIMD selected only when `none` is a token endpoint auth method), ChatGPT's requirements (CIMD at `https://chatgpt.com/oauth/client.json`, `search` and `fetch` for deep research), and the MCP Python SDK 2.1.1 (`MCPServer`, `TokenVerifier`, `AuthSettings`, the authorize, token and registration handlers, the provider protocol) read from the installed package.
- Built `shared/oauth.py` (scopes, JWT mint and decode), the OAuth tables and migration 0009, `protect_api/oauth` (provider, scope policy, admission middleware with audit, routes with the SDK handlers, consent and connections endpoints), the audience change in the JWT strategy, `services/mcp` (token verifier, API client, twelve tools, five resource templates, two prompts, the ASGI app with both metadata paths and a health route), the compose service, Dockerfile, nginx routes in the frontend container and the Ansible template, env variables, the CI matrix entry, the consent and Connected AI clients pages with the sidebar link, `docs/mcp/index.md`, ADR 0015, and the `q` filter on the entity list that `search_entities` needs.
- Verification: ruff, mypy strict, eslint, tsc, vitest, vite build, OpenAPI regenerated; the Python suites (`tests/api/test_oauth.py`: metadata, registration rules, the full PKCE flow, scoped and audited access, code reuse, refresh rotation, revocation, consent denial, resource and redirect validation, a client id metadata document; `tests/mcp`: discovery, 401 and 403 challenges, tools over streamable HTTP against the real API, resources, prompts, audit rows, no data without membership) pass (15 tests), the full Python suite passes (279 tests), the screenshot sweep is clean on 37 routes at three viewports including the consent and Connected AI clients pages, and on the rebuilt local stack the whole flow ran through nginx: metadata, dynamic registration, authorize, consent, PKCE token exchange, then every tool over `/mcp` against Demo park (Rhino 14, its collar, traces, metrics, aggregates, position, search and fetch, a prompt), a write with the token refused with `insufficient_scope`, the connection listed and revoked.
- Found while testing: a URL object built outside the SDK's metadata models gains a trailing slash on a path-less issuer, which would break RFC 8414 issuer comparison in clients; the models now receive strings. Entity and device types are named by `label`, not `name`.
- Not done: the exit criterion (Claude and ChatGPT against the dev server) waits for the VM and the domain. `ruff format` also reformatted five test files of phase 8 that had drifted. Not committed; Tim reviews and commits.

### 2026-09-04, release v0.6.0 (Claude)

- CI green on the phase 9 commit (6186e2f); the phase 8 commit had failed CI on `ruff format`, fixed by the same commit. Tagged v0.6.0 per D67 on Tim's "continue". Phase 10 starts next.

### 2026-09-04, phase 10 (Claude)

- Decisions D72 to D75 asked and accepted as recommended: pgBackRest in the database container, `mc mirror` for objects, host cron with a `backup_runs` table, OpenTelemetry with an optional Grafana profile. Facts checked first: the TimescaleDB image ships pgBackRest 2.59.1, WAL archiving was off, AddaxAI Connect uses a host cron with status in Redis.
- Built: `docker/postgres/pgbackrest.conf` and the `protect-pgbackrest` wrapper, `archive_mode=on` with `archive_timeout=900` in compose, the `object-mirror` and `lgtm` profiles, `BACKUP_*`, `TRACE_RETENTION_*` and `OTEL_*` settings, `backup_runs` (migration 0010), `shared/backup.py`, `protect_api/backup.py` (record, integrity), the backups router and page, `SYSTEM_BACKUP` findings, `protect_rules/retention.py`, `shared/telemetry.py` with the bus, tracer, worker, API and MCP hooks, `protect_api/health_areas.py` and the System Health areas on the page, the trace timeline and the explorer trace link, `scripts/backup.sh`, `scripts/restore.sh`, `scripts/restore-verify.sh` with `docker/backup/verify.yml`, the Ansible schedule and variables, ADR 0016 and four guides.
- Exercised on the local stack with a posix repository and the local MinIO as the mirror target: stanza, check (WAL push through the async spool), full backup (79 s, 2.9 GB), incremental, object mirror, integrity check, the status page, and the restore test end to end (54 s: restore, WAL replay to the last transaction, promote, migrate, API healthy, 22.4 million positions, referenced objects present). Found on the way: pgBackRest refuses empty options and needs the word pgbackrest in `archive_command` (hence the wrapper as the archive command), the generated `restore_command` needs the wrapper as `cmd`, and a second compose project needs its own network and container names because compose fixes both.
- Verification: ruff, mypy strict, 286 Python tests, eslint, tsc, vitest, vite build, mkdocs strict, both compose configurations, screenshot sweep clean on 40 routes. Not committed.
- Open: the clean-server recovery on a VM with an S3 bucket, timed against the RTO.

### 2026-09-04, dev server on DigitalOcean and the recovery drill (Claude)

- Tim connected the Smart Parks DigitalOcean account with an API token kept in `~/.config/smartparks-protect` (outside the repository; a pre-commit hook now refuses credentials and filled-in configuration, commit a717be9). Created with `doctl`: the droplet `smartparks-protect-dev` (4 vCPU, 8 GB, ams3, 178.62.201.128), the Spaces bucket `smartparks-protect-dev-backups` with its own key; Tim added the A record `dev-protect.smartparks.org` at TransIP. Inventory and vaulted host vars live in the same private directory.
- First playbook runs on a real server found five defects, all fixed and pushed: the sshd drift check compared `prohibit-password` while `sshd -T` prints `without-password`; the frontend port was published on every interface and Docker bypasses ufw; the security check failed its ssh test under `pipefail` and never counted passes; a failing final check left the TLS site unreloaded because handlers had not run; the commit hash was not passed to the build. Then the run went fully green: 17 security checks, TLS from Let's Encrypt, `verify-server.sh` passing, ten cron jobs.
- Backups against Spaces: PostgreSQL crashed every ten seconds once archiving was on, because PostgreSQL was PID 1 in its container and pgBackRest's detached asynchronous archive process was reparented to the postmaster, whose exit the postmaster took for a crashed backend; `init: true` on the database service fixed it. Stanza, check, full and incremental backups, object mirror, integrity check and the restore test (69 s) then passed on the server.
- The clean-server recovery drill found a data-loss risk: the drill server archived its promoted timelines into the production stanza and a later restore followed "latest", missing rows that were on the real timeline. Fixed: restores use `--target-timeline=current`, `scripts/restore.sh --test` turns archiving off on a drill server, the stray timelines were purged from the archive. The drill then took 435 s from droplet creation to a verified restored server with every archived row present (target four hours); the drill droplet was destroyed.
- Open: Tim registers with the invitation link on the dev server and connects Claude and ChatGPT. The object restore's warning on empty buckets was a wrong emptiness test, fixed.
- Later the same day: Tim registered on the dev server and connected Claude; the three questions of the exit criterion were answered correctly against a seeded Demo park (Rhino 14, collar SP05-demo, 48 hourly uplinks then silence). ChatGPT could not be tested: Developer mode is not offered on Tim's Plus plan. An operations admin account (protect-ops@smartparks.org, credentials in the private config directory) seeds and checks the dev server.

### 2026-09-04, phase 11 (Claude)

- Decisions D76 to D79 asked and taken: our own WebBLE protocol implementation (the public app is GPL-3.0, this repository MIT), one source event per frame on built-in channel sources with a browser sync stored as a log file, Cloudloop over its Lingo webhook with the token in the URL, and a route choice in the control dialog with the browser as a route that is never chosen automatically.
- Backend: `device_log_files` and the built-in sources "Browser (WebBLE)" and "Log file upload" (migration 0011, fixed ids); `shared/logfiles.py` and the file processing worker in the decoder service (batches, counts, period, firmware, re-decode); `InboundMessage.device_id` for deliveries whose device the caller knows; the OpenCollar driver reads frames by acquisition channel and ships its protocol catalogue (`catalog.json`, 123 settings, 46 commands, 20 values, generated from the research document); the Cloudloop adapter (Lingo and Core shapes, `Data/DoSendSbdMessage`, `Data/GetThings`, `Platform/Ping`); route options, pinned routes and client-only routes in the command path; new endpoints for log files, syncs, routes, browser results, deliveries per record and the driver catalogue; webhooks with `?token=` and `allowed_source_ips`.
- Frontend: `lib/opencollar-ble.ts` (Nordic UART, frames, settings encoding, status decoding, log streaming) over an injected transport with nine tests, the WebBLE store and hook, the cards "Nearby over Bluetooth" and "Log files", the route choice and browser execution in Control, deliveries with a channel filter, built-in sources kept out of the create dialog.
- Verified: 303 Python tests (the exit criterion as a decoder test and through the API, malformed frames, re-decode, the Cloudloop webhook with token and allow-list, the WebBLE command path with the device's confirmation through a synced frame), lint, mypy, frontend lint, typecheck and 14 tests, strict docs build; the whole path also exercised through the rebuilt local stack (upload, decode, re-decode, browser sync, WebBLE route, command written by the browser and confirmed by a synced status frame) and the screenshot sweep.
- Open: a physical OpenCollar for the Bluetooth half and a Cloudloop account with an enrolled RockBLOCK; Cloudloop's deep link path is a guess; the frames of a BLE session are synced when an operation ends, not live.

### 2026-09-04, phase 12 (Claude)

- Decisions D80 to D83 asked and taken: overlay columns with the originals untouched, a per-project approval switch, bounded and reviewed recomputation, effective and original export views.
- Backend: migration 0012 (overlay columns and partial indexes on positions and measurements, `data_corrections`, `curation_jobs`, stale flags on deliveries); `shared/curation/` (effective value expressions, apply and revert with superseding chains, attribution rerun, current state recomputation, delivery flagging, bulk jobs with preview, impact, batches and a replay report); every reader switched to the effective value (map track, positions, analytics, rule data access and replay, exports, integrations); the curation router; `?stale=true` and resend on deliveries; the export service runs curation jobs.
- Frontend: the Curation workspace under Analyze, the curate dialog and history on device positions and explorer rows, the approval switch in project settings, stale deliveries with resend, export view options.
- Verified: the curation API tests (single corrections through every reader, the approval switch with four eyes, the bulk shift with preview, apply, stale delivery, resend and revert), lint, mypy, frontend lint, typecheck and tests, strict docs build.
- Note: migration 0012 creates partial indexes on positions and measurements; on the local benchmark database (73 GB) that scan takes minutes once. Production servers start from an empty schema.

### 2026-09-04, phase 13 (Claude)

- Decisions D84 to D87 asked and taken: everything with a public API built now (The Things Stack, Actility, EarthRanger direct, icons, dashboards, MCP writes), Movebank as an export format, WildlifeNL and FerusTracker deferred.
- Backend: the TTS adapter (webhook documents to messages with gateway receptions, downlinks with correlation ids, gateway and device sync), Actility as a subclass of the KPN adapter, downlink events matched through provider metadata, the direct EarthRanger connector with in-place updates through the previous delivery id, the Movebank event and reference datasets, migration 0013 (server settings, pending MCP actions, project icons, dashboards), the manual event endpoint, SVG validation, dashboards, the AI action policy and endpoint with the confirmation flow, the write scopes and the MCP write tools.
- Frontend: Dashboards under Analyze with saved view, map, alerts, events and status tiles; custom icons in project settings with the icon store; the AI clients policy page; Movebank datasets in the export dialog.
- Verified: adapter, connector, platform API and MCP tests, lint, mypy, frontend lint, typecheck and tests, strict docs build.
- Open: live checks with a The Things Stack application, a ThingPark deployment and an EarthRanger site; WildlifeNL and FerusTracker when access exists; Cloudloop's, TTS's and EarthRanger's deep link paths are guesses until seen live.

### 2026-09-04, phase 13 addendum: WildlifeNL, FerusTracker and CRA IoT (Claude)

- Phase 13 committed and pushed (3d5fe4f, CI green). Tim sent the WildlifeNL API repository (UtrechtUniversity/wildlifenl, MPL-2.0, Go with huma; Postgres and InfluxDB), which corrects D84's assumption that the platform is EarthRanger based.
- D88 asked and taken: positions and temperatures as borne sensor readings, camera trap detections as detections, the device identity as the sensor id. Built `connectors/wildlifenl.py` with species resolution by name, the role check in the connection test, `DeliveryItem.device_identity`, tests, the runbook and the plan and changelog entries.
- FerusTracker: ferustracker.nl is a login page (version 11.48.0) without documentation and no API was found. Tim then shared the Node-RED flow that feeds it (an unauthenticated post per uplink with the decoded fields as `objectJSON`); D89 records the connector built from it, with the assumptions to confirm live listed in its runbook.
- CRA IoT (portal.iot.cra.cz), asked for by Tim the same evening: built from the platform's public documentation repository and Swagger as `adapters/cra_iot` (D90); its message is the LORIOT format in an envelope, downlinks and devices go through the REST API with single sign-on tokens.
- Open: WildlifeNL's API URL and a data-system account, FerusTracker's site value and a look at the platform, and a CRA IoT account with a LoRa device, for the live checks.

### 2026-09-04, phase 14 (Claude)

- Decisions D91 to D94 asked and taken: reduced-scale benchmark on the dev server, organizations as grouping, translation-ready English-only frontend, full security audit with application-level throttling.
- Security: `shared/ratelimit.py` and the API middleware (login, registration, password reset, token, webhook and AI action windows on Redis, 429 with Retry-After, `RATE_LIMIT_*` settings), the access matrix test over every OpenAPI operation with four callers, one finding fixed (curation permissions were checked after body validation), `pip-audit` and `npm audit` in CI with a weekly schedule, `docs/operations/security.md`.
- Docs CI: `scripts/docs_check.py` (internal links and anchors in the built site, Mermaid fences, the MCP tool reference against the server's tools) in the docs job.
- Organizations: admin CRUD, `organization_id` on projects (server admins move projects), the filter, the Projects page card and column, the project settings control, docs.
- Release process guide; the update and deployment guides brought current.
- Translation layer: i18next with the English catalogue (860 strings, extracted by a codemod over 57 files and by hand where sentences mixed text and values), the lint rule, the catalogue check in CI, the language switch in the sidebar, the frontend conventions.
- Benchmark generator rewritten to write in time order with a barrier between workers and `--compress`; proven at scale 0.005 on the dev server (all but one chunk compressed while loading); the reset lifts TimescaleDB's decompression limit; the 0.2 generation is running there.
- Verified: ruff, mypy, 337 backend tests, frontend lint, typecheck, catalogue check, tests and build, strict docs build, docs check, the rebuilt stack (throttle headers, organizations) and a clean UI sweep.
- Open: the benchmark run and results page; `VERSION` v2.0.0 on Tim's word; the live checks of earlier phases.

### 2026-09-04, phase 14 exit criteria (Claude, while Tim slept)

- Developer criterion: a throwaway driver for a vendor GPS tracker written from `docs/devices/driver-interface.md` and its public manual alone (three payload layouts, positions, measurements, state, events, six downlink actions, golden tests over the manual's examples). Gaps the check found and closed in the guide: how a LoRaWAN frame reaches `event.frame`, that metric keys need a migration with `seed_sql()`, how control actions are declared, the fixture README rule, the docs page and navigation, and creating the device type. Removed on 2026-09-05 at Tim's request: the product focuses on OpenCollar, the guide keeps what the check taught.
- Operator criterion: the deployment drill above. Finding for the 2.0 release: until it is tagged, a docs-only deployment lands on v0.6.0 and fails the final security check on the frontend port; the changelog's Unreleased section already carries the fix.
- Benchmark generation on the dev server restarted at 21:27 UTC after the first run wrote into chunks compressed by the smoke test (the generator now decompresses the window first and recompresses chunks behind the frontier); about 2 million positions per 13 minutes with a flat disk footprint.

### 2026-09-05, phase 14 benchmark (Claude)

- Generation finished at 01:33 UTC: 44.2 million positions, 176.9 million measurements, 4.1 hours, 2.6 GB and 7.3 GB compressed, 52 of 53 chunks compressed during the load.
- The runner needed three fixes found on the server: a refused export answer crashed it, the login token expired during the 65 minute export job (re-login on 401), and a transient resolver failure on the droplet killed a poll (retry on network errors). Each cost one export job; the complete run then took 78 minutes (08:08 to 09:26 UTC).
- Results in `docs/operations/benchmarks.md` with the reading; scalability page updated. The dataset stays on the dev server (20 GB used of 154) until Tim decides; `generate.py --reset` removes it in minutes.
- The benchmark exports showed that finished export files were never removed (three of 4.9 GB on the dev server): the export service now sweeps expired files hourly, jobs become `expired`, migration 0014. The dev server's disk (43 GB used) frees itself a week after those jobs once the server runs this code.

### 2026-09-05, ChirpStack live check and what it taught (Claude)

- The first real network: Tim's ChirpStack v4 (chirpstack-dev4.smartparks.org) posts collar SP051307's uplinks to the dev server over its HTTP integration; the first live status uplink is a fixture with a golden test against ChirpStack's decoder. Found on the way: the adapter minted no webhook token (it counted as a pull source), the example config carried the local broker, the device link used an upper-case DevEUI, a data source could not be deleted from the page, and there was no place to watch what a source receives before a device exists.
- Built from those findings: Data sources, Traffic (per source) and Server admin, Traffic (inbound, outbound, commands, hourly summary); Test connection and Sync devices; delete; a source modelled as its channels with the form's guidance and a per-channel Status (messages received, the ingest connector state in Redis, the last API answer, capabilities held back until their channel is configured); MQTT reconnects with backoff.
- Tim's ruling: ChirpStack v4 is gRPC only. The adapter uses the `chirpstack-api` client (`api_url` grpcs://host:443 through an nginx `grpc_pass` location, or grpc://host:8080); the REST gateway path and compose service are gone; the local bootstrap talks gRPC and was proven against the local stack (Test connection, Sync devices, Status all good).
- Open on Tim's side: the `grpc_pass` location on his nginx, a tenant API key, the source's `api_url` and `api_token`; then Request status proves the downlink path. The ChirpStack API secret was pasted into the chat and should be rotated.


### 2026-09-05, data source form per channel (Claude)

- Tim found the JSON configuration field of the data source form unclear: which value goes where, and no way to switch a channel off. The form now generates proper fields from the adapter's schema (switches, numbers, choices, lists, text with the schema's description as help) and groups them per channel: the channel's required fields starred, its optional settings beneath, its credentials as password fields; keys no channel names sit under General settings.
- Each channel has an on/off switch stored on the source (`DataSource.channels`, migration 0015) and enforced in the ingest runner, the webhook, command routing, Test connection and the syncs. A new source starts with the channels that still need input off; a switched-off channel hides its fields.
- Every adapter declares per channel its `config_keys`, `optional_keys`, `credential_keys` and `optional_credential_keys`; a test checks each named key exists in the adapter's schemas (which found the ChirpStack MQTT login missing from the credentials schema). Verified with screenshots of the new and edit forms on the rebuilt local stack.
