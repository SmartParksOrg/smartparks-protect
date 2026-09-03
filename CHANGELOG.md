# Changelog

All notable changes to Smart Parks Protect are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [semantic versioning](https://semver.org/). Servers run tagged releases, never `main`.

## Unreleased

### Added

- Connectivity and ingestion (phase 2): Redis Streams event bus with consumer groups, retry with backoff, dead letters and heartbeats; adapter and driver contracts with registries; generic HTTP webhook and generic MQTT adapters; generic JSON driver; ingest service and decoder service; source deliveries linking repeat deliveries to one canonical row; out-of-line payloads in MinIO above 64 KB; per-source webhook tokens; Needs Attention API for unknown identities, failed source events and dead letters; read endpoints for positions, source events and traces; one Docker image for all Python services; first server admin bootstrap command.
- Core domain and access control (phase 1): migration 0001 with every table, five hypertables with compression and retention, authentication by invitation with JWT, roles and permission keys, audit log, processing trace helper and error taxonomy, assignment resolution at canonical time, admin API for projects, members, invitations, entity types, entities, features, device types, devices, assignments, handover, external identities, data sources with encrypted credentials, metrics and CSV device import. API under `/api/v1`, bounded lists everywhere, `protect-migrate` compose service.
- Repository foundation (phase 0): uv workspace with exact pins, `shared` package (config, database, logger, version), API skeleton with `/api/health` and `/api/version`, frontend skeleton with the Smart Parks colours and logo, docker compose stack with a `chirpstack` profile, MkDocs documentation site with ADRs 0001 to 0006, AddaxAI Connect reuse audit, CI, `scripts/dev.sh`, commit-msg hook.
