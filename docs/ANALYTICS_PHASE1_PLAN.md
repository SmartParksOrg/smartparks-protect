# Analytics phase 1 plan: movement ecology and grazing

Status: reviewed and approved by Tim on 2026-09-14 on the branch `feature/analytics-movement-grazing`, with one change to the proposal: analyses run in a worker of their own from the start (decision A below). Implementation follows the roadmap on this branch. Nothing here is merged into `main`.

Where this document lives. The repository keeps plans as phases inside `PROJECT_PLAN.md` and its conventions ask for no redundant Markdown files (`CONVENTIONS.md`, rule 8). This file is the review artefact for the analytics branch, kept apart on purpose so that `main` stays untouched while the plan is discussed. When the plan is approved, its decisions move into `PROJECT_PLAN.md` as the rewritten phase 22 (the placeholder "Analysis as modules" already reserved for this work), the architectural choice becomes ADR 0031, and the user-facing parts become `docs/analytics/movement.md` and `docs/analytics/grazing.md` in the MkDocs nav. This file is then removed or shortened to a pointer. Until then it is not in the MkDocs nav and the docs build ignores it.

## 1. Executive summary

Smart Parks Protect gains an optional analysis area with two capabilities and nothing more:

1. Movement ecology: what tracked animals did in a period. Distance, displacement, speed, step length and turning angle, stationary and moving periods, day and night, residence time and revisitation on a grid, location clusters and hotspots, home range as a minimum convex polygon and as a kernel density estimate with 50 percent and 95 percent contours, comparison between subjects and between periods.
2. Grazing and rewilding: how tracked grazing animals use management areas over time. Time and animal-hours per area, per hectare and per day, relative use between areas, repeat visits, time since last use, grazing and rest cycles, comparison between areas, periods, seasons and herds. This level works on tracking data and management polygons alone. Landscape, environmental and management interpretation levels are designed as extension points only.

Everything else stays out of scope: contact analysis, habitat selection, biodiversity, animal health, patrol, fleet, infrastructure, water, human-wildlife conflict, connectivity, ecosystem condition, conservation outcomes and any environmental data platform. The architecture leaves them possible and plans none of them. A decision gate after movement and grazing are live (section 20) decides whether native analytics grows at all.

The one principle above all others: the Protect core (ingestion, decoding, the live map, entities, devices, events, rules, alerts, notifications, integrations, exports) must keep working when the analysis subsystem is disabled, absent, overloaded or broken. The design reaches that with logical isolation first: a separate Python package, separate tables, a job that runs in a worker of its own outside the request path and outside the ingest path, explicit bounds on every input, module flags, and a permission key. The worker is one more compose service from the same image, so it can be stopped, limited or removed without touching anything else. A separate service or store is not planned.

## 2. Current repository assessment

Based on the implementation as read on 2026-09-13 (commit `031b82a` on `main`), with documentation consulted second. Where the two disagree, the code wins and the disagreement is listed in 2.16.

### 2.1 Technology stack

- Backend: Python 3.12, FastAPI 0.141, SQLAlchemy 2 async with asyncpg, Alembic (head `0028`), pydantic 2, one uv workspace (`shared` plus `services/*`), ruff and strict mypy in CI.
- Database: PostgreSQL 17 with TimescaleDB 2.29 and PostGIS, from migration 0001 (ADR 0003). Hypertables: `source_events`, `positions`, `measurements`, `gateway_receptions`, `device_state_history`, chunked by 7 days (30 for state history), columnstore compression after 7 days, retention only on source events. No continuous aggregates exist; `docs/architecture/scalability.md` keeps them in reserve.
- Bus and workers: Redis Streams (ADR 0004, `shared/shared/bus.py`), one stream per topic, one consumer group per worker, exponential retry, dead letters, per-device lanes with `BUS_CONCURRENCY` (8). Worker base class `shared/shared/worker.py`. Workers: ingest, decoder, export, rules, automation, integration, plus the MCP HTTP service.
- Object storage: MinIO (`shared/shared/storage.py`), buckets `uploads`, `exports`, `device-log-files`, `pictures`.
- Frontend: React 19, Vite 8, TypeScript 6, Tailwind 4, shadcn over Radix, TanStack Query and Table, react-hook-form with zod, zustand, react-i18next, MapLibre GL 6, terra-draw, ECharts 6 through `echarts/core`, Vitest, Playwright as an ad hoc sweep script.
- Deployment: one Docker image for every Python service (`docker/python.Dockerfile`, `uv sync --all-packages`), `docker-compose.yml` with no resource limits, Ansible playbook with `env-refresh` and `sync-config` tags, images built on the server.

### 2.2 Frontend architecture

- Routes in `services/frontend/src/App.tsx`, lazy per page. Project routes under `/projects/:projectId/...` with an "Analyze" family already present: `analyze/explorer`, `analyze/exports`, `analyze/curation`, `analyze/dashboards`. Guarded routes wrap `RequireProjectPermission` (`components/layout/RequireAuth.tsx`).
- Navigation model in `components/layout/navigation.ts`: sections and items with an optional `permission` key, an `allScope` flag and a `phase` marker for items that exist in the plan but not yet in the code. `Sidebar.tsx` hides items and sections the caller cannot use.
- Permission gate: `usePermissions(projectId).can(key)` (`hooks/useProjects.ts`), keys from the project list (decision D188).
- State conventions (`services/frontend/FRONTEND_CONVENTIONS.md`): URL for anything bookmarkable, TanStack Query with `api/queryKeys.ts`, zustand for client state, per-user preferences through `hooks/usePreference.ts` (`PATCH /users/me`).
- Explore canvas (`pages/project/ExplorerPage.tsx`, phase 21): one selection of entities and devices over a period shown as table, chart or map, a canvas bound of 50,000 rows, saved views as URL parameters (decision D42). It computes nothing new by design (phase 21 goal).

### 2.3 Backend architecture

- API routers in `services/api/protect_api/routers/`: `map.py` (current state, tiles, tracks, heat, network locations, point at time), `data.py` (positions list), `records.py`, `analytics.py` (series over measurements, saved views), `exports.py`, `entities.py` (entities, features), `groups.py`, `platform.py` (dashboards), `projects.py`, `admin.py`, `network.py` (system status, health).
- Dependencies in `protect_api/deps.py`: `require_permission(key)` gives a `ProjectContext` with `permissions` and `visibility`; `require_scope_permission` gives a `ScopeContext` for the all-projects scope (ADR 0022). `protect_api/visibility.py` narrows every read to a member's scope (decision D186).
- Shared engines in `shared/shared/`: `analytics.py` (bucket ladder, `MAX_BUCKETS` 5,000, `MAX_SERIES` 20, `aggregate_statement`), `records.py` (one row per device moment), `exports/` (datasets, writers, runner, `DIRECT_MAX_ROWS` 100,000), `curation/effective.py` (`effective_time`, `effective_geom`, `visible`, `device_fix`, `sources_filter`), `curation/jobs.py` (bulk jobs on the export worker), `rules/` (evaluator with shapely and a haversine).
- The API sets a 120 second statement timeout (decision D147). Workers run their statements unbounded.

### 2.4 Database architecture

- `positions` (`shared/shared/models/timeseries.py`): `(id, time)` primary key, `device_id` not null, `project_id` and `entity_id` resolved at canonical time (ADR 0010), `record_type` (`gnss` or `network`), `canonical_key`, `geom` point 4326 with a GiST index, `altitude_m`, `speed_mps`, `heading_deg`, `accuracy_m`, `satellites`, `attributes`, and the curation overlay (`curated_time`, `curated_geom`, `valid`, `curated_fields`, `curation_version`). Indexes on `(device_id, time)`, `(entity_id, time)`, `(project_id, time)` and the partial curated time index.
- `device_entity_assignments` and `device_project_assignments` carry a `validity` range with an exclusion constraint; attribution is stored on the rows.
- `features`: `feature_type` in `site`, `zone`, `geofence`, `route`; `geom` of any type, SRID 4326, GiST; `attributes` JSONB; no area column and no validity in time. A circle is a polygon with `shape`, `centre` and `radius_m` in the attributes (ADR 0026).
- `entity_groups`: nested folders (ADR 0020), one group per entity, no membership history. The docs already call a group a herd.
- `entity_types`: a seeded catalogue with `livestock`, `cow`, `sheep`, `goat`, `horse`, `wild_horse`, `bison` among the wildlife sub-types (migration 0025).
- `projects.settings` is an empty JSONB bag with `timezone` beside it. `server_settings` holds one key today, the AI action policy.
- Nothing references a hypertable with a foreign key; references carry the id and the time as plain columns.

### 2.5 Geospatial capabilities

- Server side: PostGIS functions in SQL (`ST_Intersects`, `ST_MakeEnvelope`, `ST_TileEnvelope`, `ST_AsMVT`), geoalchemy2 types, shapely 2.1 for geometry conversion and the rule evaluator. Distance is a hand-written haversine in two places. numpy is present only as shapely's transitive dependency. No scipy, pandas, pyproj, geopandas, h3 or scikit-learn.
- Client side: `lib/geodesy.ts` (haversine, spherical polygon area, measuring while drawing), `components/map/networkLocations.ts` (`circlePolygon`), `components/map/layers.ts` (accuracy discs, tracks, heat, features, coverage).

### 2.6 Current map implementation

`components/map/useMap.ts` creates one MapLibre map per page; `layers.ts` follows the `ensureXLayers`, `setX`, `bindXClicks` pattern for entities, devices, tracks (`TrackLayer { entityId, kind, geometry, times }`, `setTracks`), heat (one MapLibre heatmap layer), features, events, gateways, coverage, network locations and accuracy discs. `MapPage.tsx` drives it from URL parameters (`entity`, `tracks`, `heat`, `layers`, `feed`, `point`, `state`). `MiniMap.tsx` is the small map on the entity and device pages.

### 2.7 Charts and dashboards

Two ECharts wrappers over `echarts/core`: `components/explore/ExploreChart.tsx` (line, scatter, bar, histogram, state timeline with a marked moment) and `components/analytics/SeriesChart.tsx` (dashboard and saved-view tiles). Theme through `lib/chartStyle.ts`. Dashboards (decision D86) are a grid of tiles of fixed kinds (`saved_view`, `map`, `alerts`, `events`, `entity_status`) stored as JSONB in `dashboards.tiles`, edited under `dashboards:write`. No free-form canvas and no report concept exist.

### 2.8 Time-series handling

Measurements aggregate through `time_bucket` with the ladder of decision D41 and the bound of decision D148 (answer coarser, never refuse). Tracks decimate to at most 10,000 points (`routers/map.py`). The heatmap reads at most 200 devices and 10,000 points over at most 90 days with a lateral join per device. Records page 1,000 rows by keyset. All readers take device fixes only unless asked (`sources=network` or `all`, decision D163) and the effective time and geometry of the curation overlay.

### 2.9 Entity, device, location, event and observation models

Entities (the animal, the person, the vehicle) are tracked by devices through timed assignments. Positions and measurements are the observations. Events are point-in-time facts with a geometry and a context, produced by people, AI clients or rules. Current state per entity and per device holds the newest position, its kind and, since migration 0028, its accuracy. There is no separate observation table beyond positions, measurements and events.

### 2.10 Job and background processing

The export worker (`services/export/protect_export/main.py`) is the reference for a bounded long job: it subscribes to `export.requested` and `curation.job_requested`, `shared/shared/exports/runner.py` sets the job row to running, streams rows with a server-side cursor (`yield_per` 2,000), writes a temporary file, uploads it to MinIO, records size and SHA-256, stores failures on the row and does not re-raise, and expires results after 7 days. The benchmark shows the worker at 107 to 129 MiB resident during a 22.6 million row export. The bus gives retries, dead letters, heartbeats and lag counts for free; a worker's name must be added by hand to five lists (`routers/network.py` twice, `services/rules/protect_rules/system_checks.py` twice, `scripts/verify-server.sh`).

