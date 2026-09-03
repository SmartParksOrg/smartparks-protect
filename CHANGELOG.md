# Changelog

All notable changes to Smart Parks Protect are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [semantic versioning](https://semver.org/). Servers run tagged releases, never `main`.

## Unreleased

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
