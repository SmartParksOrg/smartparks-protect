# Smart Parks Protect

Smart Parks Protect is a self-hosted operational data platform for Smart Parks deployments. It ingests data from field devices and IoT platforms, normalizes it into one domain of entities, devices, positions, measurements and events, and makes that data useful through a live map, a Data Explorer, exports, a rules engine, device control and outbound integrations such as EarthRanger.

Status: released, v2.9.0 on 2026-09-19, closing phase 29 with the movement methods; v2.8.0 the same day brought contact tracing, the Sentinel-2 vegetation of the grazing analysis, a Dutch interface, the AWT driver, a battery type per device and gateways named by hand; see `CHANGELOG.md`. Since then `main`, which this site describes, carries phases 32 to 42: fence lines and traps, areas from files and the map, cardiac monitoring, moves with history and bulk actions, speed and course with a speeding rule, roads and an off-road rule, vehicle use, metric dashboard tiles, GeoParquet, habitat selection with hrHSA, and offload stations (the LP0 files from an SD card). Follow `PROJECT_PLAN.md` in the repository for what is being built and in which order. This site is published from the `main` branch on every green build, so it describes the development server; a server on a release tag is described by that tag's `docs/` folder and its section of the changelog.

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