### 2.11 Role and permission architecture

`shared/shared/permissions.py`: 21 keys in nine areas, four built-in roles as nested sets (viewer, operator, analyst, admin), custom roles per project, a member's scope of groups, entities and devices enforced on every read (ADR 0030). The area `exports_and_analysis` holds `exports:create`, `views:write` and `dashboards:write`; the analyst role has all three. Server admins have everything. The project list carries the caller's keys, so the interface gates on keys, never on role names.

### 2.12 Reporting and export capabilities

Datasets: records, positions, measurements, aggregates, source events, Movebank events and reference. Formats: CSV, XLSX, JSON, and for positions GeoJSON and GPX. Direct download up to 100,000 rows, a job above (decision D144). Jobs are reproducible from their parameters (`POST /exports/{id}/reproduce`) and carry metadata and a SHA-256. No GeoPackage writer and no report concept.

### 2.13 Likely extension points

- `PROJECT_PLAN.md` phase 22 already describes the shape this plan fills: modules as code, runs as rows, a job in the export worker or a worker of its own, `GET /projects/{id}/analyses`, a result page of blocks.
- The export runner and `ExportJob` are the template for `analysis_runs` and its runner.
- `shared/shared/curation/effective.py` is the single way to read positions correctly.
- The `features` table is the management polygon store the grazing level 1 needs.
- The navigation model's `permission` and `phase` fields, the `RequireProjectPermission` guard and `usePermissions` are the gating hooks.
- `layers.ts` and the ECharts wrappers are the display primitives.
- The export writers serve result exports.

### 2.14 Technical constraints

- One image and one virtualenv for all Python services: a dependency added anywhere ships everywhere. Scientific libraries therefore need a strong reason.
- mypy strict: an untyped library needs an `ignore_missing_imports` override.
- Every user-facing endpoint must have an explicit bound (architecture 13.10, definition of done).
- The reference envelope is 25,000 devices, 250 million positions, one billion measurements; the dev server runs the 0.2 scale dataset (44 million positions).
- The API statement timeout is 120 seconds; the sweep and the benchmark measure the live map at a 3 second budget.
- Every list endpoint takes `limit` (max 500) and returns `items` with `next_cursor`; a test fails otherwise.
- Every human string goes through `t()`; the catalogue is checked in CI.
- Compose declares no resource limits, so isolation is by design and by bounds, not by cgroups, until a limit is added.

### 2.15 Functionality that already exists and should be reused

Listed per topic in section 3.

### 2.16 Documentation against implementation

- `PROJECT_PLAN.md` "Target repository structure" lists `services/aggregation/`; no such service exists. Continuous aggregates are unused. Conclusion: no aggregation service is assumed here.
- The milestone table says phase 22 ships in v2.6.0; the status table and phase 23 say v2.7.0. This plan takes v2.7.0.
- `FRONTEND_CONVENTIONS.md` describes a Playwright smoke over every route; the implementation is `scripts/ui-sweep.mjs`, run by hand. New routes are picked up automatically because it parses `App.tsx`.
- The gate rule says pages behind a key sit under `RequireProjectPermission`; the four `analyze/*` routes are not wrapped, their pages gate the write actions internally. The new analysis pages follow the rule with a route guard.
- `docs/api/index.md` says Analyze pages need "nothing more" than the data; a new key `analysis:run` changes that for running analyses, not for reading results.
- The architecture document (section 30.2) defers "full scientific statistics library and advanced behavioral modeling". This plan stays inside that: PostGIS, shapely and numpy only.
- The CI matrix omits `ingest`; unrelated to this plan but worth knowing before adding a matrix entry.

## 3. Existing components to reuse

| Topic | Reuse | Where |
| --- | --- | --- |
| Tracking data | Positions with the curation overlay, device fixes by default, valid rows only | `shared/shared/curation/effective.py`, `shared/shared/models/timeseries.py` |
| Subject resolution | Entity to device assignments over time, groups with subgroups, the member's scope | `shared/shared/models/domain.py`, `protect_api/visibility.py` (`groups_and_subgroups`, `Visibility.narrow`) |
| Maps | The page map, track layers, features layers, heat, accuracy discs, the mini map | `components/map/useMap.ts`, `layers.ts`, `MiniMap.tsx` |
| Geospatial | PostGIS for containment, clustering (`ST_ClusterDBSCAN`) and area (`ST_Area` on geography); shapely for hulls and unions; the haversine already in the rule evaluator | `shared/shared/rules/evaluator.py` (constant), PostGIS |
| Areas | `features` of type `zone` or `geofence` drawn on the map or the Features page, circles as polygons | `routers/entities.py` (features), `components/map/draw.ts`, `FeaturesPage.tsx` |
| Jobs | The export worker, the export runner pattern, bus retries and dead letters, heartbeats, system checks | `services/export`, `shared/shared/exports/runner.py`, `shared/shared/bus.py`, `system_checks.py` |
| Roles | Permission keys and areas, `require_permission`, the project list's keys, `usePermissions` | `shared/shared/permissions.py`, `deps.py`, `hooks/useProjects.ts` |
| Exports | Writers for CSV, XLSX, JSON, GeoJSON; the direct download path; the export job for raw positions | `shared/shared/exports/writers.py`, `routers/exports.py` |
| Charts | `echarts/core` wrappers and the theme | `components/analytics/SeriesChart.tsx`, `lib/chartStyle.ts` |
| UI | `PageHeader`, `Page`, `Callout`, `Field`, `DataTable` with `defaultHiddenSmall`, `ConfirmDialog`, `EmptyState`, `useMutationToast`, `usePages` | `components/common`, `components/data` |
| Settings pattern | A `Settings` field, `.env.example`, the compose anchor, `env.j2` | `shared/shared/config.py`, `docker-compose.yml` |
| Time zone | `projects.timezone` for day boundaries | `shared/shared/models/access.py` |
| Provenance | `trace_id`, `source_event_id` on rows, the export job's metadata and SHA-256 | `shared/shared/models/analytics.py` |

## 4. Core impact and isolation assessment

This section answers the core protection contract point by point.

Runtime impact. The API gains one router. Its endpoints create rows, read rows and count fixes; the count is bounded by the same indexes the tracks read uses and by the statement timeout. No API endpoint computes an analysis. The ingest, decoder, rules, automation and integration workers do not import the analysis package and subscribe to no analysis topic. The live map, the entity, device, event and rule endpoints are untouched. The frontend loads the analysis pages lazily, so the bundle a viewer without analysis downloads does not grow beyond the shared chunks.

Database impact. Two new tables in the `analysis_` namespace (section 6), both ordinary tables, no hypertable, no new column on `positions`, `measurements`, `entities`, `devices` or `features`. The analysis reads `positions` through the same indexes and the same effective-time expressions as tracks and exports. Writes go only to the analysis tables. Reads in the worker use a server-side cursor with `yield_per`, a per-run statement timeout set with `SET LOCAL statement_timeout`, and the fix bound of section 14, so a run cannot hold the hypertable or the connection pool. One run holds one connection.

Deployment impact. One more compose service, `analysis`, from the same image and env anchor, running `python -m protect_analysis.main`; one migration; the settings of section 16; the worker's name in the five lists that know workers (`routers/network.py` twice, `system_checks.py` twice, `scripts/verify-server.sh`), a `tests/analysis` directory and a CI matrix entry. The export worker is untouched. Stopping the `analysis` container stops analyses and nothing else.

Dependency impact. numpy becomes an explicit dependency of `shared`; it is already installed in every container as shapely's dependency, so the image does not grow. No scipy, pandas, geopandas, pyproj, scikit-learn or raster library. PostGIS does the spatial work and shapely the hulls, so nothing heavy enters the API or MCP runtime. A future module that needs more must justify it at the decision gate and may then move analysis into its own image (section 4, last paragraph).

Failure behaviour. A run that raises marks its own row failed with the error and does not re-raise, the way `run_export` does, so the bus does not retry a deterministic failure. A run that exceeds its timeout is cancelled by the worker and marked failed with `ANALYSIS_TIMEOUT`. A worker crash leaves the message pending; the bus reclaims it after the backoff and the run reports `failed` after the last attempt. The API reads the row; a missing or broken worker means runs stay queued and the page says so with the worker's heartbeat age, taken from the existing system status. Nothing else in the product waits for a run.

Resource isolation. The runs have a process of their own, so their CPU and memory never compete with exports or curation jobs inside one container, and a compose resource limit can be put on that one service when wanted. Concurrency is one run at a time per worker (a semaphore in the handler, independent of the bus lanes), a wall-clock timeout per run, a statement timeout per run, a maximum number of subjects, days and fixes per run, a maximum grid size for the density estimate, and cancellation checked between steps. The API keeps its 120 second statement timeout and never joins the analysis tables to the hypertables. Memory is bounded by construction: fixes stream in, per-subject arrays are freed after each subject, the density grid is at most 250 by 250 cells of float64, and a result document is capped in size before it is stored.

Feature disablement. `ANALYSIS_MODULES` (a comma list, default `movement,grazing`, empty disables everything) is read at startup by the API and the worker. A disabled module is absent from the module catalogue, its routes answer 404, its navigation items are hidden, and a queued run of a disabled module is marked failed with `MODULE_DISABLED` by the worker. Per project, `projects.settings.analysis_modules` (optional list) narrows the deployment's list. Per person, `analysis:run` decides who may start runs. Turning everything off leaves the navigation exactly as it is today.

Moving out later. Stage 2 is in place from the start (the worker of its own). Stage 3, if ever: the package `shared/shared/analysis/` reads through SQLAlchemy models only, writes only to `analysis_*` tables, and speaks to the rest through the bus and the two tables, so it can be given its own image with its own dependencies, or its own database with the two tables and a read replica of `positions`, without touching the core. This plan does not build stage 2 or 3.

## 5. Proposed phase 1 architecture

```
frontend  Analyze section: Movement, Grazing (lazy pages)
   |  POST/GET /projects/{id}/analyses, GET .../{run}/geometries, GET /analysis-modules
   v
API  routers/analyses.py  (validate, bound, narrow to scope, create row, publish)
   |  analysis.requested {run_id}                        ^ reads analysis_runs
   v                                                      |
bus  Redis stream                                          |
   |                                                       |
   v                                                       |
analysis worker  services/analysis, shared/shared/analysis/runner.py  |
   |  reads positions (effective time and geom, device fixes, valid), features, assignments
   |  computes with PostGIS, shapely, numpy
   v
analysis_runs (status, progress, result document)  analysis_geometries (result polygons)
```

Package layout, all new files:

```
shared/shared/analysis/
  __init__.py        registry: MODULES, enabled_modules(settings)
  base.py            AnalysisModule protocol, Parameters base, ResultDocument, Warning, Provenance
  limits.py          the bounds of section 14 as constants and a Settings mirror
  runner.py          run_analysis(session, run): status, timeout, progress, result, errors
  quality.py         data quality checks shared by both modules
  primitives/
    trajectory.py    load a subject's fixes as arrays, gaps, steps, speeds, turning angles
    spatial.py       containment per fix, area per polygon, clusters, grid cells
    homerange.py     MCP, KDE grid, isopleth polygons
    timeagg.py       interval weights, day and night, calendar buckets in the project time zone
  modules/
    movement.py      the movement module
    grazing.py       the grazing module
  environment.py     EnvironmentalDataProvider protocol and an empty registry (section 11)
services/analysis/protect_analysis/main.py   (the worker: subscribe, handler, cleanup loop)
services/analysis/pyproject.toml
services/api/protect_api/routers/analyses.py
services/api/protect_api/schemas/analysis.py
services/api/alembic/versions/0029_analysis_runs.py
services/frontend/src/pages/project/MovementPage.tsx
services/frontend/src/pages/project/GrazingPage.tsx
services/frontend/src/components/analysis/   (RunForm pieces, RunStatus, ResultMap, ResultCharts, ResultTable, WarningsCallout, RunList)
services/frontend/src/lib/analysis.ts        (URL state, result document types and helpers)
tests/shared/test_analysis_*.py, tests/api/test_analyses.py, tests/export/test_analysis_worker.py
```

