# Smart Parks Protect

Smart Parks Protect is a self-hosted operational data platform for Smart Parks deployments. It ingests data from field devices and IoT platforms, normalizes it into one domain of entities, devices, positions, measurements and events, and makes that data useful through a live map, a Data Explorer, exports, a rules engine, device control and outbound integrations such as EarthRanger.

Status: released, v2.6.0 on 2026-09-16 with phases 22 to 28 (connectivity and network locations, the live map's controls and its feed, one top bar and night mode, roles and a member's scope, the analysis modules movement, grazing and device performance with PDF reports, GNSS outliers, the expected fix interval and device settings known per device); see `CHANGELOG.md`. Follow `PROJECT_PLAN.md` in the repository for what is being built and in which order. This site is published from the `main` branch on every green build, so it describes the development server; a server on a release tag is described by that tag's `docs/` folder and its section of the changelog.

## Where to look

| Section | For whom | What it covers |
| --- | --- | --- |
| [Getting started](getting-started/index.md) | Everyone | Install, quick start, first project |
| [Concepts](concepts/index.md) | Users and developers | Device versus entity, assignments, data levels, timestamps |
| [Architecture](architecture/index.md) | Developers | Services, data model, processing pipeline, scalability |
| [Devices](devices/index.md) | Developers and operators | Device drivers, OpenCollar, control actions |
| [Integrations](integrations/index.md) | Operators and developers | Connectivity adapters, runbooks per platform, outbound connectors |
| [Analytics](analytics/index.md) | Users | Data Explorer, export, curation |
| [Rules](rules/index.md) | Users | Rules, events, alerts, automations |
| [Administration](administration/index.md) | Administrators | Projects, users, permissions, notifications |
| [Operations](operations/index.md) | Operators | Deployment, updates, backup and recovery, observability |
| [Troubleshooting](troubleshooting/index.md) | Everyone | Where data stops and how to find out |
| [API](api/index.md) | Developers | REST and WebSocket reference |
| [MCP](mcp/index.md) | Developers | AI client access through the Model Context Protocol |
| [Decisions](adr/index.md) | Developers | Architecture decision records |
