# Smart Parks Protect

Smart Parks Protect is a self-hosted operational data platform for Smart Parks deployments. It ingests data from field devices and IoT platforms, normalizes it into one domain of entities, devices, positions, measurements and events, and makes that data useful through a live map, a Data Explorer, exports, a rules engine, device control and outbound integrations such as EarthRanger.

Status: pre-alpha. The repository foundation exists, nothing user-facing runs yet. Follow `PROJECT_PLAN.md` in the repository for what is being built and in which order.

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