Naming: the package is `analysis`, not `analytics`, because `shared/shared/analytics.py` and the `/analytics` router are the existing bucketing engine and the frontend calls that area "Analyze". A run is an "analysis" in the API and the interface.

Boundary rules, enforced by a test that imports the core modules and asserts none of them import `shared.analysis`:

- `shared.analysis` may import `shared.models`, `shared.curation.effective`, `shared.database`, `shared.storage`, `shared.bus`, `shared.config`, shapely and numpy.
- Nothing under `shared.ingest`, `shared.rules`, `shared.connectivity`, `shared.device_drivers`, `services/ingest`, `services/decoder`, `services/rules`, `services/automation`, `services/integration` imports `shared.analysis`.
- `shared.analysis` never writes to a table outside `analysis_*`.

## 6. Data model

Migration 0029. Two tables, both in the `analysis_` namespace, both ordinary tables with UUID keys.

`analysis_runs`

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid | primary key |
| project_id | uuid | FK projects, CASCADE |
| module | text | `movement` or `grazing`, check constraint |
| status | text | `queued`, `running`, `completed`, `failed`, `cancelled`, check constraint |
| name | text null | set when a person keeps the run |
| parameters | jsonb | the validated parameters, the module's pydantic model dumped |
| method_version | text | the module's version string at run time, for example `movement/1` |
| progress | smallint | 0 to 100 |
| cancel_requested | bool | set by the API, read by the runner between steps |
| input_count | int null | fixes read |
| excluded_count | int null | fixes dropped by the quality rules |
| result | jsonb null | the result document (section 8.4), capped at 4 MiB |
| result_version | int | schema version of the document, 1 |
| error_code | text null | `ANALYSIS_FAILED`, `ANALYSIS_TIMEOUT`, `MODULE_DISABLED`, `INPUT_TOO_LARGE` |
| error_message | text null | first 2,000 characters |
| created_by_user_id | uuid null | FK users, SET NULL |
| created_at, started_at, finished_at | timestamptz | |
| expires_at | timestamptz null | `finished_at + 30 days` unless kept (name set) |
| source_run_id | uuid null | FK self, SET NULL, when re-run from another run |
| trace_id | uuid null | for the log lines |

Indexes: `(project_id, created_at desc)`, `(project_id, module, status)`, partial `(expires_at) where expires_at is not null`.

`analysis_geometries`

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint identity | primary key |
| run_id | uuid | FK analysis_runs, CASCADE |
| kind | text | `mcp`, `kde`, `hotspot`, `cluster`, `area_use`, `track_summary` |
| subject_id | uuid null | the entity, or null for the herd |
| label | text | shown on the map |
| level | real null | 0.5 or 0.95 for isopleths |
| area_m2 | double precision null | from `ST_Area(geom::geography)` |
| geom | geometry(Geometry, 4326) | GiST index |
| properties | jsonb | small, for the popup |

Index `(run_id, kind)`. Result geometry lives here and not in the document so the map endpoint can serve GeoJSON by run and kind and the document stays small.

What is not added: no column on `positions` or the current states; no `analysis_definitions` table (a kept run with its parameters is the saved analysis; re-run creates a new row that points back through `source_run_id`); no report table; no dashboard tile kind (a link to a run is enough in phase 1); no environmental tables.

Core data stays authoritative and untouched: entities, devices, assignments, positions, measurements, events, features, groups, projects, source events, traces. Analysis data: `analysis_runs`, `analysis_geometries`. Both are regenerable from core data and the parameters; deleting them loses nothing that cannot be recomputed.

## 7. Job and execution architecture

Synchronous, in the API request, bounded like today:

- `GET /projects/{id}/analyses/estimate?module=&...`: counts the fixes the parameters would read, per subject, with the same filters, and answers the count, the days, the subjects, and which bound would be crossed. A count over the `(entity_id, time)` index stays within the 120 second timeout at the envelope; the tracks read counts the same way today.
- The result reads: `GET .../analyses/{run}` returns the stored document; `GET .../geometries` returns stored polygons; both are reads of small tables.
- The context map on the analysis page uses the existing `GET /tracks` (decimated to 5,000 points per subject) while the run is queued or running, so the person sees the tracks at once.

Asynchronous, in the worker: every calculation that produces derived data. There is no small-run shortcut in the API: a run over one animal and one day finishes in a second or two in the worker and the page polls every 3 seconds the way the exports page does. One path is simpler to bound, to test and to explain than two.

Lifecycle:

```
POST /analyses  -> queued (row, audit "analysis.created", publish analysis.requested)
worker handler  -> running (started_at) -> progress updates through a short session
                -> completed (result, geometries, finished_at, expires_at)
                -> failed (error_code, error_message)
POST .../cancel -> cancel_requested=true; queued becomes cancelled at once,
                   running becomes cancelled at the next step boundary
DELETE          -> the row and its geometries go (audit "analysis.deleted")
PATCH           -> name (keeps the run: expires_at cleared) or clears it
POST .../rerun  -> a new queued run with the same parameters, source_run_id set
cleanup loop    -> expired runs deleted hourly, in the analysis worker's background loop
```

The handler in the analysis worker (`services/analysis/protect_analysis/main.py`, built on `shared.worker.Worker` like the export worker):

```
async def on_analysis_requested(message):
    async with ANALYSIS_SLOT:  # asyncio.Semaphore(settings.analysis_concurrency)
        async with session_scope() as session:
            run = await session.get(AnalysisRun, run_id)
            if run is None or run.status != "queued":
                return  # idempotent on redelivery
            await run_analysis(session, run)  # never raises; stores failure on the row
```

`run_analysis` sets `SET LOCAL statement_timeout` to `analysis_statement_timeout_seconds` on the session, wraps the module's `run` in `asyncio.wait_for(..., analysis_timeout_seconds)`, passes a `progress(percent, step)` callback that writes through its own short session (the streaming session cannot commit, the export runner notes why), and checks `cancel_requested` between steps through that same short session.

Redelivery and idempotence: the handler returns without work when the row is not queued, so a message re-delivered after a crash does not run twice and does not overwrite a completed result. A run interrupted by a crash stays `running` until the reclaim; the runner marks a `running` row older than the timeout as `failed` with `ANALYSIS_TIMEOUT` when it sees it again.

## 8. Movement ecology design

### 8.1 Inputs

- Project, from the route.
- Subjects: 1 to 25 entities, chosen from the entities list with search, from a group (with subgroups) or from an entity type. Devices are not subjects in phase 1; a device's track belongs to the animals it tracked, and the assignment history already attributes each fix. A follow-up may add a device subject for collars that are not assigned.
- Period: a preset (7, 30, 90 days, a year) or from and to; at most 366 days. Optional comparison period of the same length or any length; at most one comparison.
- Options with defaults: gap threshold 4 hours (an interval longer than this is a gap, not movement), maximum plausible speed 15 m/s for wildlife and 5 m/s for livestock by default (fixes implying more are excluded and counted), stationary speed threshold 0.05 m/s over at least 30 minutes, grid cell 100 m for residence and hotspots, minimum absence for a revisit 12 hours, home range methods MCP (95 percent) and KDE (50 and 95 percent) on or off, KDE bandwidth automatic (reference bandwidth) or a value in metres, KDE grid up to 250 by 250 cells, day and night by sun elevation at the fix (a compact solar position formula in `timeagg.py`, no dependency) with the project time zone for calendar days.
- Fix filters, not options: device fixes only (`device_fix()`), `valid` rows, effective time and geometry, the subject's assignment windows.

### 8.2 Algorithms

All arithmetic on the sphere with the haversine and the existing earth radius; positions are 4326 and the areas involved are small.

