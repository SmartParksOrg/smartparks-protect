# AddaxAI Connect reuse audit

Written on 2026-09-03 from a read-only pass over `/home/tim/apps/AddaxAI-Connect` (v0.9.0 plus 57 commits). Decision D1 in `PROJECT_PLAN.md`: Smart Parks Protect is written from scratch and mirrors patterns. This page records, per mechanism, whether the pattern is mirrored, adapted or left out, and why. It is the reading step; no code was copied.

Legend: **mirror** take the mechanism as is; **adapt** take the idea, change the shape; **leave out** do not carry over.

## Backend

| Mechanism | Verdict | What to take | What to change |
| --- | --- | --- | --- |
| Invitation flow | adapt | Invitation carries role and project membership; JWT `iat` versus `password_changed_at` invalidates old sessions on password change | No `request.state.db` middleware coupling; invitation email not globally unique; JWT lifetime from settings, not hardcoded |
| RBAC | mirror the shape, adapt the scope | `Role` enum, server admin as a user flag, one membership row per user and project, `require_server_admin` and `require_project_*` dependencies that read `project_id` from the path | Site scope enforced per endpoint by SQL string splicing; push scope into a query helper and add permission keys (`devices:control`, `data:curate`, ...) |
| Queue and workers | adapt | Heartbeat stamped before the pop so a wedged callback goes stale, tolerant heartbeat parsing, two readers of the same rule (health page and scheduled liveness alert), 15 minute staleness | Lists with `BRPOP` have no acknowledgement, retry or dead letter (a `TODO` where the dead letter should be); use Redis Streams with consumer groups (ADR 0004) |
| Logging | mirror | Structured JSON logger with context variables for correlation ids, kwargs become fields, request id middleware sets `X-Request-ID` | Accept an inbound `X-Request-ID`; set `user_id` from the auth dependency; use the standard library instead of `python-json-logger` |
| Notification workers | adapt | One coordinator plus thin channel workers, a log row written before queueing, per-integration health stamps (`last_sent_at`, `last_error`, `health_status`) | Add retry with backoff and a dead letter; "logged as failed and dropped" is not acceptable for alerts |
| Shared package | adapt | Installable `shared` package as the single source of pins, services import `from shared...` | Split the 50 KB `models.py` into a package, cache `get_settings`, drop the sync engine, put shared Pydantic schemas in `shared/schemas/` |
| Alembic | adapt | Synchronous migrations with `NullPool`, date-prefixed descriptive names, migrations run as a command not at startup | Drop the stale `include_object` whitelist that silently skips most tables in autogenerate; no backfill scripts inside the migration script; restart the API after migrations because asyncpg caches prepared statements |
| Testing | adapt | Environment set before imports in the root `conftest.py`, strict asyncio mode, `pip check` as a CI gate (here `uv sync --frozen`) | No database tests at all in AddaxAI Connect; here API tests run against a real Postgres, Redis and MinIO |
| Versioning | adapt | `VERSION` file written before the tag, copied into the image, exposed with the commit hash on `/api/version`, servers run tags | Add a `CHANGELOG.md` and a release script; there is no changelog in AddaxAI Connect |

Dependency notes: AddaxAI Connect pins FastAPI 0.141, SQLAlchemy 2.0.23, Pydantic 2.13, FastAPI-Users 15, redis-py 5.0.1 (pinned because redis-py 8 changed the socket timeout), Python 3.11, no uv, no lockfile, no ruff, no mypy.

## Tooling and deployment

