# Changelog

All notable changes to Smart Parks Protect are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [semantic versioning](https://semver.org/). Servers run tagged releases, never `main`.

## Unreleased

Observability, System Health, backup and disaster recovery (phase 10), proven on the dev server; multi-path OpenCollar acquisition (phase 11): Web Bluetooth, raw log files and Cloudloop/Iridium, built from documentation and the local stack.

### Added

- Multi-path OpenCollar (architecture 25, ADR 0017): every frame read over Web Bluetooth, every line of a raw log file and every Iridium message is a delivery decoded through the normal pipeline, so one GNSS record delivered three ways is one position with three deliveries (verified by a test). Built-in data sources "Browser (WebBLE)" and "Log file upload" (migration 0011).
- Raw log files as managed assets (decision D77): upload on the device page, SHA-256 duplicate detection, status and counts (frames, malformed, records found, new, known through another path), period, firmware and decoder version, the file's trace, download of the original, decode again; the `device_log_files` table, `POST /devices/{id}/log-files`, the file processing worker in the decoder service, `LOG_FILE_MAX_BYTES` and `LOG_FILE_BATCH_SIZE`.
- Web Bluetooth (decision D76): our own implementation of the OpenCollar BLE protocol in the frontend (Nordic UART, `[port][msg_id][len][data]`); the card "Nearby over Bluetooth" connects, shows status, reads and writes every setting of the protocol catalogue (`GET /devices/{id}/driver-catalog`, generated from the research document), downloads and erases the flash log, and syncs every received frame as a log file of channel `webble` (`POST /devices/{id}/log-files/ble-sync`).
- Command routes (decision D79): `GET /devices/{id}/routes`, a route choice in the control dialog with the most recently seen network route preselected, the WebBLE route while the collar is connected in this browser (`POST /devices/{id}/routes/webble`), commands written by the browser with `POST /commands/{id}/browser-result`, confirmations through the synced frames. Adapters can declare `requires_client`; such routes are never selected automatically.
- Cloudloop adapter (decision D78): the Lingo JSON webhook (and the deprecated Core shape) as Iridium source events with the satellite session time apart from the record time, the IMEI as identity with the thing id as attribute, `Data/DoSendSbdMessage` commands with the collar's satellite framing, `Data/GetThings` management sync, `Platform/Ping` test; webhooks may carry the token as `?token=` for adapters that declare it and may restrict caller addresses (`allowed_source_ips`).
- Deliveries per canonical record with a channel filter: `GET /deliveries?canonical_type=&canonical_id=`, the "deliveries" view on the device page and in the source event dialog.
- Docs: OpenCollar over Web Bluetooth, raw log files, the Cloudloop runbook, ADR 0017.

- Backups (architecture 28, ADR 0016): pgBackRest in the database container with continuous WAL archiving and a weekly full plus hourly incremental backup to an encrypted S3-compatible repository; `mc mirror` of the MinIO buckets to the backup bucket; the `backup_runs` table (migration 0010) recorded by `scripts/backup.sh` through `protect_api.backup`; an integrity check of referenced objects; `scripts/restore-verify.sh`, a weekly restore into an isolated compose project with health and row checks; `scripts/restore.sh` for clean-server and point-in-time recovery; the Backup and recovery page for server admins; `SYSTEM_BACKUP` alerts for failed or stale backups, WAL archiving and restore tests; the Ansible schedule and host variables; guides for backup and recovery and for restore.
- Technical telemetry (architecture 26.8): OpenTelemetry traces and metrics from every service over OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (FastAPI, SQLAlchemy, httpx, redis, one span and two metrics per bus message, the processing trace id on spans); the compose profile `observability` with Grafana, Tempo, Prometheus and Loki in one container; an observability guide.
- System Health per area (architecture 26.2): ingestion, decoding (failures by error code, duplicate rate), rules and automation, integrations, device control, exports, backup and recovery, each with indicators and drill-down links.
- Trace explorer timeline (architecture 26.3) and a trace link on Data Explorer rows; trace retention per class (architecture 26.9) applied daily by the rules service with `TRACE_RETENTION_*`.
- Troubleshooting guide.

### Fixed

- From the first playbook runs on a server: the sshd drift check accepts `sshd -T`'s `without-password`; the frontend port binds to localhost (Docker bypasses ufw); the security check counts passes and no longer fails its ssh test under `pipefail`; pending handlers run before the final check; the deployed commit reaches the image build.
- The database container runs an init process as PID 1: with PostgreSQL as PID 1, pgBackRest's asynchronous archive process was reparented to the postmaster and its exit restarted the cluster every ten seconds.
- Restores follow the timeline of the backup set, and `scripts/restore.sh --test` keeps a drill server from archiving into the production stanza; a drill had made a later restore follow its own timeline.
- `scripts/verify-server.sh` checks the integration worker's heartbeat as well.

## v0.6.0, 2026-09-04

Production LoRaWAN networks and the dev server (phase 7), integrations, Traccar, AddaxAI Connect and gateways (phase 8), and the MCP server for AI clients (phase 9), built from documentation and the local stack; live verification pending.

### Added

- MCP server for AI clients (ADR 0015, architecture 27): the `protect-mcp` service at `/mcp` (streamable HTTP, stateless) with read-only, bounded tools (`list_projects`, `search_entities`, `get_entity`, `get_device`, `get_latest_position`, `query_measurements`, `list_metrics`, `query_events`, `get_processing_trace`, `search_traces`, and `search` and `fetch` for ChatGPT), `smartparks://` resources and the prompts `analyze_device_health` and `investigate_missing_data`. It calls the API with the client's token and never the database.
- OAuth 2.1 authorization server in the API: metadata at `/.well-known/oauth-authorization-server`, authorize, token, registration and revocation endpoints from the MCP SDK under `/api/v1/oauth`, client id metadata documents and dynamic registration, PKCE, JWT access tokens with the MCP URL as audience and the read scopes of architecture 27.5, hashed and rotated refresh tokens, consent page `/oauth/consent`, Connected AI clients page with disconnect. Access tokens reach the API read-only within their scopes; every request is audited with the tool name (AI action policy: reads allowed, every write disabled).
- Migration 0009: `oauth_clients`, `oauth_authorization_codes`, `oauth_refresh_tokens`.
- `q` filter on the entity list (name contains).
- nginx routes for `/mcp` and the OAuth discovery documents, an MCP rate limit zone; `MCP_PUBLIC_URL`, `MCP_PORT`, `API_INTERNAL_URL` and the OAuth lifetimes in `.env.example`.
- Integration framework (ADR 0014): integrations per project with connector, encrypted credentials, filters (object types, entities, devices, event types, minimum severity, metric keys, freshness bound); one idempotent `integration_deliveries` row per (integration, object type, object id, object version) with the retry schedule on the row (30 s doubling to 6 h, 30 attempts), request, response, external id and trace; the `protect-integration` service (live path, delivery loop that isolates an unreachable target, backfill in batches with progress); API for integrations, connectors, the delivery log with inspection, retry, test sends and backfill; the Integrate section in the frontend.
- Outbound connectors: EarthRanger via Gundi (positions as observations with the entity as source, events in the `smartparks_protect_` namespace, subject and event type mapping, test event), signed webhook with `X-Protect-Delivery`, MQTT with a topic template.
- Traccar adapter: session login, the `/api/socket` websocket with the latest positions on every connect, positions, events and device status as generic JSON with the Traccar record under `raw`, Traccar's forwarding accepted on the webhook, `POST /api/commands/send` as the command proof of concept, device listing. Runbook.
- AddaxAI Connect inbound connector: a dedicated viewer account, `GET /api/images` polled newest first with a captured-at cursor, a daily rescan over an overlap window and a manual rescan from a date, detections filtered on category, species and confidence as `SPECIES_DETECTION` events with the camera's location and a link back. Runbook.
- Gateway registry: server-level `gateways` from receptions, ChirpStack gateway stats and connection state, and a sync against the platform's gateway list; project gateways with reception statistics, gateway detail with the devices heard, device connectivity with gateway diversity and best-gateway share; administrator overrides. Network, Gateways screen. Runbook.
- Generic JSON driver: events carry an optional point and description; `position`, `event`, `state` and `detection` source events decode; the `PLATFORM_COMMAND` control action.
- Polling cursors per data source (`data_source_cursors`) with `GET` and `POST /data-sources/{id}/cursor`.
- System health lists every worker; the lag check covers every consumer group of a topic.
- Migration 0008: `integrations`, `integration_deliveries`, `gateways`, `data_source_cursors`.
- Demonstration script (`docs/getting-started/demonstration.md`) with the local steps passing and the live steps recorded as pending.
- KPN LoRa (ThingPark) adapter: HTTP push of `DevEUI_uplink`, `DevEUI_downlink_Sent`, `DevEUI_location` and `DevEUI_notification` with LRR receptions; downlinks through the ThingPark downlink API in token or bearer mode. Runbook.
- LORIOT adapter: websocket application output with reconnect (`rx`, `gw`, `txd` frames), the HTTP output as a webhook, downlinks as `tx` frames over the same output. Runbook.
- Netmore adapter: the export format over HTTP push or the Netmore MQTT broker, downlink responses; a `platform` setting selects downlinks, queue and clear through the LoRaWAN Portal API (login token) or downlinks and clear through Netmore Connect (API key). Runbook.
- akenza.io adapter: webhook samples with the raw frame, the akenza device id as identity, downlinks through the akenza REST API. Runbook.
- `GET /data-sources/adapters`: every adapter with push flag, command support, channel, config schema and example, credential fields and setup hint; the data source form is built from it and the frontend names no provider. Webhook tokens are minted for every adapter that declares `push`.
- Provider boundary guard test over the backend and the frontend. Migration 0007 rewrites a column comment that named a provider.
- Ansible playbook and roles (security with sshd drift check, docker, nginx, ssl, dev-tools with release tag resolution, app-deploy, security-check), example inventory and variables, `scripts/verify-server.sh`, `scripts/security-status.sh`. Deployment and update guides.

### Fixed

- The provider boundary guard compiled its pattern with a literal backspace instead of a word boundary and matched nothing; it now checks the backend and the frontend for real.

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