- Steps: consecutive fixes per subject, ordered by effective time; step length (m), duration (s), speed (m/s). Steps longer than the gap threshold are gaps: excluded from distance, speed and residence, counted in the quality report.
- Distance travelled: the sum of step lengths of non-gap steps. Reported with the share of the period covered by non-gap steps, so a sparse track is not read as a short one.
- Displacement: straight-line distance from the first to the last fix, and the maximum distance from the first fix (net squared displacement is stored per fix for the chart).
- Speed: per step; summary as mean, median and 95th percentile; a histogram; an hour-of-day profile.
- Turning angle: the change of bearing between consecutive non-gap steps; a rose histogram of 16 bins.
- Stationary and moving: a step is stationary below the speed threshold; runs of stationary steps lasting at least the minimum are stationary periods; the rest is moving. Share of time in each, the number of stationary periods, their mean length.
- Day and night: each step is day, night or twilight by the sun elevation at its start; distance, speed and stationary share per class.
- Residence time and revisitation on a grid: each fix is snapped to a cell of the chosen size (a projected grid in the local UTM-like frame computed from the mean latitude, in Python); each cell accumulates the time weight of its fixes (half the interval to the previous and to the next fix, gaps capped); a visit ends when the subject has been outside the cell for longer than the minimum absence; the number of visits is the revisitation. Hotspots are the cells that together hold 50 percent of the time, reported as polygons.
- Location clusters: `ST_ClusterDBSCAN` in PostGIS over the subject's fixes with a distance of the grid cell and a minimum of 5 points, run in SQL so the fixes are not loaded twice; cluster convex hulls and their time share are geometries of kind `cluster`.
- Home range MCP: the convex hull (shapely) of the fixes inside the given percentile of distance from the centroid (95 by default); area in hectares from `ST_Area(geography)`.
- Home range KDE: a Gaussian kernel density on a grid of at most 250 by 250 cells covering the fixes plus three bandwidths; bandwidth by the reference rule (Silverman's, from the standard deviation of the coordinates and the count) or the given value; the 50 and 95 percent utilisation distributions are the smallest set of cells holding that share of the volume; the isopleth polygon is the union of those cells (shapely `unary_union`), simplified lightly. This is a cell-union isopleth, not a smoothed contour; the document says so, and a smoother contouring is a later improvement, not a dependency now.
- Trajectory summary: the first and last fix, the number of fixes, the sampling interval (median and 90th percentile), the days with data, per subject.
- Comparison: the same metrics for the comparison period, and a table subject by period; for groups, the per-subject rows plus a mean row with the standard deviation.

Deferred on purpose: Brownian bridges, dynamic Brownian bridges, autocorrelated KDE, state-space and hidden Markov models, behavioural classification. Each needs a library or a large amount of code and a validation the phase 1 users have not asked for.

### 8.3 Derived metrics

Per subject and period: fixes, days with data, median sampling interval, distance (km), mean daily distance, displacement (km), maximum displacement, mean speed, median speed, 95th percentile speed, stationary share, moving share, stationary periods, day distance, night distance, MCP 95 area (ha), KDE 50 area, KDE 95 area, KDE bandwidth used, hotspot count, cluster count, missing fix share, excluded fixes.

### 8.4 Result document

```json
{
  "version": 1,
  "module": "movement", "method_version": "movement/1",
  "subjects": [{"id": "...", "name": "...", "type": "..."}],
  "periods": [{"key": "main", "from": "...", "to": "..."}, {"key": "comparison", ...}],
  "summary": {"main": {"<subject>": {"distance_km": 12.3, "...": 0}}, "comparison": {...}},
  "tables": [{"key": "comparison", "columns": [...], "rows": [...]}],
  "charts": [
    {"key": "daily_distance", "kind": "line", "unit": "km", "series": [{"subject": "...", "period": "main", "data": [[ms, value]]}]},
    {"key": "speed_histogram", "kind": "bar", ...}, {"key": "hour_profile", ...}, {"key": "turning", "kind": "rose", ...}, {"key": "nsd", ...}
  ],
  "geometries": {"mcp": 3, "kde": 6, "hotspot": 14, "cluster": 9},
  "warnings": [{"code": "missing_fixes", "level": "warning", "subject": "...", "text": "22% of expected fixes are missing in this period."}],
  "provenance": {...}
}
```

Charts are data only; the frontend draws them with `echarts/core` (line, bar, a rose as a polar bar).

### 8.5 Map outputs

The analysis page map shows the subjects' tracks over the period (the existing tracks read), and toggles for the result layers read from `GET .../geometries?kind=`: MCP hulls, KDE 50 and 95 isopleths (translucent fills in the brand palette by subject), hotspot cells, cluster hulls. A click on a geometry opens a small panel with the label, the area and the time share. The layers follow the `ensureXLayers`, `setX` pattern in a new `components/map/analysisLayers.ts`.

### 8.6 Charts and tables

Daily distance per subject (line), speed histogram (bar), hour-of-day activity (bar), turning angle rose (polar bar), net squared displacement (line), and for the comparison a grouped bar of the chosen metric by subject and period. One summary table of the metrics of 8.3, subject by period, with `defaultHiddenSmall` on the secondary columns, and a CSV export of the same.

### 8.7 UI flow

Route `/projects/{id}/analyze/movement`, navigation item "Movement" under Analyze, shown when the project's modules include `movement`; the "Run" button needs `analysis:run`, reading needs `project:read`.

1. The form at the top: subjects (a multi-select with search and a "from group" and "by type" pick), period (preset or dates), comparison (off, previous period, custom), options in a collapsed "Method" section with the defaults visible. The URL carries the form (`entity`, `group`, `range`, `from`, `to`, `compare`, `gap`, `speed_max`, `cell`, `methods`), so a link reproduces a form.
2. The estimate line under the form: "3 animals, 90 days, about 41,000 fixes" and, when a bound is crossed, what to change. The Run button.
3. On Run: a run row appears in "Runs" (the last 20 runs of this module in the project, with status, progress and age) and the page switches to `?run=<id>`. The map shows the tracks at once; the result blocks fill in when the run completes; failures show the error and a "Run again" button.
4. The result: summary cards per subject, the map, the charts, the table, the warnings callout, and the actions "Keep" (name it), "Export" (CSV of the tables, GeoJSON of the geometries, XLSX of the tables), "Run again", "Delete".
5. Contextual entry: the entity page header gets "Analyse movement" (when the module is on and the person may run) that opens the page with the entity and the last 30 days filled in and does not run by itself.

On a phone the form folds to a sheet, the map takes the width, the table hides secondary columns, and the charts stack.

### 8.8 Data quality warnings

Computed by `quality.py` for both modules and shown as a callout above the results, with a "why" text per warning:

- Missing fixes: the expected count from the median sampling interval over the period against the actual count; a warning above 20 percent missing, a notice above 5.
- Gaps: the share of the period inside gaps; a warning above 25 percent, with the sentence "Large gaps make residence time and home range estimates unreliable."
- Irregular sampling: the 90th percentile interval more than three times the median.
- Impossible speeds: fixes excluded by the plausible speed, with the count.
- Duplicates: fixes at the same effective time for a subject are collapsed to one and counted.
- Timestamp anomalies: fixes with a device time ahead of ingestion beyond the clock tolerance are already invalid rows and are counted as excluded.
- GNSS quality: fixes with `accuracy_m` above 100 m or `satellites` below 4 where the fields exist, counted, not excluded, with a notice that the grid cell is smaller than the accuracy when that happens.
- Deployment changes: a subject that changed collar inside the period, with the date; a subject with no assignment in part of the period.
- Few fixes: fewer than 30 fixes for a subject makes home range and clusters unavailable for it, with the sentence on the card.

### 8.9 Exports

From the result: the summary and comparison tables as CSV or XLSX, the geometries as GeoJSON, the whole document as JSON, through `GET .../analyses/{run}/export?format=&what=` with the existing writers and the direct path (result sizes are far under the direct bound). The raw fixes of the run's subjects and period remain an export job of the positions dataset in GeoJSON or GPX, one click away from the result ("Export the fixes"), for QGIS, R or Python. GeoPackage is noted for later: a writer over the standard library's sqlite3 with shapely WKB is feasible without a dependency, but no user has asked yet.

### 8.10 Limitations, stated in the interface

- Distance from fixes underestimates the path between fixes; a coarser sampling means a shorter apparent distance. The document reports the sampling interval next to the distance.
- Speed is the mean speed over a step, not an instantaneous speed.
- KDE represents estimated space use and depends on the bandwidth and the grid; the isopleths are cell unions.
- MCP includes areas never visited between far fixes.
- Residence time on a regular grid depends on the cell size and is biased by irregular sampling.
- Day and night by sun elevation ignore the animal's own rhythm and cloud cover.
- Results describe the collared animals, not the population.

## 9. Grazing and rewilding design

### 9.1 Level 1, tracking-derived (this phase)

The question: how are tracked grazing animals using the management areas over time?

Inputs:

- Subjects: a herd, chosen as a group (with subgroups) or a set of entities, 1 to 100 animals, or an entity type (for example every cow); the same fix filters as movement.
- Management areas: 1 to 50 polygons chosen from the project's features of type `zone` or `geofence` (polygons and multipolygons; circles are polygons already). No new feature type is introduced: a management unit is a zone the person picks. A project may keep a naming convention or an attribute (`attributes.management.unit = true`) so the picker offers "all management units" as a preset; the analysis stores the chosen ids, so the convention is optional. Area per polygon from `ST_Area(geom::geography)` in hectares at run time, stored in the result.
- Period, at most 366 days; comparison period optional; seasons as named sub-periods when the person asks (a calendar split of the period into meteorological seasons by the project time zone).
- Weighting: `equal` (each animal counts one, the default), `attribute` (each entity's `attributes.<key>` numeric value, for example `livestock_unit` or `body_mass_kg`, with the animals lacking the value listed in a warning and counted as one), `metabolic` (body mass in the attribute raised to 0.75, normalised to the herd mean). Nothing is assumed silently: the document names the weighting, the key and the animals with defaults.
- Options: gap threshold 4 hours, interval attribution rule (see below), residence grid cell 100 m for the intensity map inside areas.

Algorithm:

- For each animal, the sequence of fixes over the period with the time weight per fix as in movement (half of each neighbouring interval, gaps capped at the threshold). The gap cap means a collar silent for a day does not put 24 animal-hours anywhere.
- Containment: one SQL statement joins the run's fixes to the chosen polygons with `ST_Contains` (GiST on both sides); a fix inside no polygon is "outside the areas"; a fix inside overlapping polygons counts in each and the overlap is reported.
- Per area and per animal: time (hours), weighted animal-hours, visits (a visit starts when the animal's fixes enter the area and ends after an absence longer than the minimum, 6 hours by default), mean visit length, first and last use, days used.
- Per area: animal-hours, animal-days (animal-hours divided by 24), animal-hours per hectare, animal-days per hectare, share of the herd's tracked time, animals that used it, use days, rest days (days without use), time since last use at the end of the period, and the longest rest.
- Relative grazing pressure: an area's animal-days per hectare divided by the herd's mean over all chosen areas, so 1.0 is average; shown with its rank.
- Spatial use intensity: the residence grid of movement, restricted to the chosen areas, as hotspot cells with the time weight, one geometry set per area.
- Grazing and rest cycles: a timeline per area of daily animal-hours; rest periods as runs of days below a threshold (default zero); the mean cycle length where the pattern repeats.
- Comparison: between areas (the table, sorted by pressure), between periods (the same table for the comparison period with the difference and the percentage change), between seasons (one table row per season), between herds (a second subject set, rows per herd).

### 9.2 Derived metrics

Per area and period: hectares, animal-hours, animal-days, animal-hours per hectare, animal-days per hectare, weighted animal-days per hectare, relative pressure, share of herd time, animals used, visits, mean visit hours, use days, rest days, longest rest days, last use, hours since last use, hotspot cells. Per herd: tracked animal-hours, share inside any area, share outside.

### 9.3 Area normalisation

Per hectare from the polygon's geographic area at run time; overlapping polygons are counted separately and the overlap hectares are listed; a polygon under one hectare or with an invalid geometry is refused with a clear message at the estimate step. Weighted figures are labelled with the weighting in every table header ("animal-days per ha, livestock units").

### 9.4 UI

Route `/projects/{id}/analyze/grazing`, item "Grazing" under Analyze when the module is on.

1. The form: herd (group, entities or type), areas (a multi-select of the project's zones and geofences with an "all management units" preset when the convention is used, and a "Draw on the map" link to the Features page), period, comparison (off, previous period, seasons, another herd), weighting (equal, attribute with the key, metabolic), options in "Method".
2. The estimate line and Run, as in movement.
3. The result: a map with the areas coloured by relative pressure (a five-step ramp in the brand palette) and the hotspot cells inside them, a table of areas with the metrics (secondary columns hidden on a phone), a timeline chart of daily animal-hours per area (stacked bars or lines, toggle), a bar chart of animal-days per hectare per area, a rest calendar strip per area (days as cells), the warnings callout, the actions of movement.
4. Contextual entries: a group's row on the Groups page and the entities list group filter get "Analyse grazing" when the module is on; a zone's panel on the live map and the Features page get "Grazing in this area" that opens the form with the area chosen.

### 9.5 Reports

Phase 1 delivers a kept run with a name and a link, its tables as CSV and XLSX, and its geometries as GeoJSON. A "Monthly grazing utilisation report" as a stable document (a PDF or a fixed page with a date and a version) is the report concept of section 18 and is not built now; the result document already holds every number and the provenance such a report needs, and `source_run_id` links a re-run to its origin, so a report can later be a kept run rendered to a page.

### 9.6 Limitations, stated in the interface

- Time in an area is a proxy for potential grazing pressure. It is not measured feeding. The table header says "use (animal-days per ha)", not "grazing".
- Only collared animals count. The herd size is not extrapolated unless the person chooses a weighting, and the document then names it.
- Fix sampling and gaps bias the hours; the missing fix share and the gap share are shown next to the totals.
- Overlapping areas double-count by design; the overlap is listed.
- Areas are fixed polygons without validity in time; an area that changed during the period must be two features.

### 9.7 Future environmental enrichment, not built

Level 2 (landscape context): vegetation class, habitat, soil, terrain, water, management attributes per area, read through the provider extension point of section 11 and joined to the area table as extra columns. Level 3 (environmental response): NDVI or EVI, biomass, rainfall, vegetation recovery, seasonal baselines, as time series per area from a provider. Level 4 (management interpretation): forage demand, carrying capacity, utilisation thresholds, over and under-grazing indicators, recommendations, only after level 3 data and a validation with the users, and always with the method and its uncertainty in the document. None of these is a prerequisite for level 1, and the level 1 tables are complete without them.

## 10. Shared primitives

Only what both modules need now, each with the question "is it required by movement or grazing today" answered yes:

| Primitive | Movement | Grazing | Where |
| --- | --- | --- | --- |
| Trajectory retrieval per subject (fixes with effective time and geometry, device fixes, valid, assignment windows, streamed with `yield_per`) | yes | yes | `primitives/trajectory.py` |
| Steps, gaps, time weights per fix | yes | yes | `primitives/trajectory.py` |
| Distance on the sphere (the existing haversine, moved to `shared/shared/geodesy.py` so the rule evaluator and the satellite module share it) | yes | no (hotspots use the grid) | `shared/shared/geodesy.py` |
| Grid cells in a local metric frame, residence time and visits per cell | yes | yes | `primitives/spatial.py` |
| Spatial containment of fixes in chosen polygons (SQL) | no | yes | `primitives/spatial.py` |
| Polygon area in hectares (SQL) | yes (home range) | yes | `primitives/spatial.py` |
| Clusters (`ST_ClusterDBSCAN`) | yes | no | `primitives/spatial.py` |
| Home range MCP and KDE | yes | no | `primitives/homerange.py` |
| Calendar buckets in the project time zone, day and night, seasons | yes | yes | `primitives/timeagg.py` |
| Period comparison (the same computation over two windows, a difference table) | yes | yes | `base.py` helpers |
| Group comparison (rows per subject, a mean row) | yes | yes | `base.py` helpers |
| Data quality checks | yes | yes | `quality.py` |

Not built: a generic metric registry for analyses, a pipeline or DAG framework, a plug-in loader, a raster stack, a scheduler, a query builder. Track segmentation beyond stationary and moving runs is not needed by either module.

## 11. Minimal GIS and environmental extension point

Phase 1 needs one GIS input: management polygons, which are project features. No GIS layer concept is added.

For later levels, `shared/shared/analysis/environment.py` defines the boundary without implementing a provider:

```
class EnvironmentalDataProvider(Protocol):
    key: str  # "project_layers", "sentinel_ndvi", ...
    layers: tuple[str, ...]  # what it can answer: "vegetation_class", "ndvi", ...

    async def sample(
        self, layer: str, geometries: Sequence[BaseGeometry], period: Period, project_id: UUID
    ) -> LayerSample: ...


PROVIDERS: dict[str, EnvironmentalDataProvider] = {}  # empty in phase 1
```

Rules recorded now so the first provider does not couple a module to a source:

- A module asks for a layer by name and gets a `LayerSample` (values per geometry, or a time series per geometry, with the source, the resolution and the sampling time). It never names a provider.
- Providers are registered in order of preference; a project-specific provider (project GIS uploads, later) overrides an open global one for the same layer.
- A provider failure raises inside `sample`; the module catches it, adds a warning to the document and completes without the layer. Level 1 never calls a provider.
- Provider settings (keys, endpoints) live in `data_sources` or `server_settings` when a provider exists, not in the analysis package.

That is the whole extension point. No provider, no cache table, no raster store is built.

## 12. API proposal

All under `/api/v1`, project-scoped, with `limit` and `next_cursor` on the list.

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /analysis-modules` | signed in | the enabled modules with key, label, version, limits; used by the sidebar and the forms |
| `GET /projects/{id}/analyses?module=&status=&limit=&cursor=` | `project:read` | newest first, hidden when a run's subjects fall outside the reader's scope |
| `POST /projects/{id}/analyses` | `analysis:run` | body `{module, parameters, name?}`; validates with the module's model, narrows to scope, checks the bounds (422 with the reason), creates the row, audits, publishes; 201 with the run |
| `GET /projects/{id}/analyses/estimate?module=&...` | `analysis:run` | the counts and the bound verdict |
| `GET /projects/{id}/analyses/{run}` | `project:read` | the row with the result document when completed |
| `PATCH /projects/{id}/analyses/{run}` | `analysis:run` (own) or `project:write` | `name` |
| `POST /projects/{id}/analyses/{run}/cancel` | same | |
| `POST /projects/{id}/analyses/{run}/rerun` | `analysis:run` | new run, `source_run_id` |
| `DELETE /projects/{id}/analyses/{run}` | same as PATCH | |
| `GET /projects/{id}/analyses/{run}/geometries?kind=&subject_id=&limit=` | `project:read` | GeoJSON FeatureCollection, at most 2,000 features per call |
| `GET /projects/{id}/analyses/{run}/export?what=summary|comparison|areas|timeline|geometries|document&format=csv|xlsx|json|geojson` | `project:read` | the existing writers, direct |

Parameter models (`schemas/analysis.py`): `MovementParameters` (subjects as `entity_ids`, `group_id` or `entity_type_id`, `time_from`, `time_to`, `comparison`, the options of 8.1) and `GrazingParameters` (subjects, `feature_ids`, period, comparison, `weighting`, options), each with the bounds as pydantic constraints and a `subjects_resolved` step in the router that expands a group or a type to entity ids inside the caller's visibility and stores the ids in `parameters` so the run is reproducible later even when the group changes.

The all-projects scope is not supported in phase 1: the routes take a project id and answer 404 for `all`.

MCP: no analysis tool in phase 1. A read tool that lists and reads runs is a small follow-up under the existing read scopes; it is noted, not planned.

## 13. Database proposal

- Migration 0029: the two tables of section 6 with their indexes and check constraints; the downgrade drops them. No change to any existing table.
- No new index on `positions`: the run reads by `(entity_id, time)` and the containment join uses the GiST index on `geom`, both present.
- No continuous aggregate, no materialised view, no cache table. The result document is the cache; a kept run is the saved analysis.
- Cleanup: expired runs deleted by the analysis worker's hourly cleanup loop, geometries by cascade.
- Size: a movement run over 25 subjects stores a document under 1 MiB and at most a few hundred geometry rows; a grazing run over 50 areas and a year stores under 2 MiB (the daily timeline is 50 by 366 numbers). The 4 MiB cap refuses anything larger with `INPUT_TOO_LARGE` and a message that suggests fewer subjects or areas.

## 14. Performance and resource isolation

Bounds, as constants in `shared/shared/analysis/limits.py` with `Settings` overrides for the ones an operator may tune:

| Bound | Default | Where enforced |
| --- | --- | --- |
| Subjects per movement run | 25 | parameters, estimate |
| Animals per grazing run | 100 | parameters, estimate |
| Areas per grazing run | 50 | parameters |
| Days per run | 366 | parameters |
| Fixes per run (`ANALYSIS_MAX_FIXES`) | 500,000 | estimate (422) and the runner (stops with `INPUT_TOO_LARGE`) |
| Fixes per subject in memory | 200,000 | trajectory loader |
| KDE grid | 250 by 250 | parameters |
| Geometries per run | 5,000 | runner |
| Result document | 4 MiB | runner |
| Runs in progress per worker (`ANALYSIS_CONCURRENCY`) | 1 | handler semaphore |
| Run wall clock (`ANALYSIS_TIMEOUT_SECONDS`) | 900 | `asyncio.wait_for` |
| Statement timeout in a run (`ANALYSIS_STATEMENT_TIMEOUT_SECONDS`) | 300 | `SET LOCAL` |
| Queued runs per project | 5 | POST answers 429 with the count |
| Runs kept per project | 200 kept plus 30 days of others | cleanup |

Why the core stays responsive:

- The API never computes; its analysis endpoints are index reads and one count under the 120 second timeout.
- The worker reads with `yield_per` and frees per-subject arrays; the export benchmark shows the worker under 130 MiB while streaming 22 million rows, and a run reads at most 500,000.
- One run at a time in the analysis worker, a process of its own; exports and curation jobs keep their worker and never wait for an analysis.
- PostgreSQL work is bounded by the statement timeout per run and by reading through the existing indexes; a containment join is limited to the run's fixes and at most 50 polygons.
- Cancellation is checked between steps (load, steps, grid, clusters, home range, document) and the statement timeout ends a long statement.
- Retry: a failed run is stored, never retried by the bus (the handler does not raise); a person re-runs by hand. A crash is retried by the bus reclaim up to `BUS_MAX_ATTEMPTS`.
- Caching: the run itself. The same parameters run twice produce two runs; the interface offers the last completed run with the same parameters before creating a new one (a lookup on `(project_id, module)` and an equality on `parameters`).
- Incremental calculation: not in phase 1. A monthly grazing run over a year reads a year; at 25 fixes an hour per animal and 100 animals that is under 22 million fixes only at the extreme, and the fix bound refuses that with a suggestion to split the period. If a project wants rolling monthly summaries, a scheduled re-run is the later feature, and incremental accumulation the one after.

Measured before the merge: the benchmark script gains two runs on the 0.2 scale dataset (a movement run over one subject and a year, a grazing run over 20 animals, 10 areas and 90 days) with budgets of 120 and 180 seconds, and a check that the live map and the tracks reads stay within their budgets while a run is in progress.

## 15. Permissions

- One new key `analysis:run` in the area `exports_and_analysis` ("Run analyses and keep their results"), granted to the analyst and admin built-in roles, available to custom roles. Reading runs and results needs `project:read`, the same as reading tracks, because a result is derived from data the reader may already see.
- A member's scope applies twice: at creation the subjects are narrowed to the caller's visibility (a group expands only to visible entities; an explicit entity outside the scope is refused with 422), and at read a run whose stored subjects include an entity outside the reader's scope is hidden from the list and answers 404. Area features are visible to every member already.
- Deleting or renaming a run: the creator, or `project:write`.
- Server admins have every key. The all-projects scope is not offered.
- The route guard: `RequireProjectPermission permission="project:read"` is a no-op, so the two pages are guarded by the module flag (a page for a disabled module redirects to the map), and the Run button by `can("analysis:run")`.

## 16. Feature flags

Three levels, using mechanisms that exist:

1. Deployment: `ANALYSIS_MODULES` in `Settings` (`analysis_modules: str = "movement,grazing"`), `.env.example`, the compose anchor and `env.j2`. Empty disables the subsystem: the router registers no analysis routes except the catalogue answering an empty list, the worker ignores the topic (and logs a queued run as skipped, marking it failed with `MODULE_DISABLED`), the sidebar shows no items.
2. Project: `projects.settings.analysis_modules`, an optional list edited on the project settings page by a project admin (`project:write`), narrows the deployment list. Absent means all enabled modules.
3. Person: `analysis:run` per role.

The project list (`ProjectWithRole`) gains `analysis_modules: list[str]` computed from 1 and 2, so the frontend needs no extra request and `usePermissions` gains a sibling `useAnalysisModules(projectId)` reading the same list. Movement and grazing are independent entries in the list, so either can be off alone. No new table, no flag framework.

## 17. Testing strategy

- Unit, primitives (`tests/shared/test_analysis_trajectory.py`, `test_analysis_spatial.py`, `test_analysis_homerange.py`, `test_analysis_timeagg.py`, `test_analysis_quality.py`): a square walk of side 1 km gives a distance of 4 km, four turning angles of 90 degrees and a displacement of zero; a straight walk gives a displacement equal to the distance; a gap longer than the threshold is excluded and counted; steps below the speed threshold form a stationary period of the right length; residence time on a grid for a subject sitting in one cell equals the period; two visits separated by a longer absence count as two; the MCP of the corners of a square is that square with the right hectares; the KDE of a Gaussian point cloud with a known standard deviation gives a 95 percent area within 15 percent of the analytic value and a 50 percent area inside the 95 one; day and night classification at a known place and date; seasons in a southern hemisphere time zone.
- Spatial intersection (`tests/shared/test_analysis_spatial.py` on the migrated database): fixes inside, outside and on the boundary of a polygon; a fix inside two overlapping polygons counts in both; a circle feature; a multipolygon; hectares of a known polygon.
- Residence time and grazing normalisation (`tests/shared/test_analysis_grazing.py`): a herd of two animals in an area of 10 hectares for 24 hours gives 48 animal-hours, 2 animal-days, 0.2 animal-days per hectare; the gap cap keeps a silent day out; weighting by an attribute doubles one animal; missing attribute values fall back to one and warn; relative pressure averages to 1 over the areas; rest days are counted.
- Known movement examples: a fixture track recorded from a real collar (the dev server's SP051890 export, anonymised) with expected totals computed once by hand and by an independent script, kept under `tests/fixtures/analysis/`.
- API (`tests/api/test_analyses.py`): every role against every endpoint (the access matrix gains the routes with the viewer allow-list for reads); scope narrowing on creation and on read; 422 for each bound; 404 for a disabled module; the lifecycle through the worker handler run in the test process; cancel of a queued run; rerun links the source; export in each format; the estimate's counts; list pagination.
- Worker (`tests/analysis/test_worker.py`): a completed run end to end on the shared test database; a module that raises stores `ANALYSIS_FAILED` and the handler returns; a timeout stores `ANALYSIS_TIMEOUT`; a redelivered message for a completed run does nothing; a disabled module stores `MODULE_DISABLED`; an export job queued during a run still completes.
- Isolation (`tests/shared/test_analysis_boundary.py`): imports of the core packages do not pull `shared.analysis`; the analysis package writes only to `analysis_*` tables (checked by inspecting the statements the runner issues against a mock session in one test, and by the migration's table list in another).
- UI (Vitest): `lib/analysis.ts` URL state round-trip, the result document parsing and chart series building, the warning texts; component tests for the run status and the warnings callout; the navigation test extended for the two items and their hiding when the module list is empty; the sweep script picks the two routes up.
- Performance: the two benchmark runs of section 14 and the concurrent live map budget, recorded in `docs/operations/benchmarks.md`.
- Failure isolation on the dev server before the merge: stop the analysis worker, queue a run, confirm the live map, ingestion and the entity page work and the run shows "waiting for the worker"; start the worker and see it complete; set `ANALYSIS_MODULES=` and confirm the navigation is unchanged from today.

## 18. Implementation roadmap

Foundation required by movement and grazing (F), then movement (M), then grazing (G), then the validation and the gate (V). No other module has a phase.

- F1 package, registry, base types, limits, boundary test
- F2 migration 0029 and models
- F3 the analysis worker, the runner, the topic, the cleanup loop, the registrations
- F4 API router, schemas, permission key, flags, project list field
- F5 frontend foundation: routes, navigation, `lib/analysis.ts`, run list, run status, warnings callout, export menu
- F6 primitives shared by both modules: trajectory, time weights, grid residence, calendar, quality
- M1 movement metrics and charts data
- M2 clusters and home range (MCP, KDE)
- M3 movement page: form, estimate, result blocks, map layers
- M4 movement exports and the entity page entry
- M5 movement tests and docs
- G1 containment, area, use metrics, cycles
- G2 grazing page: form with areas and weighting, result blocks, map ramp, timeline
- G3 grazing comparison (periods, seasons, herds) and exports
- G4 grazing entries (groups, features, map panel) and docs
- V1 benchmark runs, dev server failure drill, sweep, docs, changelog, plan phase 22 rewrite, ADR 0031
- V2 decision gate review (section 20)

Order rationale: F6 before M1 because both modules stand on it; movement before grazing because the movement page proves the run, result and map machinery on one subject type before the grazing page adds areas and weighting; V1 before any merge.

Future scope, listed only so the architecture does not block it: contact analysis, habitat selection, animal health, biodiversity, patrol, fleet, infrastructure, water, human-wildlife conflict, connectivity, ecosystem condition, conservation outcomes, environmental providers, scheduled re-runs, dashboard tiles for runs, reports, an MCP read tool, GeoPackage, device subjects, smoothed KDE contours, Brownian bridge and autocorrelated methods.

## 19. Engineering tasks

Each task: objective, existing files, proposed files, backend, frontend, database, tests, dependencies, acceptance, priority, complexity.

### F1 analysis package and boundary

- Objective: the module boundary exists in code with nothing inside it but the contract.
- Existing files: `shared/shared/__init__.py`, `pyproject.toml` (mypy packages list).
- Proposed files: `shared/shared/analysis/__init__.py`, `base.py`, `limits.py`, `environment.py`; `tests/shared/test_analysis_boundary.py`.
- Backend: `AnalysisModule` protocol (`key`, `label`, `version`, `Parameters` model, `async run(ctx, params, progress) -> ResultDocument`), `ResultDocument`, `Warning`, `Provenance` pydantic models, `MODULES` registry, `enabled_modules(settings)`, the limits constants, the empty provider registry.
- Frontend: none.
- Database: none.
- Tests: the boundary import test; the registry lists both keys; a disabled list yields nothing.
- Dependencies: none.
- Acceptance: mypy strict passes; the boundary test passes; no core module imports the package.
- Priority: 1. Complexity: S.

### F2 tables and models

- Objective: `analysis_runs` and `analysis_geometries` exist with a migration up and down.
- Existing files: `services/api/alembic/versions/0028_position_accuracy.py` (template), `shared/shared/models/__init__.py`.
- Proposed files: `shared/shared/models/analysis.py` (namespace-safe name: `analysis_runs` module), `services/api/alembic/versions/0029_analysis_runs.py`.
- Backend: the two models, enums `AnalysisStatus`, exports in `models/__init__`.
- Database: section 6.
- Tests: the migration round trip already runs in every test session; a model test inserts a run and a geometry and reads them back with `ST_Area`.
- Dependencies: F1.
- Acceptance: `alembic upgrade head` and `downgrade -1` clean; the tables carry the indexes.
- Priority: 1. Complexity: S.

### F3 the analysis worker, the runner, the topic, the cleanup loop

- Objective: a queued run becomes a completed or failed row in a worker of its own, without the API doing any work.
- Existing files: `shared/shared/bus.py` (`Topic`), `services/export/protect_export/main.py` and `services/export/pyproject.toml` (patterns), `shared/shared/exports/runner.py` (pattern), `shared/shared/worker.py`, `services/api/protect_api/routers/network.py` (`WORKERS`, `GROUPS`), `services/rules/protect_rules/system_checks.py` (`WORKERS`, `CONSUMERS`), `scripts/verify-server.sh`, `docker/python.Dockerfile` (two COPY lines), `docker-compose.yml`, `pyproject.toml` (workspace sources, dev group, mypy packages), `.github/workflows/ci.yml` (matrix), `shared/shared/config.py`, `.env.example`, `ansible/roles/app-deploy/templates/env.j2`, `docs/operations/observability.md`.
- Proposed files: `services/analysis/pyproject.toml`, `services/analysis/protect_analysis/__init__.py`, `services/analysis/protect_analysis/main.py`, `shared/shared/analysis/runner.py`, `tests/analysis/__init__.py`, `tests/analysis/test_worker.py`.
- Backend: `Topic.ANALYSIS_REQUESTED = "analysis.requested"`; the worker `analysis` subscribing to it with the handler and its semaphore, and a background cleanup loop; `run_analysis` with status, timeout, statement timeout, progress through a short session, cancellation checks, result cap, failure storage; `expire_analyses`; settings `analysis_modules`, `analysis_concurrency`, `analysis_timeout_seconds`, `analysis_statement_timeout_seconds`, `analysis_max_fixes`; the worker in `network.WORKERS` and `GROUPS`, `system_checks.WORKERS` and `CONSUMERS`, and the verify script; the compose service `analysis` (`*python-build`, `*python-env`, `depends_on` like the export worker); the CI matrix entry.
- Frontend: none.
- Database: none beyond F2.
- Tests: section 17, worker.
- Dependencies: F1, F2.
- Acceptance: a run of a stub module completes in the test; a raising stub stores the failure and the handler returns; a timeout stores `ANALYSIS_TIMEOUT`; dead letters stay at zero; `docker compose config` lists the service and `scripts/verify-server.sh` reads its heartbeat; the system status names the worker when it is silent.
- Priority: 1. Complexity: M.

### F4 API and permissions

- Objective: the endpoints of section 12 with scope, bounds, flags and audit.
- Existing files: `shared/shared/permissions.py`, `services/api/protect_api/routers/__init__.py`, `deps.py`, `visibility.py`, `routers/exports.py` (pattern), `routers/projects.py` (`ProjectWithRole`), `schemas/access.py`, `docs/administration/permissions.md`, `tests/api/test_access_matrix.py`.
- Proposed files: `services/api/protect_api/routers/analyses.py`, `schemas/analysis.py`, `tests/api/test_analyses.py`.
- Backend: the key `analysis:run` in `exports_and_analysis`, the analyst and admin sets; the router; subject resolution and narrowing; the estimate count; the export through the writers; `analysis_modules` on the project list; the project settings field and its PATCH validation.
- Frontend: none here.
- Database: none.
- Tests: section 17, API; the access matrix rows.
- Dependencies: F1 to F3.
- Acceptance: every endpoint bounded and tested per role; OpenAPI regenerated; the permissions doc names the key.
- Priority: 1. Complexity: M.

### F5 frontend foundation

- Objective: the two pages exist as shells with a run list, status and the shared result blocks, hidden when the modules are off.
- Existing files: `App.tsx`, `components/layout/navigation.ts`, `Sidebar.tsx`, `hooks/useProjects.ts`, `api/queryKeys.ts`, `api/types.ts`, `pages/project/ExportsPage.tsx` (pattern), `components/analytics/ExportDialog.tsx`.
- Proposed files: `pages/project/MovementPage.tsx`, `GrazingPage.tsx` (shells), `components/analysis/RunList.tsx`, `RunStatus.tsx`, `WarningsCallout.tsx`, `ResultTable.tsx`, `ResultChart.tsx`, `ExportMenu.tsx`, `SubjectPicker.tsx`, `PeriodPicker.tsx`, `lib/analysis.ts`, `lib/analysis.test.ts`, `components/layout/navigation.test.ts` (extended).
- Frontend: routes `analyze/movement`, `analyze/grazing` under a module guard; navigation items with `permission` unset and a `modules` filter; `useAnalysisModules`; query keys `analyses`, `analysis`, `analysisGeometries`, `analysisModules`; polling every 3 seconds while queued or running; the run list with `usePages`; the export menu.
- Backend: none.
- Database: none.
- Tests: the Vitest items of section 17 for `lib/analysis.ts` and navigation; the sweep.
- Dependencies: F4.
- Acceptance: with `ANALYSIS_MODULES=` the sidebar equals today's; with modules on the items show and the shells load at three widths without console errors.
- Priority: 1. Complexity: M.

### F6 shared primitives

- Objective: trajectory loading, steps, time weights, grid residence, calendar and quality checks, tested on synthetic tracks.
- Existing files: `shared/shared/curation/effective.py`, `shared/shared/rules/evaluator.py` (haversine constant), `shared/shared/connectivity/satellite.py` (the second copy).
- Proposed files: `shared/shared/geodesy.py`, `shared/shared/analysis/primitives/trajectory.py`, `spatial.py` (grid part), `timeagg.py`, `shared/shared/analysis/quality.py`, `tests/shared/test_analysis_trajectory.py`, `test_analysis_timeagg.py`, `test_analysis_quality.py`, `tests/fixtures/analysis/`.
- Backend: the haversine moved to `geodesy.py` and both callers pointed at it; `load_trajectory(session, entity_id, window, filters) -> Trajectory` (numpy arrays: times, lat, lon, accuracy, satellites; streamed, bounded); `steps(trajectory, gap_seconds)`; `time_weights`; `local_grid(mean_lat, cell_m)`, `residence(trajectory, grid, min_absence)`; `sun_class(times, lat, lon)`, `calendar_days(times, tz)`, `seasons(window, tz, hemisphere)`; `quality_report(trajectory, steps, options)`.
- Frontend: none.
- Database: none.
- Tests: section 17, unit.
- Dependencies: F1; numpy declared in `shared/pyproject.toml` (already installed transitively).
- Acceptance: the synthetic cases pass with tolerances; a 200,000 fix trajectory loads under 5 seconds and 100 MiB in a local measurement recorded in the task's commit message.
- Priority: 1. Complexity: L.

### M1 movement metrics

- Objective: the movement module produces the metrics, tables and chart data of 8.2 to 8.4 without the spatial layers.
- Existing files: F6 outputs.
- Proposed files: `shared/shared/analysis/modules/movement.py`, `tests/shared/test_analysis_movement.py`.
- Backend: `MovementParameters`, the run over subjects and periods, the document assembly, the comparison tables, the provenance block, progress per subject.
- Tests: the square and straight walks through the module; a comparison run; the document validates against `ResultDocument`.
- Dependencies: F1 to F3, F6.
- Acceptance: a run over the fixture track reproduces the expected totals within 1 percent.
- Priority: 2. Complexity: M.

### M2 clusters and home range

- Objective: MCP, KDE with 50 and 95 percent isopleths, clusters and hotspot cells as geometries.
- Proposed files: `shared/shared/analysis/primitives/homerange.py`, `spatial.py` (clusters), `tests/shared/test_analysis_homerange.py`, `test_analysis_spatial.py`.
- Backend: `mcp(points, percent)`, `kde_grid(points, bandwidth, cells)`, `isopleths(grid, levels)`, `reference_bandwidth(points)`, `clusters_sql(session, run, subject, eps_m, min_points)`, hectares through `ST_Area`; geometry rows written per subject; the movement module calls them when the methods are on.
- Tests: section 17, unit and spatial.
- Dependencies: M1.
- Acceptance: the Gaussian cloud test within tolerance; a run over 25 subjects and a year of the benchmark data stays under the 250 by 250 grid and the geometry cap.
- Priority: 2. Complexity: L.

### M3 movement page

- Objective: the question-oriented page of 8.7 with the map layers of 8.5 and the charts of 8.6.
- Existing files: `components/map/layers.ts`, `useMap.ts`, `lib/chartStyle.ts`, `components/explore/ExploreChart.tsx` (for reference, not reused as is).
- Proposed files: `components/map/analysisLayers.ts` (+ test), `components/analysis/MovementForm.tsx`, `MovementResult.tsx`, `ResultMap.tsx`, `SubjectCards.tsx`; `MovementPage.tsx` filled.
- Frontend: URL state, the estimate line, Run, the result blocks, layer toggles, the geometry popup, the phone layout.
- Dependencies: F5, M1, M2.
- Acceptance: the flow of 8.7 on the dev server with two animals; the sweep at three widths; strings extracted.
- Priority: 2. Complexity: L.

### M4 movement exports and entry points

- Objective: result exports and "Analyse movement" on the entity page.
- Existing files: `pages/project/EntityPage.tsx`, `routers/analyses.py`.
- Frontend: the export menu wired to `what` and `format`; the header action on the entity page behind the module flag and `can("analysis:run")`; "Export the fixes" opening the export dialog with the positions dataset preset.
- Tests: an API test per export format; a Vitest test of the preset.
- Dependencies: M3.
- Acceptance: GeoJSON of a run opens in QGIS with the polygons and their attributes.
- Priority: 2. Complexity: S.

### M5 movement tests and docs

- Objective: the documentation and the changelog for movement.
- Proposed files: `docs/analytics/movement.md`, `mkdocs.yml` nav entry, `DEVELOPERS.md` section "Analysis", `docs/administration/pages.md` rows, `CHANGELOG.md`.
- Acceptance: `mkdocs build --strict` passes; the docs name the limitations of 8.10.
- Dependencies: M1 to M4.
- Priority: 2. Complexity: S.

### G1 grazing metrics

- Objective: the grazing module with containment, area normalisation, visits, cycles and weighting.
- Proposed files: `shared/shared/analysis/modules/grazing.py`, `spatial.py` (containment, area), `tests/shared/test_analysis_grazing.py`, `test_analysis_spatial.py` (extended).
- Backend: `GrazingParameters`, `containment_sql(session, run_fixes, feature_ids)`, `area_hectares`, the per-area and per-animal tables, the timeline, rest days, relative pressure, weighting with the warnings, the seasons split, the herd comparison.
- Dependencies: F6, M1 (time weights and residence reused).
- Acceptance: the normalisation cases of section 17; a run over the benchmark's park polygons completes within the budget.
- Priority: 3. Complexity: L.

### G2 grazing page

- Objective: the page of 9.4 with the area picker, the weighting choice, the map ramp, the timeline and the rest strip.
- Proposed files: `components/analysis/GrazingForm.tsx`, `GrazingResult.tsx`, `AreaPicker.tsx`, `RestStrip.tsx`; `GrazingPage.tsx` filled; `analysisLayers.ts` extended with the area ramp.
- Dependencies: F5, G1.
- Acceptance: the flow on the dev server with a herd and three drawn zones; the sweep.
- Priority: 3. Complexity: L.

### G3 grazing comparison and exports

- Objective: periods, seasons and herds compared in tables and charts; exports of areas and timeline.
- Dependencies: G1, G2.
- Acceptance: a two-period run shows the differences; the CSV of the areas table opens with the weighting in the headers.
- Priority: 3. Complexity: M.

### G4 grazing entries and docs

- Objective: "Analyse grazing" from the groups page and the entities group filter, "Grazing in this area" from the feature panel and the Features page; `docs/analytics/grazing.md` with the limitations of 9.6 and the levels of 9.7.
- Existing files: `GroupsPage.tsx`, `EntitiesPage.tsx`, `components/map/FeaturePanel.tsx`, `FeaturesPage.tsx`.
- Dependencies: G2, G3.
- Acceptance: the entries appear only with the module on; docs build.
- Priority: 3. Complexity: S.

### V1 validation

- Objective: the evidence for the decision gate.
- Existing files: `scripts/benchmark/run.py`, `docs/operations/benchmarks.md`, `PROJECT_PLAN.md`, `docs/adr/`.
- Backend and scripts: the two benchmark runs and the concurrent budget check; the dev server drill of section 17.
- Docs: phase 22 rewritten from this plan with its decisions numbered from D196 (D195 went to the layers panel's arrangement on 2026-09-13), ADR 0031 "Analysis as an isolated, optional subsystem", the changelog, this file reduced to a pointer.
- Acceptance: budgets met and recorded; the drill passed; the docs build; the plan and ADR merged with the code in one review.
- Dependencies: everything above.
- Priority: 1 before the merge. Complexity: M.

## Progress on the branch

- F1 done on 2026-09-14: `shared/shared/analysis/` (`__init__.py` registry and `enabled_modules`, `base.py` contract, `limits.py`, `environment.py` provider boundary), `Settings.analysis_modules`, `tests/shared/test_analysis_boundary.py` (no core module imports the package, the setting gates the catalogue, no provider in phase 1). mypy strict clean.
- F2 done on 2026-09-14: `AnalysisStatus` and `AnalysisModuleKey` enums, `shared/shared/models/analysis.py` (`AnalysisRun`, `AnalysisGeometry`), migration `0029_analysis_runs.py`, `tests/api/test_analysis_models.py` (round trip, the area from PostGIS, cascade). The migration runs up and down in CI's test session.
- F3 done on 2026-09-14: the worker `services/analysis` (`protect_analysis.main`, one run at a time, an hourly cleanup), `shared/shared/analysis/runner.py` (`run_analysis` with the statement timeout, the wall clock, progress and cancellation through a short session, the result cap, the geometries with their area from PostGIS, every outcome stored on the row; `expire_analyses`), `Topic.ANALYSIS_REQUESTED`, the settings `ANALYSIS_CONCURRENCY`, `ANALYSIS_TIMEOUT_SECONDS`, `ANALYSIS_STATEMENT_TIMEOUT_SECONDS`, `ANALYSIS_MAX_FIXES` (compose, `.env.example`, `env.j2`), the worker in the five lists, the Dockerfile, the workspace, the compose service `analysis`, the CI matrix, `tests/analysis/test_worker.py` (six cases with a stub module). CI runs on the branch through a draft pull request, never merged by hand.
- F4 done on 2026-09-14: the key `analysis:run` (area exports and analysis, the analyst and admin sets, the frontend catalogue, the permissions doc), `shared/shared/analysis/parameters.py` (`SubjectSelection`, `Window`, `CommonParameters`), `project_modules(settings, project_settings)`, `schemas/analysis.py`, `routers/analyses.py` (the catalogue, the estimate, the list, create with subject resolution from ids, a group or a type inside the caller's scope, the queue cap, read, keep by name, cancel, rerun, delete, geometries as GeoJSON, export as JSON, GeoJSON or CSV of a table), `analysis_modules` on the project list, `tests/api/test_analyses.py` (three tests over a stub module: the life of a run, subjects and bounds, roles, scope and flags). The plan's code fences lost their language tag because ruff lints fenced Python in Markdown.
- F5 done on 2026-09-14: the navigation items Movement and Grazing carry a `module` and show only when the project offers it (the sidebar and the command palette filter on `useAnalysisModules`), `RequireAnalysisModule` guards the routes `analyze/movement` and `analyze/grazing`, `lib/analyses.ts` (the result document types, the form state in the URL, the windows) with its test, `components/analysis/` (`RunList` polling while a run is active, `RunStatus`, `WarningsCallout`, `ResultTable`, `ResultChart` over `echarts/core`, `RunView` with keep, export, run again, cancel and delete), the two page shells listing and showing runs, the query keys and types. The forms and the maps come with the modules.
- F6 done on 2026-09-14: `shared/shared/geodesy.py` (the one haversine, `metres_between` for GeoJSON order, `bearing_deg`; the rule evaluator and the satellite module call it now), `shared/shared/analysis/primitives/trajectory.py` (`load_trajectory` streams a subject's device fixes at their effective time and geometry into arrays, `steps` with the gap flag, `turning_angles`, `time_weights` capped at the gap threshold, `exclude_impossible` measured from the last kept fix), `primitives/spatial.py` (`LocalGrid` on a tangent plane, `residence` with time and visits per cell, `hotspots`), `primitives/timeagg.py` (the sun's elevation by the NOAA approximation for day, twilight and night, local days, meteorological seasons with the southern swap), `shared/shared/analysis/quality.py` (`quality_report`: few fixes, missing share, gaps, irregular sampling, impossible speeds, duplicates, poor GNSS), numpy declared in `shared/pyproject.toml`, `AnalysisTooLarge` moved to `base.py` so a primitive can raise it. Three synthetic test files under `tests/shared/`: a square walk, a gap, an outlier, a grid, the sun at Amersfoort, the seasons, the warnings. The committed OpenAPI schema was regenerated after the catalogue route lost its query parameter in F4.
- M1 done on 2026-09-14: `shared/shared/analysis/modules/movement.py` (`MovementParameters` with the defaults of 8.1, `analyse_trajectory` for one subject and period: distance with the covered share, displacement and net squared displacement, speed summary and histogram, stationary periods, day, twilight and night by the sun, distance per local day and per hour, turning angles, residence and the hotspot cells; `build_document` with the summary table subject by period, the mean and standard deviation rows, the six charts and the provenance; `MovementModule.run` reading the subjects and the project time zone, streaming each trajectory, excluding impossible speeds, reporting progress per subject), `shared/shared/analysis/modules/__init__.py` registers the modules when the worker or the API imports it. `tests/shared/test_analysis_movement.py` (a straight walk within 1 percent, a resting animal, few fixes, the document with a comparison) and `tests/api/test_analysis_movement_run.py` (the run over inserted fixes through the API and the runner, the hotspot polygon with its area, the GeoJSON and CSV reads). Home range and clusters follow in M2.
- M2 done on 2026-09-14: `shared/shared/analysis/primitives/homerange.py` (`mcp` as the convex hull inside a percentile of distance from the centre, `reference_bandwidth`, `kde_grid` binning the weighted fixes on a grid of at most 250 cells a side and applying the Gaussian kernel by FFT convolution, `isopleths` as the union of the densest cells per level made valid and lightly simplified), `primitives/spatial.py` gains `clusters_sql` (`ST_ClusterDBSCAN` in the UTM zone of the fixes, the largest clusters with their convex hulls, fix counts and first and last use) and `hectares` (`ST_Area` on the geography). The movement module's `spatial_layers` fills `mcp95_ha`, `kde50_ha`, `kde95_ha`, `kde_bandwidth_m` and `cluster_count` and returns the polygons of kinds `mcp`, `kde` and `cluster` when the method is on and the subject has 30 fixes or more. `tests/shared/test_analysis_homerange.py` (the MCP of a square, a far fix outside the 95 percent MCP, the Gaussian cloud within 15 percent of the analytic area, weights); the API run test checks every kind lands with its area. Measured: 200,000 fixes through the KDE and its isopleths in well under a second.
- M3 done on 2026-09-14: the movement page of 8.7. `lib/analyses.ts` carries the method options in the URL (`gap`, `speed_max`, `cell`, `methods`, `kde`), builds the module's parameters and gives every subject the colour of its track; `components/analysis/MovementForm.tsx` (subjects with search, add a group with its subgroups, add a type, the period presets and a custom range, the comparison, the method folded with its defaults in one line, the estimate line, Run); `components/map/analysisLayers.ts` (+ test: the polygons in their subject's colour, the larger first, kinds toggled by a filter, a click reports the properties); `components/analysis/ResultMap.tsx` (the tracks of the main period, the polygons by kind with chips, fit, the picked polygon's label, area and share); `components/analysis/SubjectCards.tsx` (the figures that answer the question, the comparison beside each); `RunView` takes `render` blocks (summary, map, after), names subjects in the labels, and the charts keep the subject colour with the comparison dashed; `MovementPage.tsx` composes them, folds the form into a sheet on a phone and lists the limitations of 8.10 under the results. The English catalogue is extracted. Not yet seen on the dev server: the branch is not deployed there (main only), so the flow with two animals waits for a deployment Tim asks for.
- M4 done on 2026-09-14: "Analyse movement" on the entity page header (behind the module flag and `analysis:run`) opens the form with the entity and the default 30 days; the run view's export menu gains "The fixes behind it…" (behind `exports:create`), which opens the existing export dialog preset to the positions of the subjects over the main period as GeoJSON (`fixesPreset` in `lib/analyses.ts`, with its test). The export formats are covered by the API tests of F4 and the run test of M1.
- M5 done on 2026-09-14: `docs/analytics/movement.md` (the form, the run, the result, the method, what the figures cannot say, exports and API, switching it on and off), the nav entry and the index bullet, the "Analysis" section of `DEVELOPERS.md`, the Movement row of `docs/administration/pages.md`, the changelog (Added, Migrations, Upgrade notes). `mkdocs build --strict` passes.
- G1 done on 2026-09-14: `shared/shared/analysis/modules/grazing.py` (`GrazingParameters`: the areas as feature ids, the weighting with its key, seasons, a second herd, the visit absence, the cell, the rest threshold; `load_areas` reads the zones and geofences with their geodesic hectares and refuses what cannot be used; `containment` in shapely over the trajectory arrays already loaded, so the fixes are read once (a change from the SQL join of 9.1, same result); `area_use` gives the per-area figures of 9.2, the per-animal rows, the daily animal-hours and the herd totals for any window, so the comparison period and the seasons reuse it; `weights_of` with the warning naming the animals without a value; the hotspot cells inside each area and the areas with their relative pressure as geometries; overlaps as a notice and a table; the comparison table with the change in percent). The module's `check` runs at the estimate through a hook the API calls when a module has one, and the second herd is narrowed to the caller's scope like the subjects. `tests/shared/test_analysis_grazing.py` (two animals a day in ten hectares, a silent day, the weightings, relative pressure and rest days, visits) and `tests/api/test_analysis_grazing_run.py` (zones through the API, the tiny one refused, the run with its tables, charts and polygons).
- G2 done on 2026-09-14: `components/analysis/GrazingForm.tsx` (the herd as in movement, the areas from the project's zones and geofences with "All management units" for the convention and a link to draw one, the period, the comparison with nothing, the period before, the seasons or another herd as a group, the weighting with its key, the method folded: gap, absence, cell, rest threshold, speed), `AreaCards.tsx` (the herd's tracked hours and shares, a card per area with use per hectare, relative pressure and rank, animals, use and rest days, longest rest, hours since last use, the comparison beside the use), `RestStrip.tsx` (the use-and-rest calendar from the timeline series), `analysisLayers.ts` gains the `area` kind coloured by the five-step pressure ramp (+ test), `ResultMap` shows an area's hectares, use, pressure, rank and rest days; `GrazingPage.tsx` composes them with the limitations of 9.6; `lib/analyses.ts` carries the areas, the weighting, the second herd and the options in the URL and builds the module's parameters (+ tests); a shared hook resolves a group or a type named in the URL into entities for both forms.
- G3 done on 2026-09-14: the comparison table (main against the period before, the change in percent), the seasons as rows per season, the second herd as rows per herd, the use-per-hectare bars with one series per period or herd, and the exports of every table as CSV (the weighting in the unit of the headers), the polygons as GeoJSON and the fixes through the export dialog, all through the run view of F5.
- G4 done on 2026-09-14: "Analyse grazing" on a group's row of the Groups page and beside the entities list's group filter, "Grazing in this area" in a zone's panel on the live map and on the Features page (behind the module flag and `analysis:run`); `docs/analytics/grazing.md` with the limitations of 9.6 and the levels of 9.7, the nav entry, the index bullet, the pages-per-role row, the changelog and the developer notes. The API tests of F4 expect both modules in the catalogue now.
- V1 in part on 2026-09-14: ADR 0031 written and in the nav, phase 22 of `PROJECT_PLAN.md` rewritten from this plan with the decisions D196 to D203 in its table and a session log entry, the changelog carries both modules, `scripts/benchmark/run.py` gains the section `analysis` (the movement run over the busiest subject and a year, the grazing run over the twenty busiest animals of the last 90 days and ten `bench-zone-` squares it draws once over their extent, the worker's memory watched, the live map and a track read timed while the grazing run is in progress, budgets of 120, 180, 3 and 2.5 seconds). Not done, for want of a server that runs the branch: the measurements themselves, the concurrent budget check's numbers in `docs/operations/benchmarks.md`, and the dev server drill of section 17; this file is reduced to a pointer at the merge. Render tests of the subject cards, the area cards and the rest strip (`components/analysis/cards.test.tsx`) stand in for the browser check until then.
- Deployed on the dev server on 2026-09-14 at Tim's word (the playbook with `-e git_version=feature/analytics-movement-grazing`, last at 1036078): the analysis service runs, migration 0029 applied, both modules in the catalogue, a movement run over the two cows of the Smart Parks project and a grazing run over two test zones drawn around the meadow of "Rode geus koe 2081" (features "Analysis test zone West" and "East", marked as management units; both kept runs named "Test: …") complete in about 3 seconds each. Seen and fixed the same afternoon: the chart legend on one scrolling row above the plot, the map fitted to the polygons rather than to a track with a far outlier, the speed histogram on fixed bins so animals share one axis, the period and metric cells by their labels, no rank without a pressure, no overlap for zones that only touch, the rest strip's dates horizontal, the runs list inside a phone screen, the track as a line only on the result map. Still to do: the benchmark section and the drill of section 17.

## 20. Decision gate before future analytics

After movement and grazing are merged and have run on the dev server and with the first real project for at least one month, a review answers, with evidence:

- Adoption: how many people ran analyses, how often, which module, and whether they kept results.
- Performance: the benchmark numbers, the live map and ingest budgets during runs, the worker's memory, and any timeouts or failures in the run table.
- Maintenance: the size of the analysis package, the tests, and the issues raised.
- Deployment: whether stage 2 (a worker container) was needed and why.
- UI complexity: whether the analysis pages stayed out of the core pages and whether the entries confused anyone.
- Scientific usefulness: whether the metrics answered the questions the ecologists and the grazing managers asked, and which limitations mattered.
- Value against external tools: what people still export to QGIS or R, and why.
- Support: questions and mistakes seen.
- Architectural impact: any change made to core code for the sake of analysis, and whether the boundary held.

Only after that review does any further module (contact analysis, habitat, health, biodiversity, patrol, fleet, infrastructure, water, conflict, connectivity, ecosystem condition, outcomes) get a plan, and only when it meets the admission rule of section 17 of the brief: used repeatedly, the data already in Protect, integration adding substantial value, a real decision supported, substantially easier than external GIS, and a maintenance cost in proportion.

## 21. Final architecture review

- Can Protect core run completely without analytics: yes; no core module imports the package, the routes and the sidebar disappear with `ANALYSIS_MODULES=`, and the tables are separate.
- Does telemetry ingestion remain unchanged and non-blocking: yes; ingest and the decoder do not know the topic or the package.
- Does analytics primarily read core data: yes; it reads positions, features, assignments and groups and writes only `analysis_*` tables.
- Can analytics jobs fail without affecting core: yes; failures are stored on the run row, the handler never raises, and the worker is a process of its own that nothing else waits for.
- Can movement be disabled independently: yes, by the module list at deployment or project level.
- Can grazing be disabled independently: yes, the same way.
- Can environmental providers fail without affecting core or grazing level 1: yes; there are none in phase 1 and the contract makes a provider failure a warning inside a run.
- Are heavy calculations outside the main request path: yes; the API counts and reads rows, the worker computes.
- Are analytics tables logically separated: yes; the `analysis_` namespace, no foreign key into hypertables, cascade on the project only.
- Is the first implementation simpler than a general framework: yes; two modules, one runner, one document shape, no plug-in loader, no scheduler, no registry beyond a dict.
- Are we building only what movement and grazing require: yes; every primitive in section 10 is used by at least one of the two, and the provider extension point is one protocol and an empty dict.
- Can researchers still export to external tools: yes; result tables and geometries as CSV, XLSX, JSON and GeoJSON, raw fixes as GeoJSON and GPX through the existing export job.
- Is grazing useful before remote-sensing enrichment exists: yes; level 1 answers the management question from tracking and polygons alone, with its proxies named.
- Have we avoided detailed planning for future analytics: yes; section 18 lists them in one paragraph.
- Is all phase 1 work isolated on `feature/analytics-movement-grazing`: yes; this document is the only change, on that branch, and `main` is untouched.

Decisions approved by Tim on 2026-09-14 (numbered from D196 when they enter the plan):

- A. Analyses run in a worker of their own from the start: the compose service `analysis` from the same image, one run at a time, its own timeouts. Tim chose this over the proposal of sharing the export worker, for the cleaner isolation from exports and curation jobs.
- B. A run expires after 30 days unless kept by name; a kept run is the saved analysis; re-run creates a new run linked to the old one. The alternative of saved definitions as their own table is not built.
- C. Management areas are the project's zone and geofence features chosen per run, with an optional attribute convention for a preset; no new feature type and no project GIS layer concept in phase 1.
- D. Flags are `ANALYSIS_MODULES` at deployment, `projects.settings.analysis_modules` per project, and the key `analysis:run` per role; no flag framework.
- E. Dependencies stay at PostGIS, shapely and numpy; KDE isopleths are cell unions until a smoother contour is asked for; no scipy, pandas or geopandas.
- F. Subjects are entities in phase 1; devices as subjects are a follow-up.
- G. The result document lives in `analysis_runs.result` with a 4 MiB cap and the polygons in `analysis_geometries`; no MinIO object for results.
- H. The all-projects scope, dashboard tiles, reports, scheduled re-runs and an MCP tool are outside phase 1.
