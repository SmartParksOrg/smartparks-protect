# Changelog

All notable changes to Smart Parks Protect are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [semantic versioning](https://semver.org/). Servers run tagged releases, never `main`.

## Unreleased

## v0.4.0, 2026-09-04

Device control through ChirpStack (phase 6).

### Added

- Control actions declared by drivers (`shared/control/actions.py`, ADR 0013): typed parameters as JSON schema, permission, confirmation policy, required capability, encoder, optional interpreter. OpenCollar declares `REQUEST_STATUS`, `REQUEST_POSITION`, `SET_GNSS_INTERVAL` and `RESET`.
- One command path (`shared/control/commands.py`): create, encode, route through the device's data sources, submit, a `command_executions` timeline and an audit-class trace; provider `txack`, `ack` and `log` events and device responses move the lifecycle; commands expire after the action's expiry. `command.updated` on the bus and the WebSocket.
- ChirpStack command connector over the REST API device queue, with queue read and flush.
- API: device actions with availability reasons, commands per device and per project, command detail, downlink queue.
- Automation action type `command`, sent to the event's device as the automation.
- Frontend: Actions menu and command history with the lifecycle timeline on the device page, the platform queue with flush, the Commands page under Control, command actions in the automation editor.
- Migration 0006: `commands`, `command_executions`.

## v0.3.0, 2026-09-04

Rules, events, alerts, automations and notifications (phase 5).

### Added

- Rules as versioned JSON documents (`shared/rules/schema.py`, ADR 0012): position, measurement, state and schedule triggers; threshold, geofence (enter, exit, inside, outside), no-data and window aggregate conditions with `all`, `any` and `not`; FOR duration; cooldown reminders; event template with severity and alert flag. Reserved condition types (`near`, `dwell`, `crossed`, `baseline`, `correlation`, `event_chain`) can be saved but not enabled. Six templates: geofence exit, geofence enter, speed limit inside an area, no data, battery low, possible immobility.
- Rules service (`protect-rules`): a stateful evaluator on `position.created`, `measurement.created` and `device.state_changed`, a scheduler for schedule rules, per-subject state in `rule_state`, each rule in its own transaction with failures on `rules.last_error` and a failed trace, a compact trace per fired rule. System checks every five minutes open and auto-resolve system alerts for stale workers, dead letters and consumer lag.
- Replay: test a saved version or a draft document over the project's history without side effects, bounded to 50,000 rows, 500 events and 5,000 schedule steps.
- Events and alerts: project and server-level lists newest first with a time cursor, event detail with deliveries, alert acknowledge and resolve with a note (viewers may act, `alerts:write`), the entity's open alert count, recent events on the live map with the event marker family and a detail dialog.
- Automation service (`protect-automation`): automations bind event types, severity, alert-only, entity and rule filters to actions; notify (email, Telegram) and signed webhook actions; one idempotent action delivery per action and event with attempts, response and trace; transient failures retried by the bus, stale events skipped by the automation's freshness bound; failed deliveries can be retried from the UI.
- Notifications: channel-neutral `shared/notifications` (render, email with the development guard, Telegram Bot API, dispatch); notification targets per project and at server level; Telegram chats linked with a `/start <code>` handled by the automation service's bot poller (decision D43); test messages; capabilities endpoint.
- Frontend: Rules (list, enable, editor with template picker, condition builder, JSON fallback, versions and test tab), Events, Alerts inbox, Automations with deliveries, Notification targets with the Telegram link dialog; server-admin pages for system alerts, automations and targets; events on the map.
- Migration 0005: `rule_state`, `automations`, `notification_targets`, `action_deliveries`; `events.project_id` and `alerts.project_id` nullable for system events; `rules.last_fired_at` and `rules.last_error`.
- Settings: `TELEGRAM_BOT_TOKEN`, `RULES_RELOAD_SECONDS`, `SYSTEM_CHECK_INTERVAL_SECONDS`; mail settings move to every Python service.

### Changed

- The API mailer sends through `shared.notifications.email`; the development guard lives there now.
- Project viewers hold `alerts:write`.

## v0.2.0, 2026-09-03

Analyze: the Data Explorer and exports as backend capabilities with their screens, the synthetic scale benchmark, and TimescaleDB confirmed at the decision gate.

### Added

- Data Explorer backend (phase 4): bucketed aggregates with automatic resolution from a fixed ladder, `mean`, `min`, `max`, `median`, `sum`, `count`, `first`, `last`, series, long and wide layouts, drill-down rows with source event and trace, metrics with data per project, saved views per project.
- Export as a backend capability: export jobs run by the new `protect-export` service into MinIO with progress, SHA-256 and reproducibility metadata; direct downloads up to 100,000 rows; CSV, XLSX (sheets split at the Excel limit), JSON, GeoJSON and GPX; datasets positions, measurements, source events and aggregates; timezone selection; reproduce a job.
- Data Explorer and Exports screens in the frontend: filter builder, ECharts line, scatter, bar, histogram and state timeline, table with drill-down to rows and source events, saved views, export dialog for direct downloads and jobs, job list with progress, download and reproduce.
- Benchmark scripts: synthetic dataset generator scalable to the reference envelope and a runner that writes `docs/operations/benchmarks.md`. TimescaleDB confirmed at the phase 4 gate (ADR 0003).
- Bootstrap `--demo` creates the demo project, device type, device and entity for the simulator; the simulator sends real OpenCollar frames by default.

### Fixed

- Bootstrap passed no API key to the Protect data source when it minted one.
- Cursor pagination on bigint keys.
- The bus handles batches in lanes per device (`BUS_CONCURRENCY`), which took one decoder from about 60 to about 90 events per second.

## v0.1.1, 2026-09-03

The v0.1.0 tag does not build the frontend on a clean checkout; use this tag instead.

### Fixed

- The `data/` ignore rule hid `services/frontend/src/components/data/DataTable.tsx` from git, so the tagged frontend did not compile. The rule now matches only the root data directory.
- MinIO buckets are created on first use, so the decoder works against a MinIO without the compose bucket setup (tests and CI).
- CI prints failed test names as workflow annotations.

## v0.1.0, 2026-09-03

First vertical slice: a simulated OpenCollar sends uplinks through a local ChirpStack, the OpenCollar driver decodes them, the entity appears on the live map, the traffic viewer shows raw and decoded data, the trace explorer shows the steps.

### Added

- Frontend (phase 3): app shell with login, invitation registration and password reset, project switcher, sidebar sections, role guards; live map with clustering, marker families, selection panel, tracks and live WebSocket updates; entities, devices and device detail with provenance and deep links; LoRaWAN traffic viewer; trace explorer; members and invitations; features drawn on the map; project settings; server admin screens for Needs Attention, system health, projects, users, devices with handover, data sources with webhook tokens, entity types, device types, metrics and the audit log; icon registry with a starter set; screenshot sweep.
- OpenCollar Edge driver from the public firmware and decoder, with golden tests and the full protocol research document.
- Phase 3 backend: ChirpStack adapter (MQTT events, gateway receptions, management through the REST API, deep link templates), ChirpStack compose profile with bootstrap and simulator scripts, metric registry seeds, LoRaWAN frame passed to drivers, network-level status and join handling, live map current state as GeoJSON and vector tiles, tracks with decimation, WebSocket live updates per project, LoRaWAN traffic view, trace search, basic system health.
- Connectivity and ingestion (phase 2): Redis Streams event bus with consumer groups, retry with backoff, dead letters and heartbeats; adapter and driver contracts with registries; generic HTTP webhook and generic MQTT adapters; generic JSON driver; ingest service and decoder service; source deliveries linking repeat deliveries to one canonical row; out-of-line payloads in MinIO above 64 KB; per-source webhook tokens; Needs Attention API for unknown identities, failed source events and dead letters; read endpoints for positions, source events and traces; one Docker image for all Python services; first server admin bootstrap command.
- Core domain and access control (phase 1): migration 0001 with every table, five hypertables with compression and retention, authentication by invitation with JWT, roles and permission keys, audit log, processing trace helper and error taxonomy, assignment resolution at canonical time, admin API for projects, members, invitations, entity types, entities, features, device types, devices, assignments, handover, external identities, data sources with encrypted credentials, metrics and CSV device import. API under `/api/v1`, bounded lists everywhere, `protect-migrate` compose service.
- Repository foundation (phase 0): uv workspace with exact pins, `shared` package (config, database, logger, version), API skeleton with `/api/health` and `/api/version`, frontend skeleton with the Smart Parks colours and logo, docker compose stack with a `chirpstack` profile, MkDocs documentation site with ADRs 0001 to 0006, AddaxAI Connect reuse audit, CI, `scripts/dev.sh`, commit-msg hook.
