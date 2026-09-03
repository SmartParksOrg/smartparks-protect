# Contributing

Thanks for helping build Smart Parks Protect. This page explains how work is organised. The house style is in `CONVENTIONS.md`, the code is explained in `DEVELOPERS.md`, and the roadmap is in `PROJECT_PLAN.md`.

## Before you start

1. Read `CONVENTIONS.md`. Crash early, type hints everywhere, no em dashes, natural capitalisation, no quick fixes.
2. Read the active phase in `PROJECT_PLAN.md`. Work follows the plan; if you want something that is not in it, open an issue first.
3. Install the git hook once per clone. It strips assistant co-author lines from commit messages:

```bash
git config core.hooksPath .githooks
```

## Development setup

```bash
cp .env.example .env
docker compose up -d
uv sync
cd services/frontend && npm ci
```

`scripts/dev.sh` wraps the daily commands: `up`, `down`, `logs`, `migrate`, `test`, `lint`, `docs`. See `DEVELOPERS.md` for details.

## Branches and commits

- Work on `main` for normal changes. Ask before opening a branch; branches are for large rewrites.
- Commit messages: a short imperative first line, a blank line, then why the change is needed. No co-author trailers.
- Tick the matching checkbox in `PROJECT_PLAN.md` in the same commit as the code.

## Definition of done

A change is done when all of these hold:

- Code follows `CONVENTIONS.md` and passes `ruff`, `mypy` and the tests.
- Tests exist for new behaviour. Adapters, drivers and rules are tested with recorded fixtures under `tests/fixtures/payloads/`, each with a note where the payload came from.
- Documentation is updated in the same commit: `DEVELOPERS.md` for mechanisms, `docs/` for users and operators, an ADR in `docs/adr/` for architectural choices, `CHANGELOG.md` under Unreleased.
- Every user-facing list, map, chart and export endpoint has an explicit bound.
- Access control is checked on every new endpoint, with a test per role.
- No provider-specific code outside `shared/connectivity/adapters/` and no device-specific code outside `shared/device_drivers/`.

## Adding an adapter or a driver

Extension documentation lives under `docs/integrations/` and `docs/devices/`. Start from the skeletons in `examples/` once they exist (phase 2). Every adapter and driver ships with fixtures, a runbook and an entry in the registry.

## Reporting bugs

Open a GitHub issue with the version (`/api/version`), what you did, what you expected and what happened. Attach the processing trace id when the problem is about data that did not arrive or was wrong. Security problems go through `SECURITY.md`, not the issue tracker.
