# Getting started

Smart Parks Protect runs as a set of Docker containers: the database (PostgreSQL with
TimescaleDB and PostGIS), Redis, MinIO, the API, the workers (ingest, decoder, rules,
automation, integration, export), the MCP server and the frontend. This page brings a local
stack up with a simulated collar; [deployment](deployment.md) covers a server.

## Prerequisites

- Docker with Docker Compose v2
- For development: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 24

## Start the stack

```bash
git clone https://github.com/SmartParksOrg/smartparks-protect.git
cd smartparks-protect
cp .env.example .env                                  # set the secrets before any server use
docker compose --profile chirpstack up -d             # database, redis, minio, api, workers, frontend, local ChirpStack
scripts/dev.sh bootstrap-admin you@example.org        # prints the registration link for the first server admin
```

Open the link, create your account and sign in at <http://localhost:3000>. Registration is
by invitation only; the first server admin invites the rest under Server admin, Users.

## See data move

Let the bootstrap set up the local ChirpStack (tenant, application, device profile, gateway,
device) and the demo project (project, OpenCollar device type, device `SP05-sim` with its
DevEUI, entity `Rhino 14`), then start the simulator:

```bash
scripts/dev.sh chirpstack-bootstrap --demo --protect-email you@example.org --protect-password '...'
scripts/dev.sh simulate --application-id <id printed by the bootstrap> --count 20 --rate 2
```

The simulator publishes OpenCollar uplinks the way ChirpStack does: a GNSS position per
uplink and a status message every fifth. Open the live map of Demo park and watch the rhino
move. Traffic, traces and health are under Network and Server admin. Without `--demo` you
create the project, types, device and entity yourself under Server admin, or accept the
unknown DevEUI from Needs attention.

Endpoints: API docs <http://localhost:8000/api/docs>, health
<http://localhost:8000/api/health>, ChirpStack <http://localhost:8080> (admin / admin),
MinIO console <http://localhost:9001>.

## Where to go next

- A real network: the [integrations](../integrations/index.md) runbooks, one per platform.
- Rules, events, alerts and notifications: [rules](../rules/index.md).
- Analysis and export: [analytics](../analytics/index.md).
- AI clients over MCP: [MCP](../mcp/index.md).
- The [demonstration](demonstration.md) script walks the whole platform end to end.

## Interface language

The interface follows the browser's language when a catalogue for it exists and falls back
to English; the switch at the bottom of the sidebar overrides it. English is the only
language shipped today; adding one is a catalogue under `src/locales/` in the frontend
(decision D93).

## Development commands

`scripts/dev.sh` wraps the daily commands:

```bash
scripts/dev.sh up        # docker compose up -d
scripts/dev.sh test      # python tests, needs the stack running
scripts/dev.sh lint      # ruff, mypy, eslint, tsc
scripts/dev.sh openapi   # regenerate the OpenAPI schema and the frontend types
scripts/dev.sh docs      # build this documentation site
scripts/dev.sh sweep     # screenshot every page at three widths
```

See `DEVELOPERS.md` in the repository for how the code is organised.
