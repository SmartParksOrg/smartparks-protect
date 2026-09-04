<p align="center">
  <img src="docs/assets/logo-stacked.svg" alt="Smart Parks" width="220">
</p>

# Smart Parks Protect

Self-hosted operational data platform for [Smart Parks](https://www.smartparks.org) deployments. It connects field devices and IoT platforms to one Smart Parks domain and makes that data useful: a live map, analysis and export, a rules engine that turns observations into events and alerts, device control, and durable integrations with systems such as EarthRanger.

**Status: pre-release.** Releases v0.1.0 to v0.4.0 cover the live map, the Data Explorer and exports, rules, alerts, automations and device control on a local ChirpStack; the production LoRaWAN adapters, deployment automation, integrations and the MCP server for AI clients are built and wait for live verification. The roadmap is in [`PROJECT_PLAN.md`](PROJECT_PLAN.md).

## Core concepts

- **Devices are hardware, entities are what you care about.** An animal, vehicle, gate or weather station is an entity. A collar or sensor is a device. Time-bounded assignments link them, so hardware can be replaced without losing history.
- **Connectivity adapters** talk to external platforms (ChirpStack, KPN, LORIOT, Traccar, Cloudloop) and know nothing about devices.
- **Device drivers** decode device protocols and encode commands (OpenCollar first) and know nothing about networks.
- **Raw data is kept.** Every inbound message is stored as an immutable source event. Decoded and normalized data (positions, measurements, states, events) link back to it.
- **Canonical time is device time.** Records are attributed to the project and entity that owned the device when the record was generated, not when it arrived.
- **Every record has a trace.** A processing trace explains where a message, command, import or delivery went and where it stopped.
- **Queries are bounded.** Every map, chart, table and export endpoint has a viewport, time range, page or resolution limit.
- **Rules produce meaning.** Versioned, testable rules create events; automations act on them; alerts are events that need a person.
- **Control is bidirectional.** Commands go through one capability-driven path whether a person or an automation issues them.
- **Integrations are first class.** Outbound delivery is durable, retried and inspectable.

## Documentation

- [`Smart_Parks_Protect_Concept_Architecture.md`](Smart_Parks_Protect_Concept_Architecture.md): the concept architecture (draft v16), the source for everything here.
- [`PROJECT_PLAN.md`](PROJECT_PLAN.md): phases, decisions, definition of done, session log.
- [`DEVELOPERS.md`](DEVELOPERS.md): how the code works today.
- [`CONVENTIONS.md`](CONVENTIONS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md): how we work.
- `docs/`: the documentation site (`scripts/dev.sh docs` builds it).

## Quick start

Requirements: Docker with Compose v2. For development also [uv](https://docs.astral.sh/uv/) and Node 24.

```bash
git clone https://github.com/SmartParksOrg/smartparks-protect.git
cd smartparks-protect
cp .env.example .env                                  # set the secrets before any server use
docker compose --profile chirpstack up -d             # database, redis, minio, api, workers, frontend, local ChirpStack
scripts/dev.sh bootstrap-admin you@example.org        # prints the registration link for the first server admin
```

Open the link, create your account, sign in at <http://localhost:3000>. Then let the bootstrap set up the local ChirpStack (tenant, application, device profile, gateway, device) and the demo project in Protect (project, OpenCollar device type, device `SP05-sim` with its DevEUI, entity `Rhino 14`):

```bash
scripts/dev.sh chirpstack-bootstrap --demo --protect-email you@example.org --protect-password '...'
scripts/dev.sh simulate --application-id <id printed by the bootstrap> --count 20 --rate 2
```

The simulator publishes OpenCollar uplinks the way ChirpStack does: a GNSS position per uplink and a status message every fifth. Open the live map of Demo park and watch the rhino move. Traffic, traces and health are under Network and Server admin. Without `--demo` you create the project, types, device and entity yourself under Server admin, or accept the unknown DevEUI from Needs attention.

Endpoints: API docs <http://localhost:8000/api/docs>, health <http://localhost:8000/api/health>, ChirpStack <http://localhost:8080> (admin / admin), MinIO console <http://localhost:9001>.

## Relationship to AddaxAI Connect

[AddaxAI Connect](https://github.com/PetervanLunteren/AddaxAI-Connect) is the camera trap platform this project learns from. Smart Parks Protect is written from scratch and reuses patterns, not code; the [reuse audit](docs/architecture/addaxai-connect-reuse-audit.md) records what was taken. AddaxAI Connect detections will enter Smart Parks Protect as events through a standard inbound connector.

## Licence

MIT, see [`LICENSE`](LICENSE).