| Mechanism | Verdict | What to take | What to change |
| --- | --- | --- | --- |
| docker-compose.yml | mirror structure, adapt storage | Profiles, `depends_on: condition: service_healthy` everywhere, one named network, tuned Postgres flags with reasons, `${VAR:-default}` interpolation, MinIO ports bound to localhost | Named volumes instead of bind mounts under `./data`; pin the MinIO image (AddaxAI runs `latest`); bind the API port to localhost |
| Dockerfiles | mirror ordering, adapt toolchain | Dependency metadata before source so a code change does not reinstall dependencies (a 26 minute outage taught this); resolver check as a separate step | uv with a lockfile instead of pip; non-root user later |
| `.env.example` | adapt | Grouped variables, derived versus input values | AddaxAI has no root `.env.example` (the contract lives in the Ansible template); this repo ships one so it runs without Ansible |
| Scripts | mirror `verify-server.sh` and `test-update.sh`, adapt the rest | A read-only pass/fail gate after every update or restore: containers versus `docker compose config --services`, Alembic head, health with a time budget, endpoint budgets, config regressions, error log count | Add a task runner (`scripts/dev.sh`) and linters; AddaxAI has neither |
| CI | mirror matrix, adapt content | One job per test directory with `fail-fast: false`, Python version equal to the image, `npm ci` not `npm install`, Dependabot security-only updates with grouped packages | Add ruff, mypy, eslint and `mkdocs build --strict`; add database and Redis service containers |
| Ansible | mirror | Multi-host guard in `pre_tasks`, tag-resolution deploy that ignores pre-release tags, sshd hardening in `01-` drop-in with drift check, unattended upgrades with security origins only, fail2ban on sshd only, `.env.j2` plus `import-host-vars.sh` round trip, gitignore and vault split | Non-interactive TLS issue; the SSL role's relative template path |
| Backup and restore | mirror, one addition | Dump piped straight to remote storage, one prefix-scoped key per server with delete-version withheld, versioned retention, `.restore-in-progress` and `.fresh-server` interlocks, status in Redis with TTL read by the health page | Encrypt the dump client-side before upload |
| Git hooks | mirror hook, adapt install | `commit-msg` strips assistant trailers (decision D28) | Nothing installs it in AddaxAI Connect; here `CONTRIBUTING.md` and `scripts/dev.sh hooks` set `core.hooksPath` |
| MkDocs | mirror structure, adapt pipeline | Material theme, custom palette, nav by audience | Pin `mkdocs-material`, build with `--strict` on every push, not only on merge |
| Root files | mirror README shape and `VERSION` discipline | Sentence-case headings, badges, hero, short sections | Add `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, which AddaxAI Connect lacks |

## Frontend

AddaxAI Connect is React 19, Vite, Leaflet, Chart.js, axios and React Context. Six of the libraries planned here (MapLibre native, ECharts, Vitest, Playwright test runner, React Hook Form, Zod) have no working precedent there: React Hook Form and Zod are installed but never imported.

| Mechanism | Verdict | What to take | What to change |
| --- | --- | --- | --- |
| package.json and build | adapt | `build` runs the type check before `vite build`, so a type error fails the image | Own library set; add ESLint and Vitest (absent there) |
| tsconfig and Vite | adapt | Strict flags, `VITE_PROXY_TARGET` for a local dev server against a remote API | `@/*` path alias from day one (every import there is relative); config in TypeScript |
| App shell | adapt | `/projects/:projectId/*` nesting, `?from=` return path, invitation token validation before registration | Real role guard components, lazy routes, project switcher on shadcn `Popover` |
| Auth state | adapt | Bearer attached by an interceptor, 401 redirects with return path, password change returns a fresh token | Token in one Zustand store, router navigation instead of `window.location`, decide on refresh tokens up front |
| API client | adapt | Per-domain typed modules, invalidate plus toast on mutation | Typed `fetch` wrapper instead of axios, a query key factory, types from OpenAPI |
| Zustand | adapt | The one store there (bulk upload) is the right use: work that must survive unmounts; filters live in the URL | Auth and selected project as stores, not Context |
| Forms | leave out | Nothing to take: forms are `useState` per field | React Hook Form with Zod from the start |
| Map | adapt concepts, leave out code | Shared `MapMetric` abstraction across points, clusters and hexbins, persisted base layer choice, hollow marker for "covered, nothing seen", WebGL2 check | MapLibre native clustering and layers instead of Leaflet plugins |
| Charts | adapt | Chart owns its query with an `enabled` guard, top-N cap, height from row count, header comment with the design reason | ECharts; colours from theme tokens, not hex literals |
| `FRONTEND_CONVENTIONS.md` | mirror document, adapt content | Z-index ladder (0 map, 10-30 sticky, 40 backdrop, 50 overlays, 60 status strip, 70 fullscreen map, 90 install hint, 100 toasts), responsive rules (390/768/1440, no horizontal page scroll, 16px inputs on touch, safe-area on body), colour system | Prune "to be implemented" sections; the document there drifted from the code |
| Tailwind and theme | adapt | Token map on CSS variables, `cn()` helper, mobile and PWA global rules, attribution collapse trick | Real shadcn/ui with `components.json`; decide dark mode explicitly (stray `dark:` classes there with no dark palette) |
| Tests | adapt strongly | The screenshot sweep: login, refuse to run against anything but a dev server, three viewports, flag horizontal overflow and console errors, screenshots per route | Rebuild on `@playwright/test` with routes derived from the router; add Vitest |
| Nginx | mirror | Two-stage build, `/assets/` immutable for a year, `index.html` `no-cache`, SPA `try_files`, `/api` and `/ws` proxies | Add gzip and security headers in the container (AddaxAI relies on the host proxy) |

## What this repository does differently from day one

- uv workspace with one lockfile, ruff and mypy strict, Vitest and ESLint.
- Redis Streams with acknowledgement, retry and dead letter.
- API tests against real infrastructure.
- Named Docker volumes and pinned images.
- Root `.env.example`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- The commit hook is installed by the documented setup step.
