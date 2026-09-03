# Getting started

Smart Parks Protect runs as a set of Docker containers. This page grows into the quick start at the end of phase 3. Today it starts the infrastructure, an empty API and a placeholder frontend.

## Prerequisites

- Docker with Docker Compose v2
- For development: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 24

## Start the stack

```bash
git clone https://github.com/SmartParksOrg/smartparks-protect.git
cd smartparks-protect
cp .env.example .env
docker compose up -d
```

Then open:

- Frontend: <http://localhost:3000>
- API documentation: <http://localhost:8000/api/docs>
- Health: <http://localhost:8000/api/health>
- MinIO console: <http://localhost:9001>

`docker compose --profile chirpstack up -d` adds a local ChirpStack (LoRaWAN network server) on <http://localhost:8080>, used from phase 3 to test OpenCollar uplinks end to end.

## Development commands

`scripts/dev.sh` wraps the daily commands:

```bash
scripts/dev.sh up        # docker compose up -d
scripts/dev.sh test      # python tests, needs the stack running
scripts/dev.sh lint      # ruff, mypy, eslint, tsc
scripts/dev.sh docs      # build this documentation site
```

See `DEVELOPERS.md` in the repository for how the code is organised.
